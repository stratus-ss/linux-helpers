"""Faster Qwen3-TTS decoding on Intel XPU: an XPU-graph replacement for the per-frame code predictor.

Every audio frame (12.5 per second of audio), Qwen3-TTS runs its 28-layer talker once and then calls a full
HuggingFace `generate()` on the 5-layer code predictor to sample the other 15 codebooks. On the B70 that nested
`generate()` is pure launch and Python overhead: ~120 ms per frame for ~1000 tiny kernels, about 70% of the run.

`install(model)` swaps it for a fixed-shape loop: static KV buffers (16 slots), precomputed RoPE, the same sampling
as the stock generation config (temperature, top-k, top-p; no repetition penalty for the sub-talker), all 15 steps
captured once per batch size as a single torch.xpu.XPUGraph and replayed. The talker itself is left untouched.

Random draws differ from the stock path for the same seed (in-graph RNG), so a given seed gives a different (but
equally valid) take. Needs torch >= 2.10 with XPU graphs (torch.xpu.XPUGraph).
"""
import time
import torch
import torch.nn.functional as F
from torch.nn.attention import SDPBackend, sdpa_kernel


def _apply_rope(x, cos, sin):  # x (B, H, T, D); cos/sin (T, D)
    d = x.shape[-1] // 2
    rot = torch.cat((-x[..., d:], x[..., :d]), dim=-1)
    return x * cos + rot * sin


def _sample(logits, temperature, top_k, top_p):
    """logits (B, V) float -> (B,) long. Same warpers as HF: temperature, then top-k, then top-p."""
    logits = logits / temperature
    if top_k and top_k < logits.shape[-1]:
        kth = torch.topk(logits, top_k, dim=-1).values[:, -1:]
        logits = logits.masked_fill(logits < kth, float("-inf"))
    if top_p is not None and top_p < 1.0:
        srt, idx = torch.sort(logits, descending=False, dim=-1)
        cum = srt.softmax(dim=-1).cumsum(dim=-1)
        drop = cum <= (1 - top_p)
        drop[:, -1] = False
        logits = logits.masked_fill(drop.scatter(1, idx, drop), float("-inf"))
    probs = logits.softmax(dim=-1)
    q = torch.empty_like(probs).exponential_(1)  # Gumbel-style draw: argmax(p / Exp(1)) ~ Categorical(p)
    return torch.argmax(probs / q, dim=-1)


class FastCodePredictor:
    def __init__(self, talker, use_graph=True):
        self.cp = talker.code_predictor
        self.n_out = talker.config.num_code_groups - 1  # 15 codebooks sampled per frame
        self.n_pos = self.n_out + 1                       # 2 prefill positions + 14 decode steps
        m = self.cp.model
        p = next(self.cp.parameters())
        self.dev, self.dt = p.device, p.dtype
        a0 = m.layers[0].self_attn
        self.hd, self.scaling = a0.head_dim, a0.scaling
        self.n_kv = self.cp.config.num_key_value_heads
        self.rep = self.cp.config.num_attention_heads // self.n_kv
        pos = torch.arange(self.n_pos, device=self.dev)[None]
        cos, sin = m.rotary_emb(torch.zeros(1, device=self.dev, dtype=self.dt), pos)
        self.cos, self.sin = cos[0], sin[0]  # (n_pos, D)
        kpos = torch.arange(self.n_pos, device=self.dev)
        self.mask = kpos[None, :] <= kpos[:, None]  # (q pos, k pos) causal
        self.use_graph = use_graph
        self.graphs, self.static = {}, {}
        self.pool = torch.xpu.graph_pool_handle() if use_graph else None
        self.capture_s = 0.0
        self.sampling = None

    def _forward(self, h, start, kv):  # h (B, T, hidden) at positions start..start+T-1
        T = h.shape[1]; B = h.shape[0]
        cos, sin = self.cos[start:start + T], self.sin[start:start + T]
        mask = self.mask[start:start + T][None, None]
        for li, layer in enumerate(self.cp.model.layers):
            at = layer.self_attn
            x = layer.input_layernorm(h)
            q = at.q_norm(at.q_proj(x).view(B, T, -1, self.hd)).transpose(1, 2)
            k = at.k_norm(at.k_proj(x).view(B, T, -1, self.hd)).transpose(1, 2)
            v = at.v_proj(x).view(B, T, -1, self.hd).transpose(1, 2)
            q, k = _apply_rope(q, cos, sin), _apply_rope(k, cos, sin)
            kc, vc = kv[li]
            kc[:, :, start:start + T] = k
            vc[:, :, start:start + T] = v
            # GQA without repeat_interleave: fold the `rep` query heads that share a KV head into the query axis
            qf = q.reshape(B, self.n_kv, self.rep * T, self.hd)
            mf = mask.repeat(1, 1, self.rep, 1)
            y = F.scaled_dot_product_attention(qf, kc, vc, attn_mask=mf, scale=self.scaling)
            y = y.reshape(B, -1, T, self.hd).transpose(1, 2).reshape(B, T, -1)
            h = h + at.o_proj(y)
            h = h + layer.mlp(layer.post_attention_layernorm(h))
        return self.cp.model.norm(h)

    def _run(self, B):
        S = self.static[B]; cp = self.cp
        temp, top_k, top_p = self.sampling
        h = cp.small_to_mtp_projection(S["emb"])
        h = self._forward(h, 0, S["kv"])
        tok = _sample(cp.lm_head[0](h[:, -1]).float(), temp, top_k, top_p)
        S["out"][:, 0] = tok
        for s in range(1, self.n_out):
            x = cp.small_to_mtp_projection(cp.model.codec_embedding[s - 1](tok)[:, None])
            h = self._forward(x, s + 1, S["kv"])
            tok = _sample(cp.lm_head[s](h[:, -1]).float(), temp, top_k, top_p)
            S["out"][:, s] = tok

    def _alloc(self, B, emb_dim):
        hc = self.cp.config.hidden_size
        kv = [(torch.zeros(B, self.n_kv, self.n_pos, self.hd, device=self.dev, dtype=self.dt),
               torch.zeros(B, self.n_kv, self.n_pos, self.hd, device=self.dev, dtype=self.dt))
              for _ in self.cp.model.layers]
        self.static[B] = dict(emb=torch.zeros(B, 2, emb_dim, device=self.dev, dtype=self.dt), kv=kv,
                              out=torch.zeros(B, self.n_out, device=self.dev, dtype=torch.long))

    @torch.inference_mode()
    def __call__(self, inputs_embeds, do_sample=True, top_k=50, top_p=1.0, temperature=0.9, **_):
        assert do_sample, "fast code predictor only implements sampling (do_sample=True)"
        sampling = (float(temperature), int(top_k or 0), float(top_p if top_p is not None else 1.0))
        if self.sampling is None:
            self.sampling = sampling
        assert sampling == self.sampling, "sampling settings are baked into the captured graphs"
        B = inputs_embeds.shape[0]
        if B not in self.static:
            self._alloc(B, inputs_embeds.shape[-1])
        S = self.static[B]
        S["emb"].copy_(inputs_embeds)
        with sdpa_kernel(SDPBackend.MATH):
            if not self.use_graph:
                self._run(B)
            else:
                g = self.graphs.get(B)
                if g is None:
                    t = time.time()
                    s = torch.xpu.Stream(); s.wait_stream(torch.xpu.current_stream())
                    with torch.xpu.stream(s):
                        self._run(B)  # warmup outside capture (allocator, kernel JIT)
                    torch.xpu.current_stream().wait_stream(s)
                    g = torch.xpu.XPUGraph()
                    with torch.xpu.graph(g, pool=self.pool):
                        self._run(B)
                    self.graphs[B] = g; self.capture_s += time.time() - t
                g.replay()
        return _Result(S["out"].clone())


class _Result:
    def __init__(self, sequences):
        self.sequences = sequences


def limit_codec_batch(qwen_tts_model, max_frames=1024, bucket=64):
    """Decode codes in fixed-shape groups instead of the whole batch at once.

    The 12 Hz codec upsamples 1920x, so a whole batch of clone outputs (decoded with the reference codes prepended)
    makes multi-GB conv activations; on the B70 that intermittently failed with UR_RESULT_ERROR_OUT_OF_RESOURCES at
    batch 8-32. Each group is padded to a multiple of `bucket` frames and to a fixed row count
    (max_frames // padded length), so only a handful of shapes ever reach the conv kernels (each new shape costs a
    kernel JIT on XPU). Padding uses -1 codes, which upstream already uses for batches of unequal length and trims.
    """
    st = qwen_tts_model.model.speech_tokenizer
    if getattr(st, "_grouped", False):
        return
    orig = st.decode

    def decode(encoded, *args, **kw):
        if not isinstance(encoded, list) or not encoded or "audio_codes" not in encoded[0]:
            return orig(encoded, *args, **kw)
        codes = [torch.as_tensor(e["audio_codes"]) for e in encoded]
        order = sorted(range(len(codes)), key=lambda i: -codes[i].shape[0])
        wavs, sr, i = [None] * len(codes), None, 0
        while i < len(order):
            P = max(bucket, -(-codes[order[i]].shape[0] // bucket) * bucket)
            G = max(1, min(max_frames // P, len(codes)))
            idx = order[i:i + G]; i += G
            ref = codes[idx[0]]
            batch = []
            for k in range(G):
                c = codes[idx[k]] if k < len(idx) else ref[:0]
                pad = torch.full((P - c.shape[0], ref.shape[1]), -1, dtype=ref.dtype, device=ref.device)
                batch.append({"audio_codes": torch.cat([c, pad])})
            w, sr = orig(batch, *args, **kw)
            for k, j in enumerate(idx):
                wavs[j] = w[k]
        return wavs, sr

    st.decode = decode
    st._grouped = True


def install(qwen_tts_model, use_graph=True):
    """Patch a qwen_tts.Qwen3TTSModel (any of Base / VoiceDesign / CustomVoice) in place. Returns the predictor."""
    talker = qwen_tts_model.model.talker
    fast = FastCodePredictor(talker, use_graph=use_graph)
    talker.code_predictor.generate = fast
    limit_codec_batch(qwen_tts_model)
    return fast
