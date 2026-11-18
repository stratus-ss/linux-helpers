"""Benchmark Qwen3-TTS 1.7B VoiceDesign and Base (clone) on the B70: stock vs XPU-graph code predictor, batch sizes.

Designs two test voices (TEST_VOICES) reading the reference text, then times every config on 2 voices x 8 lines.
Each config runs one discarded warmup batch first (graph capture, some kernel JIT). Single-line rows still pay
kernel JIT for every new KV length, so they are noisy (0.8-1.5 s/s for the same config). One model is loaded at a time.
Appends rows to bench/qwen.tsv; the designed voices go to <out>/voices/ (they are the clone references).

usage: CUDA_VISIBLE_DEVICES="" python qwen/bench_qwen.py [--out out/bench-qwen] [--dtype bf16|fp32]
           [--configs stock:1,graph:1,stock:8,graph:8,graph:16,graph:32] [--models design,clone]
"""
import argparse, os, sys, time
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import qwen_b70, xpu_fast

TEST_VOICES = {
    "narrator": "A calm middle-aged man with a deep, warm voice, speaking slowly and clearly like an audiobook narrator.",
    "bright": "A cheerful young woman with a bright, clear voice, speaking with energy and a smile, like a morning radio host.",
}
LINES = [
    "The train to the coast leaves at nine, so pack light and bring a warm coat.",
    "I checked the numbers twice, and they still don't add up.",
    "If you follow the river north for about an hour, you'll reach the old stone bridge.",
    "Thanks for calling. Everyone is busy right now, but your call matters to us.",
    "Wait, you're telling me the whole town knew about this, and nobody said a word?",
    "The recipe is simple: flour, water, salt, and a lot of patience.",
    "When the lights came back on, the room was empty and the window was wide open.",
    "Let's take a short break and meet back here in ten minutes.",
]


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--out", default="out/bench-qwen")
    a.add_argument("--dtype", choices=["bf16", "fp32"], default="bf16")
    a.add_argument("--configs", default="stock:1,graph:1,stock:8,graph:8,graph:16,graph:32")
    a.add_argument("--models", default="design,clone")
    a.add_argument("--tsv", default=os.path.join(os.path.dirname(HERE), "bench", "qwen.tsv"))
    a.add_argument("--seed", type=int, default=7)
    a = a.parse_args()
    dt = torch.bfloat16 if a.dtype == "bf16" else torch.float32
    configs = [(c.split(":")[0], int(c.split(":")[1])) for c in a.configs.split(",")]
    vdir = os.path.join(a.out, "voices")
    print(f"{torch.xpu.get_device_name(0)}  torch {torch.__version__}  {vars(a)}", flush=True)
    new = not os.path.exists(a.tsv)
    tsv = open(a.tsv, "a")
    if new:
        tsv.write("model\tdecoder\tdtype\tbatch\tlines\taudio_s\twall_s\ts_per_audio_s\tpeak_vram_gib\tpeak_rss_gib"
                  "\tload_s\n")

    for kind in a.models.split(","):
        t = time.time()
        m, _ = qwen_b70.load(kind, dtype=dt, graph=False)
        torch.xpu.synchronize(); load_s = time.time() - t
        print(f"{kind}: load {load_s:.1f} s, VRAM {torch.xpu.memory_allocated() / 2**30:.2f} GiB", flush=True)
        if kind == "design":
            base = [dict(text=ln, instruct=ins) for ins in TEST_VOICES.values() for ln in LINES]
        else:
            refs = {v: qwen_b70.resolve_voice(v, vdir) for v in TEST_VOICES}
            prompts = {v: m.create_voice_clone_prompt(ref_audio=w, ref_text=rt)[0] for v, (w, rt) in refs.items()}
            base = [dict(text=ln, prompt=prompts[v]) for v in TEST_VOICES for ln in LINES]
        fast = None
        for dec, B in sorted(configs, key=lambda c: c[0] == "graph"):  # stock configs first, then patch once
            if dec == "graph" and fast is None:
                fast = xpu_fast.install(m)
            jobs = base[::4] if B == 1 else (base * 2 if B > len(base) else base)  # B=1: 4 lines (slow)
            warm = [dict(j) for j in (jobs * B)[:B]]
            qwen_b70.run_batches(m, warm, B, a.seed + 1, kind, log=lambda x: None)  # warmup, discarded
            s = qwen_b70.run_batches(m, [dict(j) for j in jobs], B, a.seed, kind, log=lambda x: None)
            row = [kind, dec, a.dtype, B, s["lines"], f"{s['audio_s']:.1f}", f"{s['wall_s']:.1f}",
                   f"{s['s_per_audio_s']:.3f}", f"{s['peak_vram_gib']:.2f}", f"{s['peak_rss_gib']:.1f}", f"{load_s:.1f}"]
            tsv.write("\t".join(map(str, row)) + "\n"); tsv.flush()
            print("\t".join(map(str, row)), flush=True)
        if kind == "design" and fast is not None:  # the test voices, as clone references
            jobs = [dict(out=os.path.join(vdir, f"{v}.wav"), text=qwen_b70.DEFAULT_TEXT, instruct=ins)
                    for v, ins in TEST_VOICES.items() if not os.path.exists(os.path.join(vdir, f"{v}.wav"))]
            if jobs:
                qwen_b70.run_batches(m, jobs, 1, a.seed, kind, log=lambda x: None)
        del m, fast; torch.xpu.empty_cache()


if __name__ == "__main__":
    main()
