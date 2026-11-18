# Derived from fishaudio/fish-speech. Licensed under the Fish Audio Research License (patches/LICENSE-FISH-AUDIO.md).
# Built with Fish Audio.
"""Batched Fish Audio S2 Pro voice cloning on an Intel Arc B70 (XPU), from a TSV of lines.

Each row of the lines TSV is `out_name<TAB>voice<TAB>text[<TAB>ref_text]`:
  voice     a reference wav path, or a name looked up as <--voices-dir>/<name>.wav
  ref_text  what the reference says; defaults to the <voice>.txt sidecar (qwen/qwen_b70.py design writes one)
Text may contain Fish inline tags such as [whispering], [laughing], [crying], [sigh].

References are encoded once. Lines are generated --batch at a time (sorted by text length, so rows in a batch
finish together), with the per-frame step captured as an XPU graph per 256-token KV bucket (fish/xpu_batch.py).
The resident codec then decodes them in groups of --codec-batch, padded to a multiple of --codec-bucket frames (the
codec is causal, so the padding does not change the kept audio and it avoids a ~2 s kernel JIT per new length).
Existing outputs are skipped, so runs are resumable. One line per row: the batched path does not split long
texts the way fish_speech's generate_long does, so keep each row under about a minute of speech.

usage:
  CUDA_VISIBLE_DEVICES="" python fish/fish_clone.py examples/lines.tsv --voices-dir out/voices --out out/fish-lines \
      [--batch 32] [--bench-tsv bench/fish_batch.tsv --tag mytag]
Needs a fish-speech checkout with patches/fish-speech-xpu.patch applied: $FISH_SPEECH_DIR (default ./fish-speech)
and the S2 Pro weights in $FISH_CKPT (default $FISH_SPEECH_DIR/checkpoints/s2-pro).
"""
import argparse, os, resource, sys, time
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # never touch a CUDA card from here
import torch, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
FISH = os.path.abspath(os.environ.get("FISH_SPEECH_DIR", os.path.join(ROOT, "fish-speech")))
CKPT = os.path.abspath(os.environ.get("FISH_CKPT", os.path.join(FISH, "checkpoints", "s2-pro")))
sys.path.insert(0, FISH); sys.path.insert(0, HERE)
DEV = "xpu"


@torch.inference_mode()
def encode_audio(path, codec, device):
    """fish_speech's encode_audio, but reading with soundfile (torchaudio >= 2.9 load needs torchcodec)."""
    import torchaudio
    wav, sr = sf.read(path, dtype="float32", always_2d=True)
    wav = torch.from_numpy(wav.T).mean(dim=0, keepdim=True)
    wav = torchaudio.functional.resample(wav.to(device), sr, codec.sample_rate)[0]
    audios = wav[None, None].to(dtype=next(codec.parameters()).dtype)
    indices, feature_lengths = codec.encode(audios, torch.tensor([len(wav)], device=device, dtype=torch.long))
    return indices[0, :, : feature_lengths[0]]


def resolve_voice(v, voices_dir):
    """Voice name or wav path -> (wav path, ref text from the .txt sidecar or None)."""
    p = v if v.endswith(".wav") else os.path.join(voices_dir or ".", v + ".wav")
    p = os.path.expanduser(p)
    if not os.path.exists(p):
        raise FileNotFoundError(f"voice not found: {v} ({p})")
    txt = p[:-4] + ".txt"
    return p, (open(txt, encoding="utf-8").read().strip() if os.path.exists(txt) else None)


def read_jobs(path, voices_dir, out_dir):
    jobs = []
    for ln in open(path, encoding="utf-8"):
        if not ln.strip() or ln.startswith("#"):
            continue
        f = ln.rstrip("\n").split("\t")
        if len(f) < 3:
            raise ValueError(f"need out_name<TAB>voice<TAB>text: {ln!r}")
        out = os.path.join(out_dir, f[0] if f[0].endswith(".wav") else f[0] + ".wav")
        if os.path.exists(out):
            continue
        ref, ref_text = resolve_voice(f[1], voices_dir)
        ref_text = f[3] if len(f) > 3 and f[3] else ref_text
        if not ref_text:
            raise ValueError(f"{f[0]}: no ref text (4th column or {ref[:-4]}.txt)")
        jobs.append((ref, ref_text, f[2], out))
    return jobs


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("tsv")
    a.add_argument("--out", required=True, help="output directory")
    a.add_argument("--voices-dir")
    a.add_argument("--batch", type=int, default=16)
    a.add_argument("--max-length", type=int, default=2048, help="KV cache length (prompt + output frames)")
    a.add_argument("--kv-bucket", type=int, default=256)
    a.add_argument("--codec-bucket", type=int, default=64)
    a.add_argument("--codec-batch", type=int, default=8)
    a.add_argument("--no-graph", action="store_true")
    a.add_argument("--temperature", type=float, default=1.0)
    a.add_argument("--top-p", type=float, default=0.9)
    a.add_argument("--top-k", type=int, default=30)
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--bench-tsv", help="append a timing row to this TSV")
    a.add_argument("--tag", default="run")
    a = a.parse_args()
    assert torch.xpu.is_available(), "no XPU device"
    from fish_speech.models.text2semantic.llama import DualARTransformer
    from fish_speech.models.text2semantic.inference import load_codec_model
    import xpu_batch

    jobs = read_jobs(a.tsv, a.voices_dir, a.out)
    jobs.sort(key=lambda j: len(j[2].encode()), reverse=True)  # similar lengths per batch -> fewer idle rows
    print(f"{torch.xpu.get_device_name(0)}  torch {torch.__version__}; {len(jobs)} lines to do", flush=True)
    if not jobs:
        return
    t = time.time()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from b70_load import to_dev_chunked, xe_watchdog
    xe_watchdog()
    model = DualARTransformer.from_pretrained(CKPT, load_weights=True, max_length=a.max_length).to(torch.bfloat16)
    model = to_dev_chunked(model, DEV).eval()
    codec = to_dev_chunked(load_codec_model(os.path.join(CKPT, "codec.pth"), "cpu", torch.bfloat16), DEV); sr = codec.sample_rate
    bf = xpu_batch.BatchFish(model, a.batch, bucket=a.kv_bucket, use_graph=not a.no_graph,
                             temperature=a.temperature, top_p=a.top_p, top_k=a.top_k)
    torch.xpu.synchronize(); t_load = time.time() - t
    print(f"load {t_load:.1f} s; VRAM {torch.xpu.memory_allocated() / 2**30:.2f} GiB", flush=True)

    torch.manual_seed(a.seed)
    with torch.inference_mode():
        # warmup: one full batch (graph capture, kernel JIT), discarded
        ref0, rt0, text0, _ = jobs[0]
        t = time.time()
        bf.generate([xpu_batch.build_prompt(model, text0, rt0, encode_audio(ref0, codec, DEV))] * a.batch)
        torch.xpu.synchronize(); t_warm = time.time() - t
        print(f"warmup batch {t_warm:.1f} s (graphs {len(bf.graphs)}, capture {bf.capture_s:.1f} s)", flush=True)
        for b in range(1, 5):  # pre-JIT codec decode buckets up to 256 frames (~12 s of audio)
            for n in sorted({1, a.codec_batch, len(jobs) % a.codec_batch or a.codec_batch}):
                codec.from_indices(torch.zeros((n, 10, b * a.codec_bucket), dtype=torch.long, device=DEV))
        torch.xpu.synchronize()
        t0 = time.time(); refs = {}; t_enc = t_gen = t_dec = 0.0; audio_s = 0.0; frames = 0
        torch.xpu.reset_peak_memory_stats()
        for i in range(0, len(jobs), a.batch):
            chunk = jobs[i:i + a.batch]
            t = time.time()
            for r, _, _, _ in chunk:
                if r not in refs:
                    refs[r] = encode_audio(r, codec, DEV)
            prompts = [xpu_batch.build_prompt(model, text, rt, refs[r]) for r, rt, text, _ in chunk]
            torch.xpu.synchronize(); t_enc += time.time() - t
            t = time.time(); codes = bf.generate(prompts); torch.xpu.synchronize(); dt = time.time() - t; t_gen += dt
            t = time.time()
            items = list(zip(chunk, codes))
            for j in range(0, len(items), a.codec_batch):  # batched codec decode, padded to a shared length bucket
                sub = items[j:j + a.codec_batch]
                P = -(-max(c.shape[1] for _, c in sub) // a.codec_bucket) * a.codec_bucket
                cb = torch.stack([torch.cat([c, c[:, -1:].expand(-1, P - c.shape[1])], 1) for _, c in sub])
                wav = codec.from_indices(cb.to(DEV).long())[:, 0].float().cpu().numpy()
                for ((_, _, _, out), c), w in zip(sub, wav):
                    L = c.shape[1]; audio = w[: L * 2048]  # 2048 samples per codec frame
                    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
                    sf.write(out, audio, sr); audio_s += len(audio) / sr; frames += L
            torch.xpu.synchronize(); t_dec += time.time() - t
            print(f"batch {i // a.batch + 1}/{-(-len(jobs) // a.batch)}: {len(chunk)} lines, "
                  f"frames {[c.shape[1] for c in codes]}, gen {dt:.2f} s", flush=True)
        wall = time.time() - t0
    peak = torch.xpu.max_memory_allocated() / 2**30
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20
    print(f"TOTAL {len(jobs)} lines, {audio_s:.1f} s audio, {frames} frames in {wall:.1f} s wall "
          f"(enc {t_enc:.1f}, gen {t_gen:.1f}, dec {t_dec:.1f}) -> {wall / audio_s:.3f} s/s total, "
          f"{t_gen / audio_s:.3f} s/s gen, {frames / t_gen:.1f} frames/s; peak VRAM {peak:.2f} GiB, "
          f"peak RSS {rss:.1f} GiB; graphs {len(bf.graphs)} capture {bf.capture_s:.1f} s", flush=True)
    if a.bench_tsv:
        new = not os.path.exists(a.bench_tsv)
        with open(a.bench_tsv, "a") as f:
            if new:
                f.write("tag\tbatch\tgraph\tmax_len\tlines\taudio_s\twall_s\tenc_s\tgen_s\tdec_s\ttotal_s_per_audio_s"
                        "\tgen_s_per_audio_s\tframes_per_s\tpeak_vram_gib\tpeak_rss_gib\tload_s\twarmup_s\n")
            f.write("\t".join(map(str, [a.tag, a.batch, int(not a.no_graph), a.max_length, len(jobs), f"{audio_s:.1f}",
                                        f"{wall:.1f}", f"{t_enc:.1f}", f"{t_gen:.1f}", f"{t_dec:.1f}",
                                        f"{wall / audio_s:.3f}", f"{t_gen / audio_s:.3f}", f"{frames / t_gen:.1f}",
                                        f"{peak:.2f}", f"{rss:.1f}", f"{t_load:.1f}", f"{t_warm:.1f}"])) + "\n")


if __name__ == "__main__":
    main()
