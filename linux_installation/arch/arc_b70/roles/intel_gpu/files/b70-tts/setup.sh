#!/usr/bin/env bash
# Set up Fish Audio S2 Pro and Qwen3-TTS for an Intel Arc B70 (XPU) under Linux. No sudo, no CUDA wheels.
#
#   ./setup.sh            everything: fish-speech checkout + patch, both venvs, all weights
#   ./setup.sh fish       only Fish (checkout, .venv-fish, S2 Pro weights)
#   ./setup.sh qwen       only Qwen (.venv-qwen, VoiceDesign + Base weights)
#   SKIP_WEIGHTS=1 ./setup.sh   skip the downloads (~11 GB Fish, ~8.6 GB Qwen)
#
# Needs: git, uv, and the Intel GPU user-space stack from your distro (intel-compute-runtime, level-zero-loader).
# Env: FISH_SPEECH_DIR (default ./fish-speech), FISH_CKPT (default $FISH_SPEECH_DIR/checkpoints/s2-pro),
#      HF_HOME / HF_TOKEN as usual for Hugging Face downloads.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WHAT="${1:-all}"
PY=3.12
XPU_INDEX=https://download.pytorch.org/whl/xpu
FISH_REPO=https://github.com/fishaudio/fish-speech.git
FISH_COMMIT=214da3cd841bda85da2496b96cd3c4d7edb1337e
FISH_WEIGHTS=fishaudio/s2-pro
FISH_WEIGHTS_REV=1de9996b6be38b745688de084d87a5633f714e4e
FISH_DIR="${FISH_SPEECH_DIR:-$ROOT/fish-speech}"
FISH_CKPT="${FISH_CKPT:-$FISH_DIR/checkpoints/s2-pro}"
export CUDA_VISIBLE_DEVICES=""

make_venv() {  # make_venv <dir> <requirements file>
  local venv="$1" req="$2"
  [ -x "$venv/bin/python" ] || uv venv --python "$PY" "$venv"
  # 1) torch 2.11 XPU + oneAPI runtime wheels, only from the PyTorch XPU index
  uv pip install --python "$venv/bin/python" --index-url "$XPU_INDEX" -r "$ROOT/requirements/xpu-torch.txt"
  # 2) everything else at exact pins, without dependency resolution (so nothing can pull a CUDA torch)
  uv pip install --python "$venv/bin/python" --no-deps -r "$req"
}

check_xpu() {
  "$1/bin/python" - <<'EOF'
import torch
assert torch.xpu.is_available(), "torch sees no XPU device (check intel-compute-runtime / level-zero-loader)"
print(f"torch {torch.__version__} on {torch.xpu.get_device_name(0)}")
EOF
}

if [ "$WHAT" = all ] || [ "$WHAT" = fish ]; then
  echo "== fish-speech @ ${FISH_COMMIT:0:7}"
  if [ ! -d "$FISH_DIR/.git" ]; then
    git init -q "$FISH_DIR"
    git -C "$FISH_DIR" remote add origin "$FISH_REPO"
    git -C "$FISH_DIR" fetch -q --depth 1 origin "$FISH_COMMIT"
    git -C "$FISH_DIR" checkout -q FETCH_HEAD
  fi
  [ "$(git -C "$FISH_DIR" rev-parse HEAD)" = "$FISH_COMMIT" ] || { echo "fish-speech is not at $FISH_COMMIT" >&2; exit 1; }
  if git -C "$FISH_DIR" apply --reverse --check "$ROOT/patches/fish-speech-xpu.patch" 2>/dev/null; then
    echo "patch already applied"
  else
    git -C "$FISH_DIR" apply "$ROOT/patches/fish-speech-xpu.patch"
    echo "patch applied"
  fi
  echo "== .venv-fish"
  make_venv "$ROOT/.venv-fish" "$ROOT/requirements/fish.txt"
  uv pip install --python "$ROOT/.venv-fish/bin/python" --no-deps -e "$FISH_DIR"
  check_xpu "$ROOT/.venv-fish"
  if [ -z "${SKIP_WEIGHTS:-}" ]; then
    echo "== $FISH_WEIGHTS @ ${FISH_WEIGHTS_REV:0:7} -> $FISH_CKPT"
    "$ROOT/.venv-fish/bin/hf" download "$FISH_WEIGHTS" --revision "$FISH_WEIGHTS_REV" --local-dir "$FISH_CKPT"
  fi
fi

if [ "$WHAT" = all ] || [ "$WHAT" = qwen ]; then
  echo "== .venv-qwen"
  make_venv "$ROOT/.venv-qwen" "$ROOT/requirements/qwen.txt"
  check_xpu "$ROOT/.venv-qwen"
  if [ -z "${SKIP_WEIGHTS:-}" ]; then
    echo "== Qwen3-TTS weights (Hugging Face cache)"
    "$ROOT/.venv-qwen/bin/python" - "$ROOT/qwen" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1])
from huggingface_hub import snapshot_download
from qwen_b70 import MODELS
for repo, rev in MODELS.values():
    print(repo, rev[:7], snapshot_download(repo, revision=rev))
EOF
  fi
fi
echo "done"
