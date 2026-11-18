# Derived from fishaudio/fish-speech. Licensed under the Fish Audio Research License (patches/LICENSE-FISH-AUDIO.md).
# Built with Fish Audio.
"""Single-line Fish Audio S2 Pro benchmark on an Intel Arc B70: the stock fish_speech generate_long path, plus the
single-line speedups (KV-length bucketing, XPU-graph decode) and the ones that did not help (int8, torch.compile).

Each voice (<voices-dir>/<name>.wav with its .txt sidecar as ref text) reads --text, plus one emotion-tagged line
for the first voice. The first job is a discarded warmup. Writes <out>/<voice>.wav and appends one row per clip
to --bench-tsv (default bench/fish_single.tsv).

usage:
  CUDA_VISIBLE_DEVICES="" python fish/bench_single.py --voices-dir out/voices --voices narrator bright --tag graph \
      --kv-bucket 256 --graph [--quant int8] [--compile] [--max-length 4096]
"""
import argparse, os, resource, sys, time
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch, torch.nn as nn, torch.nn.functional as F, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, HERE)
from fish_clone import FISH, CKPT, DEV, encode_audio, resolve_voice

TEXT = "Wait, you're telling me the whole town knew about this, and nobody said a word? Unbelievable."
EMOTION_TEXT = "[sigh] I didn't ask for any of this. [whispering] Just leave me alone."


class Int8Linear(nn.Module):
    """int8 weight-only linear, per-output-row scales (what made S2 Pro fit a 12 GB card; slower on the B70)."""
    def __init__(self, lin):
        super().__init__()
        w = lin.weight.data.float()
        scale = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127
        self.register_buffer("q", torch.round(w / scale).to(torch.int8))
        self.register_buffer("scale", scale.to(torch.bfloat16))
        self.bias = lin.bias

    def forward(self, x):
        return F.linear(x, self.q.to(x.dtype) * self.scale.to(x.dtype), self.bias)


def quantize(mod, min_numel=1 << 20):
    n = 0
    for name, child in mod.named_children():
        if isinstance(child, nn.Linear) and child.weight.numel() >= min_numel:
            setattr(mod, name, Int8Linear(child)); n += 1
        else:
            n += quantize(child, min_numel)
    return n


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--tag", required=True)
    a.add_argument("--voices-dir", required=True)
    a.add_argument("--voices", nargs="+", required=True)
    a.add_argument("--text", default=TEXT)
    a.add_argument("--no-emotion", action="store_true")
    a.add_argument("--out", default=None, help="default out/fish-single/<tag>")
    a.add_argument("--quant", choices=["bf16", "int8"], default="bf16")
    a.add_argument("--max-length", type=int, default=4096)
    a.add_argument("--kv-bucket", type=int, default=0,
                   help="round the decode KV length up to a multiple of N (fixed shapes, no per-length kernel JIT)")
    a.add_argument("--graph", action="store_true", help="XPU-graph decode loop (xpu_graph_decode.py)")
    a.add_argument("--compile", action="store_true", help="torch.compile the decode step (needs Triton XPU)")
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--bench-tsv", default=os.path.join(ROOT, "bench", "fish_single.tsv"))
    a = a.parse_args()
    assert torch.xpu.is_available(), "no XPU device"
    from fish_speech.models.text2semantic.llama import DualARTransformer
    from fish_speech.models.text2semantic.inference import (decode_one_token_ar, generate_long, load_codec_model,
                                                            decode_to_audio)
    out_dir = a.out or os.path.join(ROOT, "out", "fish-single", a.tag); os.makedirs(out_dir, exist_ok=True)
    print(f"{torch.xpu.get_device_name(0)}  torch {torch.__version__}  {vars(a)}", flush=True)

    t = time.time()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from b70_load import to_dev_chunked, xe_watchdog
    xe_watchdog()
    model = DualARTransformer.from_pretrained(CKPT, load_weights=True, max_length=a.max_length).to(torch.bfloat16)
    if a.quant == "int8":
        print(f"quantized {quantize(model)} linears", flush=True)
    model = to_dev_chunked(model, DEV).eval(); model._cache_setup_done = False
    decode_one = decode_one_token_ar
    if a.kv_bucket:
        cap, b = a.max_length, a.kv_bucket

        def decode_one(*, kv_len=None, **kw):  # the mask still hides the unused tail, so output is unchanged
            if kv_len is not None:
                kv_len = min(cap, -(-kv_len // b) * b)
            return decode_one_token_ar(kv_len=kv_len, **kw)
    if a.compile:
        decode_one = torch.compile(decode_one, backend="inductor", mode="default", fullgraph=True, dynamic=True)
    dec = None
    if a.graph:
        import xpu_graph_decode
        dec = xpu_graph_decode.install(model, bucket=a.kv_bucket or 256)
    codec = to_dev_chunked(load_codec_model(os.path.join(CKPT, "codec.pth"), "cpu", torch.bfloat16), DEV); sr = codec.sample_rate
    torch.xpu.synchronize(); t_load = time.time() - t
    print(f"load {t_load:.1f} s; VRAM {torch.xpu.memory_allocated() / 2**30:.2f} GiB", flush=True)

    jobs = [(v, a.text, v) for v in a.voices]
    if not a.no_emotion:
        jobs.append((a.voices[0], EMOTION_TEXT, f"{a.voices[0]}-emotion"))
    jobs = [(jobs[0][0], jobs[0][1], "_warmup")] + jobs

    new = not os.path.exists(a.bench_tsv)
    with open(a.bench_tsv, "a") as tsv:
        if new:
            tsv.write("tag\tquant\tmax_len\tcompile\tclip\tload_s\tencode_s\tgen_s\tdecode_s\tframes\taudio_s"
                      "\tgen_s_per_audio_s\ttotal_s_per_audio_s\tpeak_vram_gib\tpeak_rss_gib\tkv_bucket\tgraph\n")
        for voice, text, name in jobs:
            ref, ref_text = resolve_voice(voice, a.voices_dir)
            torch.xpu.synchronize(); t = time.time(); prompt = encode_audio(ref, codec, DEV)
            torch.xpu.synchronize(); t_enc = time.time() - t
            torch.manual_seed(a.seed); torch.xpu.manual_seed(a.seed); parts = []
            t = time.time()
            for r in generate_long(model=model, device=DEV, decode_one_token=decode_one, text=text,
                                   prompt_text=[ref_text], prompt_tokens=[prompt], chunk_length=300):
                if r.action == "sample":
                    parts.append(r.codes)
                elif r.action == "next":
                    break
            torch.xpu.synchronize(); t_gen = time.time() - t
            codes = torch.cat(parts, dim=1)
            t = time.time(); audio = decode_to_audio(codes, codec).float().cpu().numpy(); torch.xpu.synchronize()
            t_dec = time.time() - t; dur = len(audio) / sr
            peak = torch.xpu.max_memory_allocated() / 2**30
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20
            print(f"{name}: {codes.shape[1]} frames, enc {t_enc:.2f} s, gen {t_gen:.2f} s, dec {t_dec:.2f} s, "
                  f"audio {dur:.2f} s -> {t_gen / dur:.2f} s/s gen, {(t_enc + t_gen + t_dec) / dur:.2f} s/s total; "
                  f"peak VRAM {peak:.2f} GiB", flush=True)
            if name == "_warmup":
                continue
            sf.write(os.path.join(out_dir, f"{name}.wav"), audio, sr)
            tsv.write("\t".join(map(str, [a.tag, a.quant, a.max_length, int(a.compile), name, f"{t_load:.1f}",
                                          f"{t_enc:.2f}", f"{t_gen:.2f}", f"{t_dec:.2f}", codes.shape[1], f"{dur:.2f}",
                                          f"{t_gen / dur:.3f}", f"{(t_enc + t_gen + t_dec) / dur:.3f}", f"{peak:.2f}",
                                          f"{rss:.1f}", a.kv_bucket, int(a.graph)])) + "\n")
            tsv.flush()


if __name__ == "__main__":
    with torch.inference_mode():
        main()
