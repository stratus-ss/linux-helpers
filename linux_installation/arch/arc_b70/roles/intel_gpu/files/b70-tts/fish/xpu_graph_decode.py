# Derived from fishaudio/fish-speech. Licensed under the Fish Audio Research License (patches/LICENSE-FISH-AUDIO.md).
# Built with Fish Audio.
"""XPU-graph decoding for Fish S2 Pro (DualAR): replaces fish_speech's `generate` with a version whose per-frame step
(slow transformer + 10 fast-codebook passes + sampling + RAS window + bookkeeping, ~1000 kernels) is captured once per
KV-length bucket as a torch.xpu.XPUGraph and replayed, so the CPU launches 1 graph per frame instead of ~1000 kernels.

Prefill (variable prompt length) stays eager via the stock decode_one_token_ar. Sampling semantics match the stock
decode_one_token_ar + decode_n_tokens (top-k/top-p/temperature, RAS fallback to temp 1.0/top_p 0.9 when the sampled
semantic token repeats within the last 10 frames, stop at <|im_end|>). Random draws differ from eager for the same
seed (in-graph RNG offsets), so clips differ from the eager path but are statistically equivalent.

Needs torch >= 2.10 XPU (torch.xpu.XPUGraph) and patches/fish-speech-xpu.patch (torch.where instead of
boolean-mask assignment, `_skip_pos_check`). Used by bench_single.py --graph; fish_clone.py uses xpu_batch.py.
"""
import torch
import fish_speech.models.text2semantic.inference as inf
from fish_speech.models.text2semantic.inference import (decode_one_token_ar, logits_to_probs, IM_END_TOKEN,
                                                        RAS_WIN_SIZE, RAS_HIGH_TEMP, RAS_HIGH_TOP_P)
from torch.nn.attention import SDPBackend, sdpa_kernel


def _sample(logits, temperature, top_p, top_k):
    probs = logits_to_probs(logits, temperature=temperature, top_p=top_p, top_k=top_k)
    q = -torch.log(torch.rand_like(probs))
    return torch.argmax(probs / q, dim=-1, keepdim=True).to(dtype=torch.int)  # (1,)


class GraphDecoder:
    def __init__(self, model, bucket=256, check_every=4):
        self.m, self.bucket, self.check_every = model, bucket, check_every
        self.graphs = {}  # kv_len bucket -> XPUGraph
        self.pool = torch.xpu.graph_pool_handle()
        self.static = None
        self.capture_s = 0.0

    def _alloc(self, dtype, device):
        m, c = self.m, self.m.config
        cd = c.num_codebooks + 1
        self.cap = c.max_seq_len
        S = dict(
            x=torch.zeros((1, cd, 1), dtype=torch.int, device=device),
            pos=torch.zeros((1,), dtype=torch.int, device=device),
            prev=torch.zeros((cd, RAS_WIN_SIZE), dtype=torch.int, device=device),
            out=torch.zeros((cd, self.cap), dtype=torch.int, device=device),
            step=torch.zeros((1,), dtype=torch.long, device=device),
            temp=torch.zeros((), dtype=dtype, device=device),
            top_p=torch.zeros((), dtype=dtype, device=device),
            high_temp=torch.tensor(RAS_HIGH_TEMP, dtype=dtype, device=device),
            high_top_p=torch.tensor(RAS_HIGH_TOP_P, dtype=dtype, device=device),
            bias=torch.full((1, 1, c.vocab_size), float("-inf"), dtype=dtype, device=device),
            fast_pos=torch.arange(c.num_codebooks, dtype=torch.long, device=device),
        )
        S["bias"][0, 0, c.semantic_begin_id: c.semantic_end_id + 1] = 0.0
        S["bias"][0, 0, m.tokenizer.get_token_id(IM_END_TOKEN)] = 0.0
        self.static, self.top_k = S, None

    def _step(self, kv_len):
        m, c, S = self.m, self.m.config, self.static
        fr = m.forward_generate(S["x"], S["pos"], audio_masks=None, audio_parts=None, kv_len=kv_len)
        logits = (fr.logits + S["bias"])[0, -1]
        main = _sample(logits, S["temp"], S["top_p"], self.top_k)
        high = _sample(logits, S["high_temp"], S["high_top_p"], self.top_k)
        in_window = (S["prev"][0] == main).any()
        is_sem = (main >= c.semantic_begin_id) & (main <= c.semantic_end_id)
        main = torch.where(in_window & is_sem, high, main)
        cbs = [main]
        m.forward_generate_fast(fr.hidden_states, S["fast_pos"][0:1])
        a = torch.clamp(main - c.semantic_begin_id, min=0, max=c.codebook_size - 1)
        h = m.fast_embeddings(a); cbs.append(a)
        for i in range(1, c.num_codebooks):
            lg = m.forward_generate_fast(h, S["fast_pos"][i:i + 1])
            a = _sample(lg[0, -1], S["temp"], S["top_p"], self.top_k)
            h = m.fast_embeddings(a); cbs.append(a)
        nxt = torch.stack(cbs, dim=1).T  # (cd, 1)
        S["x"].copy_(nxt.view(1, -1, 1))
        S["pos"].add_(1)
        S["prev"].copy_(torch.roll(S["prev"], -1, dims=1))
        S["prev"][:, -1:] = nxt
        S["out"].index_copy_(1, S["step"], nxt)
        S["step"].add_(1)

    def _graph(self, kv_len):
        g = self.graphs.get(kv_len)
        if g is None:
            import time
            t = time.time()
            S = self.static
            snap = {k: S[k].clone() for k in ("x", "pos", "prev", "out", "step")}
            rng = torch.xpu.get_rng_state()
            s = torch.xpu.Stream(); s.wait_stream(torch.xpu.current_stream())
            with torch.xpu.stream(s), sdpa_kernel(SDPBackend.MATH):
                self._step(kv_len)  # warmup run outside capture (allocator / kernel JIT)
            torch.xpu.current_stream().wait_stream(s)
            g = torch.xpu.XPUGraph()
            with sdpa_kernel(SDPBackend.MATH), torch.xpu.graph(g, pool=self.pool):
                self._step(kv_len)
            torch.xpu.synchronize()
            for k, v in snap.items():  # undo the warmup's side effects (KV slot write is overwritten anyway)
                S[k].copy_(v)
            torch.xpu.set_rng_state(rng)
            self.graphs[kv_len] = g
            self.capture_s += time.time() - t
        return g

    def decode(self, first_token, T, n, temperature, top_p, top_k, im_end_id):
        """Generate up to n frames after `first_token` (at position T). Returns (cd, k) incl. the im_end frame."""
        dtype = temperature.dtype
        if self.static is None:
            self._alloc(dtype, first_token.device)
        if self.top_k is None:
            self.top_k = top_k
        assert top_k == self.top_k, "top_k is baked into the captured graphs"
        S = self.static
        S["temp"].copy_(temperature); S["top_p"].copy_(top_p)
        S["x"].copy_(first_token.view(1, -1, 1)); S["pos"].fill_(T); S["prev"].zero_(); S["step"].zero_()
        self.m._skip_pos_check = True
        try:
            for i in range(n):
                kv = min(self.cap, -(-(T + i + 1) // self.bucket) * self.bucket)
                self._graph(kv).replay()
                if (i + 1) % self.check_every == 0 or i == n - 1:
                    toks = S["out"][0, i + 1 - min(self.check_every, i + 1): i + 1]
                    hit = (toks == im_end_id).nonzero()
                    if hit.numel():
                        k = i + 1 - toks.numel() + int(hit[0, 0]) + 1
                        return S["out"][:, :k].clone()
        finally:
            self.m._skip_pos_check = False
        return S["out"][:, :n].clone()


def install(model, bucket=256, check_every=4):
    """Monkeypatch fish_speech's `generate` (used by generate_long) to use XPU graphs for the decode loop."""
    dec = GraphDecoder(model, bucket, check_every)

    @torch.no_grad()
    @torch.inference_mode()
    def generate(*, model, prompt, max_new_tokens, audio_masks, audio_parts, decode_one_token=None,
                 num_samples=1, **kw):
        assert num_samples == 1
        T = prompt.size(1); cap = model.config.max_seq_len
        if T >= cap:
            raise ValueError(f"Input sequence length {T} exceeds max_seq_len {cap}")
        max_new = cap - T if not max_new_tokens else min(max_new_tokens, cap - T)
        device = prompt.device; dtype = next(model.parameters()).dtype
        if not getattr(model, "_cache_setup_done", False):
            with torch.device(device):
                model.setup_caches(max_batch_size=1, max_seq_len=cap, dtype=dtype)
            model._cache_setup_done = True
        cd = 1 + model.config.num_codebooks
        temperature = torch.tensor(kw.get("temperature", 1.0), device=device, dtype=dtype)
        top_p = torch.tensor(kw.get("top_p", 0.9), device=device, dtype=dtype)
        top_k = kw.get("top_k", 30)
        if dec.static is None:
            dec._alloc(dtype, device)
        first = decode_one_token_ar(model, prompt.view(1, cd, -1), torch.arange(0, T, device=device, dtype=torch.long),
                                    temperature, top_p, top_k, dec.static["bias"], audio_masks, audio_parts,
                                    kv_len=T).clone()
        im_end = model.tokenizer.get_token_id(IM_END_TOKEN)
        x = dec.decode(first, T, max_new - 1, temperature, top_p, top_k, im_end)
        return torch.cat([prompt, first, x], dim=1)

    inf.generate = generate
    return dec
