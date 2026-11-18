"""Qwen3-TTS 1.7B on an Intel Arc B70 (XPU): design voices from text descriptions, or clone a voice from a wav.

  design  VoiceDesign model. Each row of a voices TSV is `name<TAB>description[<TAB>text]`. Writes <out>/<name>.wav
          plus <out>/<name>.txt holding the spoken text, so the wav can be used directly as a clone reference
          (here with `clone`, or with fish/fish_clone.py).
  clone   Base model. Each row of a lines TSV is `out_name<TAB>voice<TAB>text[<TAB>ref_text]`; voice is a wav path
          or a name looked up in --voices-dir; ref_text defaults to the voice's .txt sidecar.

Lines are generated --batch at a time (sorted by text length so a batch finishes together). The XPU-graph code
predictor (xpu_fast.py) is on unless --no-graph. Existing outputs are skipped, so runs are resumable.

usage:
  CUDA_VISIBLE_DEVICES="" python qwen/qwen_b70.py design examples/voices.tsv --out out/voices
  CUDA_VISIBLE_DEVICES="" python qwen/qwen_b70.py clone examples/lines.tsv --voices-dir out/voices --out out/qwen-lines
"""
import argparse, os, resource, sys, time
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # never touch a CUDA card from here
import torch, soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xpu_fast

# (HF repo, pinned revision) per mode; the revisions are the ones benchmarked here
MODELS = {"design": ("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "5ecdb67327fd37bb2e042aab12ff7391903235d3"),
          "clone": ("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "fd4b254389122332181a7c3db7f27e918eec64e3")}
DEFAULT_TEXT = ("Good morning. This is a short recording of my voice, so you can hear how I sound "
                "before we begin. Thanks for listening.")


def load(kind, device="xpu", dtype=torch.bfloat16, graph=True, model=None):
    from qwen_tts import Qwen3TTSModel
    if model is None:  # HF cache snapshot of the pinned revision (downloaded on first use)
        from huggingface_hub import snapshot_download
        model = snapshot_download(MODELS[kind][0], revision=MODELS[kind][1])
    m = Qwen3TTSModel.from_pretrained(model, device_map=device, dtype=dtype)
    xpu_fast.limit_codec_batch(m)  # avoids intermittent UR_RESULT_ERROR_OUT_OF_RESOURCES in batched codec decode
    fast = xpu_fast.install(m) if graph else None
    return m, fast


def read_tsv(path):
    rows = []
    for ln in open(path, encoding="utf-8"):
        if not ln.strip() or ln.startswith("#"):
            continue
        rows.append(ln.rstrip("\n").split("\t"))
    return rows


def resolve_voice(v, voices_dir):
    """Voice name or wav path -> (wav path, ref text from the .txt sidecar or None)."""
    p = v if v.endswith(".wav") else os.path.join(voices_dir or ".", v + ".wav")
    p = os.path.expanduser(p)
    if not os.path.exists(p):
        raise FileNotFoundError(f"voice not found: {v} ({p})")
    txt = p[:-4] + ".txt"
    return p, (open(txt, encoding="utf-8").read().strip() if os.path.exists(txt) else None)


def peak_rss_gib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20


def run_batches(m, jobs, batch, seed, kind, log=print):
    """jobs: list of dicts with out, text and (design) instruct or (clone) prompt item. Returns stats dict."""
    jobs = sorted(jobs, key=lambda j: len(j["text"].encode()), reverse=True)
    torch.manual_seed(seed)
    torch.xpu.synchronize(); torch.xpu.reset_peak_memory_stats()
    t0 = time.time(); audio_s = 0.0
    for i in range(0, len(jobs), batch):
        chunk = jobs[i:i + batch]; t = time.time()
        texts = [j["text"] for j in chunk]
        if kind == "design":
            wavs, sr = m.generate_voice_design(text=texts, language="English", instruct=[j["instruct"] for j in chunk])
        else:
            wavs, sr = m.generate_voice_clone(text=texts, language="English", voice_clone_prompt=[j["prompt"] for j in chunk])
        torch.xpu.synchronize(); dt = time.time() - t
        for j, w in zip(chunk, wavs):
            if j.get("out"):
                os.makedirs(os.path.dirname(os.path.abspath(j["out"])), exist_ok=True)
                sf.write(j["out"], w, sr)
                if kind == "design":
                    with open(j["out"][:-4] + ".txt", "w", encoding="utf-8") as f:
                        f.write(j["text"] + "\n")
            audio_s += len(w) / sr
        log(f"batch {i // batch + 1}/{-(-len(jobs) // batch)}: {len(chunk)} lines, "
            f"{sum(len(w) for w in wavs) / sr:.1f} s audio in {dt:.1f} s")
    wall = time.time() - t0
    return dict(lines=len(jobs), audio_s=audio_s, wall_s=wall, s_per_audio_s=wall / max(audio_s, 1e-9),
                peak_vram_gib=torch.xpu.max_memory_allocated() / 2**30, peak_rss_gib=peak_rss_gib())


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("mode", choices=["design", "clone"])
    a.add_argument("tsv")
    a.add_argument("--out", required=True, help="output directory")
    a.add_argument("--voices-dir", help="clone: where voice names are looked up")
    a.add_argument("--text", default=DEFAULT_TEXT, help="design: text read by every voice without its own text")
    a.add_argument("--batch", type=int, default=8)
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--no-graph", action="store_true", help="stock HF code predictor (slower)")
    a.add_argument("--model", help="local model directory (default: pinned HF snapshot)")
    a = a.parse_args()
    assert torch.xpu.is_available(), "no XPU device"
    print(f"{torch.xpu.get_device_name(0)}  torch {torch.__version__}", flush=True)

    jobs = []
    for r in read_tsv(a.tsv):
        out = os.path.join(a.out, r[0] if r[0].endswith(".wav") else r[0] + ".wav")
        if os.path.exists(out):
            continue
        if a.mode == "design":
            jobs.append(dict(out=out, instruct=r[1], text=r[2] if len(r) > 2 and r[2] else a.text))
        else:
            wav, ref_text = resolve_voice(r[1], a.voices_dir)
            ref_text = r[3] if len(r) > 3 and r[3] else ref_text
            if not ref_text:
                raise ValueError(f"{r[0]}: no ref text (4th column or {wav[:-4]}.txt)")
            jobs.append(dict(out=out, text=r[2], ref=wav, ref_text=ref_text))
    print(f"{len(jobs)} lines to do", flush=True)
    if not jobs:
        return
    t = time.time()
    m, fast = load(a.mode, graph=not a.no_graph, model=a.model)
    torch.xpu.synchronize()
    print(f"load {time.time() - t:.1f} s, VRAM {torch.xpu.memory_allocated() / 2**30:.2f} GiB", flush=True)
    if a.mode == "clone":  # one clone prompt per distinct reference
        prompts = {}
        for j in jobs:
            key = (j["ref"], j["ref_text"])
            if key not in prompts:
                prompts[key] = m.create_voice_clone_prompt(ref_audio=j["ref"], ref_text=j["ref_text"])[0]
            j["prompt"] = prompts[key]
    s = run_batches(m, jobs, a.batch, a.seed, a.mode, log=lambda x: print(x, flush=True))
    print(f"TOTAL {s['lines']} lines, {s['audio_s']:.1f} s audio in {s['wall_s']:.1f} s -> "
          f"{s['s_per_audio_s']:.3f} s per audio second; peak VRAM {s['peak_vram_gib']:.2f} GiB, "
          f"peak RSS {s['peak_rss_gib']:.1f} GiB", flush=True)


if __name__ == "__main__":
    main()
