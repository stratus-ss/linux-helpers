# Fish S2 Pro and Qwen3-TTS on an Intel Arc Pro B70

Voice design and voice cloning on one Intel Arc Pro B70 (Battlemage, 32 GB, `xe` driver) under Linux, with
PyTorch 2.11 XPU and no CUDA anywhere. Qwen3-TTS 1.7B designs a voice from a text description, and Fish Audio
S2 Pro (4.6B) clones it to read a script of lines from a TSV. Both models are decode-loop bound, so this repo is
mostly about getting the per-frame launch overhead out of the way: XPU graphs, fixed shapes and batching.

**Result:** Fish S2 Pro cloning went from **~3.0 s of GPU time per second of audio** on the RTX 3080 Ti baseline
to **0.99 s/s** for a single line and **0.21 s/s end to end at batch 32** (0.08 s/s of generation). Qwen3-TTS went
from **~1.2 s/s** to **~0.85 s/s** for a single line once warm and **0.05 s/s** at batch 32.

Demo (generic test voice and lines): `demo/qwen-design-narrator.wav` is a voice designed by Qwen from one sentence
of description, `demo/fish-clone-narrator.wav` is Fish S2 Pro cloning it on a new line, and
`demo/fish-clone-bright-whisper.wav` shows a Fish inline emotion tag (`[whispering]`).

## What is here

- `patches/fish-speech-xpu.patch` applies to fishaudio/fish-speech
  [`214da3c`](https://github.com/fishaudio/fish-speech/commit/214da3cd841bda85da2496b96cd3c4d7edb1337e).
  Qwen3-TTS needs no patch: `qwen-tts` 0.1.1 is used as is and patched at runtime.
- `fish/`
  - `fish_clone.py`: batched cloning from a TSV of lines (the script to use).
  - `xpu_batch.py`: batched + XPU-graph decode loop for S2 Pro.
  - `bench_single.py`, `xpu_graph_decode.py`: the single-line benchmark through fish-speech's own
    `generate_long`, with the speedups and non-speedups below as flags.
- `qwen/`
  - `qwen_b70.py`: `design` (VoiceDesign) and `clone` (Base), both from TSVs, batched.
  - `xpu_fast.py`: the XPU-graph code predictor and the grouped codec decode.
  - `bench_qwen.py`: the Qwen benchmark.
- `setup.sh`, `requirements/`: from-scratch setup with exact pins and no CUDA wheels.
- `bench/`: raw benchmark TSVs. `examples/`: the TSVs used in the usage section.
- `b70_load.py`: safe model loading for every torch-XPU loader here (chunked host-to-device copies and an xe fault
  watchdog, see Gotchas).
- **Fish Audio Drama 3** runs through a fork of audio.cpp instead of PyTorch:
  [horvay/audio.cpp](https://github.com/horvay/audio.cpp) (`main`). See the Drama 3 section below.

## Results

All timings are wall-clock seconds per second of generated audio (s/s, lower is better) after warmup. Lines are
single sentences of 3-10 s. The baseline is the same models on an RTX 3080 Ti 12 GB with CUDA, bf16, one line at a
time (Fish additionally int8, see below).

### Fish Audio S2 Pro (voice clone, 44.1 kHz)

| Setup | Generation s/s | Total s/s (encode + generate + decode) | Peak VRAM |
| --- | --- | --- | --- |
| RTX 3080 Ti, int8 weights, 4096 context, codec swapped in and out | 2.95 | ~3.0+ | 5.7 GiB |
| B70, stock fish-speech, bf16, torch 2.8 | 3.78 (2.7-5.1) | 4.32 | 13.4 GiB |
| + KV length rounded up to multiples of 256 | 2.78 | 3.00 | 13.4 GiB |
| + torch 2.11 | 2.32 | 2.71 | 13.4 GiB |
| + XPU graph per frame | 1.11 | 1.51 | 13.4 GiB |
| `fish_clone.py`, batch 1 (+ sub-vocab head, GQA fold) | 0.99 | 1.14 | 13.3 GiB |
| `fish_clone.py`, batch 8 | 0.175 | 0.33 | 15.3 GiB |
| `fish_clone.py`, batch 16 | 0.120 | 0.27 | 17.7 GiB |
| `fish_clone.py`, batch 32 | **0.077** | **0.21** | 26 GiB |

Quality held: WhisperX large-v3 word error rate was 0% on every B70 clip (52 clips), the same as on the 3080, and
speaker similarity to the reference (WeSpeaker ResNet34 cosine) averaged 0.815 over 32 voices at batch 32 against
0.815 over 55 voices on the 3080 (`bench/fish_quality.tsv`). Peak host RAM was 18 GB while loading.

At batch 32, reference encoding was half of the wall time (28 of 57 s) because the benchmark used 32 different
reference voices and every new reference length compiles new codec kernels. References are cached per voice, so
with a few voices and many lines this cost disappears and total time approaches generation time.

### Qwen3-TTS 1.7B (VoiceDesign and Base clone, 24 kHz)

| Setup | VoiceDesign s/s | Base clone s/s | Peak VRAM |
| --- | --- | --- | --- |
| RTX 3080 Ti, CUDA, bf16, batch 1 | 1.24 | 1.17 | (not recorded) |
| B70, stock `qwen-tts`, batch 1 | 2.33 | 2.41 | 4.1-5.0 GiB |
| B70, stock, batch 8 | 0.39 | 0.35 | 5.9-6.5 GiB |
| B70, XPU-graph code predictor, batch 1 | 0.84-1.54 | 0.83-1.19 | 4.1-4.3 GiB |
| B70, XPU-graph code predictor, batch 16 | 0.088 | 0.083 | 5.8-6.3 GiB |
| B70, XPU-graph code predictor, batch 32 | **0.050** | **0.054** | 5.9-6.3 GiB |

Single-line rows are noisy because each new KV length still compiles kernels the first time it is seen; on a
warm, repeated line the graph path runs at 0.84 s/s against 2.1 s/s stock. Peak host RAM was 4.6-7.9 GB. Raw rows,
including batch 8 with graphs, are in `bench/qwen.tsv`.

The XPU path keeps the stock HF `generate()` for the 28-layer talker and replaces only the per-frame code predictor
(see below). Batching rows of different lengths is native in `qwen-tts`.

### Fish Audio Drama 3 (voice clone, 44.1 kHz, audio.cpp + Vulkan)

Drama 3 (released 2026-10-13) is a 35B mixture-of-experts model with about 3B active parameters per token. The
official weights are 41.5 GB and don't fit the B70, so it runs as the community Q4_K GGUF
(`Jmica/Drama-3-GGUF`, `drama-3-experts-q4_k-backbone-q8_0.gguf`, 24.6 GB) in audio.cpp's native port through
ggml's Vulkan backend on Mesa. Stock audio.cpp generates one line at a time; the fork adds a batched engine and a
TSV tool, `drama3_batch`.

| Setup | Step time | End-to-end s/s | Peak VRAM |
| --- | --- | --- | --- |
| Stock audio.cpp CLI, one line at a time | ~45 ms per frame | 0.875-1.18 | ~23 GiB |
| Batch engine, batch 8 | 44 ms | 0.286 | 24.7 GiB |
| + fused MoE adds, fewer copies, codec graphs per 32-frame bucket, batch 8 | 39.7 ms | 0.204 | |
| + mat-vec paths up to 16 columns, batch 16 | 70.4 ms | 0.154 | ~30 GiB |
| + common suffix tokens in the cached voice prefix, batch 16 | 76.2 ms | 0.161 | ~30 GiB |
| Final, batch 16 (256 lines, 1,711 s of audio) | 75.1 ms | **0.159** | 29.1 GiB |

End-to-end includes reference encoding, generation, codec decode and writing wavs, on short game lines (3-10 s).
Quality held: on a fixed 20-line set from 4 voices (8 with inline tags), WhisperX large-v3 word error rate was 0.5%
for the final batch-16 build against 1.2% for the stock CLI, and WeSpeaker speaker similarity 0.729 against 0.721.
About 1 line in 250 still runs away; every line is capped by its length (100 frames + 4.5 per character + 65 per pause
tag), and a capped line is regenerated once with another seed inside the batch and listed in `<out>/limited.tsv`.
Peak VRAM is about 29 GiB, so the job needs most of the card.

Usage (from the fork's build): `drama3_batch` reads the same TSV as `fish/fish_clone.py`
(`out_name<TAB>voice<TAB>text[<TAB>ref_text]`, voices as `<voices-dir>/<name>.wav` plus a `.txt` transcript), writes
44.1 kHz mono wavs to `<out>/<out_name>.wav`, skips existing outputs, and reads `[crying]`/`[sobbing]` as `[tearful]`
(Drama 3 sometimes turns a long crying-tagged line into crying with almost no words).

What made the difference, and where it stops:
- **One graph per step for the whole batch:** the stock port runs 16 separate graph computes per audio frame, each
  with a blocking readback and CPU-side sampling. The batch engine runs the backbone, a 4,097-row slice of the LM
  head, GPU Gumbel-max sampling with RAS and all 13 codebook tower layers in one graph, reads back 10 ints per row,
  refills finished rows continuously, and computes each voice's reference prefix once.
- **Codec decode graphs cached per 32-frame bucket:** decode went from 0.078 to 0.025 s/s.
- **Mat-vec kernels for up to 16 columns:** ggml-vulkan's tiled matmul shaders have a large fixed cost per k step on
  this card, so any matmul over 8 columns cost 80-400 us. Letting the mat-vec path take up to 16 columns made batch
  16 cost about the same per row as batch 8.
- **The wall:** at batch 16 a row-step needs about 3.5 B multiply-adds, and the DP4A/FMA kernels top out near 1.35 T
  multiply-adds/s, so the dense layers are arithmetic-bound. The XMX matrix engines (coopmat2) only pay off at 128+
  columns on Mesa, well above what a batch of game lines gives. Batch 32 is no faster per row than batch 16.

## What helped and what didn't

The B70 runs a 1-token decode step far below its compute or bandwidth limit. Each audio frame launches about a
thousand small kernels from Python (Fish: 36 slow layers, then 10 codebook passes of a 4-layer fast transformer;
Qwen: 28 talker layers, then 15 passes of a 5-layer code predictor), and on XPU every launch is expensive. Almost
everything that helped either removes launches or does more work per launch.

| Change | Model | Effect |
| --- | --- | --- |
| **XPU graphs** (`torch.xpu.XPUGraph`, torch >= 2.10) for the per-frame step | Fish, Qwen | Fish 2.3 → 1.1 s/s; Qwen code predictor was ~120 ms of each ~170 ms frame; single line 2.1 → 0.84 s/s |
| **Batching** lines (left-padded prompts plus a per-row key mask in Fish; native in Qwen) | Fish, Qwen | Nearly free per extra row: Fish batch 32 is 13x the throughput of batch 1 |
| **KV length bucketing** to multiples of 256 | Fish | Kills the per-length kernel JIT: first-pass lines went from 2.7-5.1 to a flat 2.7 s/s; also makes graphs possible (one graph per bucket) |
| **torch 2.8 → 2.11** XPU | Fish | 2.78 → 2.32 s/s, and XPU graphs need >= 2.10 |
| **GQA fold** (single-query attention without `repeat_interleave`) | Fish | batch 8: 0.27 → 0.175 s/s generation |
| **Sub-vocab head** (logits only over the 4096 semantic tokens + `<|im_end|>`) | Fish | skips 0.8 GB of reads and a 155k-wide sort per frame |
| **Codec decode bucketing and batching** (pad frame counts to multiples of 64, decode 8 at a time) | Fish, Qwen | avoids a ~2 s kernel JIT per new length; Qwen also needs grouping to avoid `OUT_OF_RESOURCES` |
| bf16 | Fish, Qwen | used throughout; fp32 was not benchmarked |
| int8 weight-only linears | Fish | **2x slower** (5.9 vs 2.8 s/s): the dequantize is extra kernels, and the step is not bandwidth bound |
| `torch.compile` (inductor + Triton XPU) | Fish | still compiling the first line after 8 minutes (dynamic KV length); abandoned for XPU graphs |
| Graphing the Qwen talker too | Qwen | not tried: it runs inside HF `generate()` with a growing `DynamicCache`, so it would need a custom loop like `fish/xpu_batch.py`. It is now most of the remaining per-frame time, so this is the next step if Qwen speed ever matters |

## Setup

Needs Linux with the `xe` kernel driver and the Intel GPU user space from your distro (`intel-compute-runtime`,
`level-zero-loader`, `intel-graphics-compiler`), git, and [uv](https://docs.astral.sh/uv/). No sudo is needed past
that, and nothing here installs CUDA wheels. `./setup.sh` does all of the following; the steps are:

```sh
git clone https://github.com/horvay/b70-tts && cd b70-tts

# 1. fish-speech at the pinned commit, plus the XPU patch
git init fish-speech && cd fish-speech
git remote add origin https://github.com/fishaudio/fish-speech.git
git fetch --depth 1 origin 214da3cd841bda85da2496b96cd3c4d7edb1337e && git checkout FETCH_HEAD
git apply ../patches/fish-speech-xpu.patch && cd ..

# 2. two venvs: torch 2.11 XPU from the PyTorch XPU index, then everything else at exact pins with --no-deps
#    (so nothing can pull a CUDA torch back in)
for v in fish qwen; do
  uv venv --python 3.12 .venv-$v
  uv pip install --python .venv-$v/bin/python --index-url https://download.pytorch.org/whl/xpu -r requirements/xpu-torch.txt
  uv pip install --python .venv-$v/bin/python --no-deps -r requirements/$v.txt
done
uv pip install --python .venv-fish/bin/python --no-deps -e fish-speech

# 3. weights (pinned revisions): S2 Pro into fish-speech/checkpoints, Qwen into the Hugging Face cache
.venv-fish/bin/hf download fishaudio/s2-pro --revision 1de9996b6be38b745688de084d87a5633f714e4e \
    --local-dir fish-speech/checkpoints/s2-pro
.venv-qwen/bin/hf download Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --revision 5ecdb67327fd37bb2e042aab12ff7391903235d3
.venv-qwen/bin/hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base --revision fd4b254389122332181a7c3db7f27e918eec64e3
```

`./setup.sh fish` or `./setup.sh qwen` sets up one side; `SKIP_WEIGHTS=1` skips the downloads (about 11 GB for
Fish, 8.6 GB for the two Qwen models). `FISH_SPEECH_DIR` and `FISH_CKPT` point the scripts at an existing checkout
or weights folder.

The two venvs share torch and transformers 4.57.3 but differ in a few pins (`pydantic`, `protobuf`, `fsspec`);
`qwen-tts` would probably install into the Fish venv too, but only the two-venv setup is tested. `uv pip check`
reports three mismatches in the Fish venv (protobuf for `descript-audiotools` and `googleapis-common-protos`,
setuptools for torch); they are inherited from upstream's pins and harmless for inference.

## Usage

Run everything with `CUDA_VISIBLE_DEVICES=""` if the machine also has an NVIDIA card (the scripts set it too).

**1. Design voices with Qwen.** A voices TSV is `name<TAB>description[<TAB>text]`:

```tsv
narrator	A calm middle-aged man with a deep, warm voice, speaking slowly and clearly like an audiobook narrator.
bright	A cheerful young woman with a bright, clear voice, speaking with energy and a smile, like a morning radio host.
```

```sh
.venv-qwen/bin/python qwen/qwen_b70.py design examples/voices.tsv --out out/voices
```

This writes `out/voices/narrator.wav` and `narrator.txt` (what it says). Every voice reads the same neutral
sentence unless the row gives its own text. Rerun with another `--seed` or reword the description if a take is off.

**2. Clone lines with Fish.** A lines TSV is `out_name<TAB>voice<TAB>text[<TAB>ref_text]`, where `voice` is a name
in `--voices-dir` or a path to any reference wav, and `ref_text` (what the reference says) defaults to the voice's
`.txt` file. Fish inline tags such as `[whispering]`, `[laughing]`, `[sigh]` or `[crying]` go in the text:

```tsv
narrator-01	narrator	The train to the coast leaves at nine, so pack light and bring a warm coat.
bright-whisper	bright	[whispering] Keep your voice down. Everyone else is still asleep.
```

```sh
.venv-fish/bin/python fish/fish_clone.py examples/lines.tsv --voices-dir out/voices --out out/lines --batch 16
```

Existing outputs are skipped, so an interrupted run resumes. Batch 16-32 is the sweet spot for a long script;
`--batch 1` is the lowest latency for one line. The same TSV also works with Qwen's Base model
(`qwen/qwen_b70.py clone examples/lines.tsv --voices-dir out/voices --out out/qwen-lines`), minus the emotion tags.

**Benchmarks:** `qwen/bench_qwen.py` reproduces the Qwen table. `fish/bench_single.py --voices-dir out/voices
--voices narrator bright --tag x [--kv-bucket 256] [--graph] [--quant int8] [--compile]` reproduces the single-line
Fish rows, and `fish/fish_clone.py ... --batch N --bench-tsv bench/fish_batch.tsv --tag x` the batched ones.

## Gotchas

- **Sampling settings in fish-speech:** `init_model()` sets `model.fixed_temperature = 0.7`, `fixed_top_p = 0.7`
  and `fixed_repetition_penalty = 1.5`, but nothing reads them. Generation uses `generate_long()`'s arguments
  (temperature 1.0, top-p 0.9, top-k 30), and its `repetition_penalty` argument is unused as well: repetition is
  handled by RAS resampling. A cloning script that copies those three lines changes nothing. `fish_clone.py` uses
  1.0 / 0.9 / 30 explicitly (`--temperature`, `--top-p`, `--top-k`).
- **Graph runs are not seed-reproducible against eager runs.** Random draws inside a replayed XPU graph advance the
  generator differently, so the same seed gives a different (equally valid) take than the stock path, and a take
  can also change with batch size or position in the batch.
- **A batch waits for its longest line.** Finished rows keep decoding until every row has stopped, which is why the
  scripts sort lines by text length before batching. Mixing a one-word line with a paragraph wastes most of a batch.
- **One line per row for Fish.** `fish_clone.py` does not split long text the way `generate_long` does; keep rows
  under about a minute of speech (`--max-length 2048` covers prompt + output frames at 21.5 frames/s).
- **int8 is slower on XPU.** Weight-only int8 was what made S2 Pro fit a 12 GB card, but on the B70 it doubled the
  time. There is room for bf16 (13.4 GiB for batch 1), so use it.
- **Triton on XPU (`torch.compile`):** Triton builds its launcher with the Level Zero headers (`level_zero/ze_api.h`),
  which the runtime packages do not ship; without root, unpack them somewhere and set `CPATH`. Once it builds, it
  prints `sycl_arch not recognized: 0` for the B70 and compiled Fish's dynamic-shape decode for minutes without
  finishing a line. XPU graphs need none of this.
- **`UR_RESULT_ERROR_OUT_OF_RESOURCES` in the Qwen codec.** Decoding a whole batch of Qwen clone outputs at once
  (they are decoded with the reference prepended, so 15-20 s each) intermittently failed in the codec's conv layers
  at batch 8-32 with most of the 32 GB still free. `xpu_fast.limit_codec_batch` decodes in fixed-shape groups of at most 1024
  padded frames; output matches upstream's batched decode.
- **xe engine faults on large host-to-device copies.** Moving a model to the B70 in one `.to("xpu")` pins large
  tensors (Fish's 800 MiB embedding) as userptr; under host memory pressure the pin times out and the copy engine
  faults ("Engine memory CAT error, class=bcs", engine reset, the job hangs; intel/compute-runtime#1010).
  `b70_load.to_dev_chunked` copies in pieces of at most 32 MiB, and `xe_watchdog` exits the process when the kernel
  log shows an xe fault, so a faulted job fails fast instead of hanging.
- **SoX warning:** `qwen-tts` prints "SoX could not be found!" at import. It is not used on this path.
- **Python launch speed matters.** Even with graphs, both models are CPU-bound on the host side; other heavy CPU load
  on the machine shows up directly in the timings.

## Hardware and software

Intel Arc Pro B70 32 GB (BMG-G31, PCI 8086:e223), AMD Ryzen 9 5900XT, 62 GB RAM. Linux 7.2 (Arch based) with the
in-kernel `xe` driver, intel-compute-runtime 26.31.39395.13, intel-graphics-compiler 2.40.13, level-zero-loader
1.32.0. Python 3.12, uv 0.12, torch 2.11.0+xpu with the oneAPI 2025.3 runtime wheels, triton-xpu 3.7.0,
transformers 4.57.3, qwen-tts 0.1.1. fish-speech at `214da3c`, S2 Pro weights at `1de9996`, Qwen3-TTS-12Hz-1.7B
VoiceDesign `5ecdb67` and Base `fd4b254`. The baseline used torch 2.8 (cu128) on the RTX 3080 Ti 12 GB.

## License

- **This repo's own code** (`qwen/`, `setup.sh`, `bench/`, `examples/`) is MIT, see `LICENSE`.
- **`fish/`** closely follows fish-speech internals (prompt building, sampling, `encode_audio`), so it is treated
  as a Derivative Work and distributed under the [Fish Audio Research License](patches/LICENSE-FISH-AUDIO.md), like
  the patch.
- **`patches/fish-speech-xpu.patch`** modifies Fish Audio's fish-speech code, so it is a Derivative Work under the
  [Fish Audio Research License](patches/LICENSE-FISH-AUDIO.md) and is distributed under it, with the attribution and
  change notes it requires in `NOTICE`. Built with Fish Audio.
- **fish-speech and the S2 Pro weights** are not included. They are under the Fish Audio Research License: research,
  evaluation and hobby use are free; any use "primarily intended for or directed toward commercial advantage or
  monetary compensation", including "any use in connection with a product or service for which You charge a fee or
  generate revenue, whether directly or indirectly", needs a separate written license from Fish Audio. Outputs are
  not Derivative Works and belong to you, but they are still subject to Fish Audio's Acceptable Use Policy and may
  not be used to train or improve other foundation models. In practice, all Fish use stays non-commercial.
- **Qwen3-TTS** (`qwen-tts` package and the Qwen3-TTS-12Hz-1.7B weights) is Apache 2.0 and is used unmodified.
- The demo audio was generated by these models from generic test descriptions and text; no real person's voice was
  used.
