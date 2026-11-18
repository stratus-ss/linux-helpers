# Derived from fishaudio/fish-speech. Licensed under the Fish Audio Research License (patches/LICENSE-FISH-AUDIO.md).
# Built with Fish Audio.
"""Batched + XPU-graph generation for Fish Audio S2 Pro (DualAR) on an Intel Arc B70.

At batch 1 the decode is weight-bandwidth bound (~15 GB of bf16 weights read per frame: 36 slow layers + 4 fast
layers x 10 codebook passes), and an M=8 GEMV costs about the same as M=1 on the B70, so generating B lines together
gives close to B-fold throughput. Prompts of different lengths are left-padded to a common length. Because RoPE
attention depends only on relative position, a shared position counter plus a per-row key mask (pad keys hidden) gives
the same attention as unpadded decoding. The per-frame step for the whole batch is captured once per KV-length
bucket as a torch.xpu.XPUGraph.

Also restricts the slow head to the 4096 semantic tokens + <|im_end|> (the only tokens the stock sampler can emit,
since every other logit gets a -inf bias), which skips 0.8 GB of embedding reads per frame and the 155k-wide sorts.

Sampling matches stock decode_one_token_ar: temperature/top_p/top_k, RAS fallback (temp 1.0, top_p 0.9) when the
semantic token repeats within the last 10 frames, stop at <|im_end|> (per row; finished rows idle until all stop).
Needs patches/fish-speech-xpu.patch applied to the fish-speech checkout (row key mask, sub-vocab head,
_skip_pos_check, GQA fold).
"""
import time
import torch
from torch.nn.attention import SDPBackend, sdpa_kernel
from fish_speech.content_sequence import TextPart, VQPart
from fish_speech.conversation import Conversation, Message
from fish_speech.tokenizer import IM_END_TOKEN
from fish_speech.models.text2semantic.inference import logits_to_probs, RAS_WIN_SIZE, RAS_HIGH_TEMP, RAS_HIGH_TOP_P


def build_prompt(model, text, ref_text, ref_codes):
    """Same conversation as fish_speech generate_long (one reference, plain text without speaker tags)."""
    tok = model.tokenizer
    conv = Conversation()
    conv.append(Message(role="system", parts=[
        TextPart(text="convert the provided text to speech reference to the following:\n\nText:\n", cal_loss=False),
        TextPart(text=f"<|speaker:0|>{ref_text}", cal_loss=False),
        TextPart(text="\n\nSpeech:\n", cal_loss=False),
        VQPart(codes=ref_codes.cpu(), cal_loss=False)], cal_loss=False, add_im_start=True, add_im_end=True))
    conv.append(Message(role="user", parts=[TextPart(text=text, cal_loss=False)], cal_loss=False,
                        add_im_start=True, add_im_end=True))
    conv.append(Message(role="assistant", parts=[], cal_loss=False, modality="voice", add_im_start=True,
                        add_im_end=False))
    encoded, audio_masks, audio_parts = conv.encode_for_inference(tok, num_codebooks=model.config.num_codebooks)
    assert audio_parts is None, "reference audio features (audio_parts) not supported in batched path"
    return encoded  # (1 + num_codebooks, T)


def _sample(logits, temperature, top_p, top_k):  # logits (B, V) -> (B, 1) index
    probs = logits_to_probs(logits, temperature=temperature, top_p=top_p, top_k=top_k)
    q = -torch.log(torch.rand_like(probs))
    return torch.argmax(probs / q, dim=-1, keepdim=True)


class BatchFish:
    def __init__(self, model, batch, bucket=256, check_every=4, temperature=1.0, top_p=0.9, top_k=30,
                 use_graph=True):
        m, c = model, model.config
        self.m, self.B, self.bucket, self.check_every, self.top_k, self.use_graph = (model, batch, bucket,
                                                                                    check_every, top_k, use_graph)
        dev = next(m.parameters()).device; dt = next(m.parameters()).dtype
        self.cd = c.num_codebooks + 1
        self.cap = c.max_seq_len
        with torch.device(dev):
            m.setup_caches(max_batch_size=batch, max_seq_len=self.cap, dtype=dt)
        m._cache_setup_done = True
        self.im_end = m.tokenizer.get_token_id(IM_END_TOKEN)
        self.vocab_idx = torch.cat([torch.arange(c.semantic_begin_id, c.semantic_end_id + 1),
                                    torch.tensor([self.im_end])]).to(dev, torch.int)
        m._out_weight = m.embeddings.weight[self.vocab_idx.long()].contiguous()
        B = batch
        self.S = dict(
            x=torch.zeros((B, self.cd, 1), dtype=torch.int, device=dev),
            pos=torch.zeros((1,), dtype=torch.int, device=dev),
            prev=torch.zeros((B, RAS_WIN_SIZE), dtype=torch.int, device=dev),
            out=torch.zeros((B, self.cd, self.cap), dtype=torch.int, device=dev),
            step=torch.zeros((1,), dtype=torch.long, device=dev),
            rowkey=torch.ones((B, self.cap), dtype=torch.bool, device=dev),
            temp=torch.tensor(temperature, dtype=dt, device=dev), top_p=torch.tensor(top_p, dtype=dt, device=dev),
            high_temp=torch.tensor(RAS_HIGH_TEMP, dtype=dt, device=dev),
            high_top_p=torch.tensor(RAS_HIGH_TOP_P, dtype=dt, device=dev),
            fast_pos=torch.arange(c.num_codebooks, dtype=torch.long, device=dev),
        )
        m._row_key_mask = self.S["rowkey"]
        self.graphs, self.pool, self.capture_s = {}, torch.xpu.graph_pool_handle(), 0.0
        self.dev = dev

    def _frame(self, fr, ras):
        """Sample one frame (B, cd) from a slow-transformer result; runs the fast transformer."""
        m, c, S = self.m, self.m.config, self.S
        logits = fr.logits[:, -1]  # (B, 4097) sub-vocab
        main = self.vocab_idx[_sample(logits, S["temp"], S["top_p"], self.top_k)]  # token ids (B, 1)
        if ras:
            high = self.vocab_idx[_sample(logits, S["high_temp"], S["high_top_p"], self.top_k)]
            in_window = (S["prev"] == main).any(dim=-1, keepdim=True)
            is_sem = (main >= c.semantic_begin_id) & (main <= c.semantic_end_id)
            main = torch.where(in_window & is_sem, high, main)
        m.forward_generate_fast(fr.hidden_states, S["fast_pos"][0:1])
        a = torch.clamp(main - c.semantic_begin_id, min=0, max=c.codebook_size - 1)
        h = m.fast_embeddings(a); cbs = [main, a]
        for i in range(1, c.num_codebooks):
            lg = m.forward_generate_fast(h, S["fast_pos"][i:i + 1])
            a = _sample(lg[:, -1], S["temp"], S["top_p"], self.top_k).to(torch.int)
            h = m.fast_embeddings(a); cbs.append(a)
        return torch.cat(cbs, dim=1).to(torch.int)  # (B, cd)

    def _commit(self, nxt):
        S = self.S
        S["x"].copy_(nxt[:, :, None]); S["pos"].add_(1)
        S["prev"].copy_(torch.roll(S["prev"], -1, dims=1)); S["prev"][:, -1:] = nxt[:, :1]
        S["out"].index_copy_(2, S["step"], nxt[:, :, None]); S["step"].add_(1)

    def _step(self, kv_len):
        fr = self.m.forward_generate(self.S["x"], self.S["pos"], audio_masks=None, audio_parts=None, kv_len=kv_len)
        self._commit(self._frame(fr, ras=True))

    def _run(self, kv_len):
        if not self.use_graph:
            with sdpa_kernel(SDPBackend.MATH):
                self._step(kv_len)
            return
        g = self.graphs.get(kv_len)
        if g is None:
            t = time.time(); S = self.S
            snap = {k: S[k].clone() for k in ("x", "pos", "prev", "out", "step")}
            rng = torch.xpu.get_rng_state()
            s = torch.xpu.Stream(); s.wait_stream(torch.xpu.current_stream())
            with torch.xpu.stream(s), sdpa_kernel(SDPBackend.MATH):
                self._step(kv_len)
            torch.xpu.current_stream().wait_stream(s)
            g = torch.xpu.XPUGraph()
            with sdpa_kernel(SDPBackend.MATH), torch.xpu.graph(g, pool=self.pool):
                self._step(kv_len)
            torch.xpu.synchronize()
            for k, v in snap.items():
                S[k].copy_(v)
            torch.xpu.set_rng_state(rng)
            self.graphs[kv_len] = g; self.capture_s += time.time() - t
        g.replay()

    @torch.inference_mode()
    def generate(self, prompts):
        """prompts: list (<= B) of encoded prompts (cd, T_i). Returns list of codes (num_codebooks, n_i)."""
        n_real = len(prompts); assert 0 < n_real <= self.B
        prompts = list(prompts) + [prompts[0]] * (self.B - n_real)  # fill unused rows with a duplicate
        S, m = self.S, self.m
        Tmax = max(p.shape[1] for p in prompts)
        if Tmax > self.cap - 64:
            raise ValueError(f"prompt too long: {Tmax}")
        x = torch.zeros((self.B, self.cd, Tmax), dtype=torch.int, device=self.dev)
        S["rowkey"].fill_(True)
        for b, p in enumerate(prompts):
            x[b, :, Tmax - p.shape[1]:] = p.to(self.dev)
            S["rowkey"][b, :Tmax - p.shape[1]] = False
        m._skip_pos_check = True
        try:
            fr = m.forward_generate(x, torch.arange(Tmax, device=self.dev), audio_masks=None, audio_parts=None,
                                    kv_len=Tmax)
            S["prev"].zero_(); S["step"].zero_(); S["pos"].fill_(Tmax)
            self._commit(self._frame(fr, ras=False))  # first frame (stock prefill has no RAS)
            S["pos"].fill_(Tmax)  # the first frame's token is fed at position Tmax
            n_max = self.cap - Tmax
            done = torch.zeros(self.B, dtype=torch.bool, device=self.dev)
            for i in range(1, n_max):
                kv = min(self.cap, -(-(Tmax + i) // self.bucket) * self.bucket)
                self._run(kv)
                if (i + 1) % self.check_every == 0:
                    done |= (S["out"][:, 0, : i + 1] == self.im_end).any(dim=1)
                    if bool(done[:n_real].all()):
                        break
        finally:
            m._skip_pos_check = False
        out = S["out"][:n_real].cpu()
        res = []
        for b in range(n_real):
            hit = (out[b, 0] == self.im_end).nonzero()
            n = int(hit[0, 0]) if hit.numel() else int(S["step"].item())
            res.append(out[b, 1:, :n].clone())
        return res
