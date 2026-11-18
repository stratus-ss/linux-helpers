# Shared XPU base image -- the Intel GPU userspace both app images need.
#
# WHY A SHARED BASE, AND WHY ARCH:
#
# Every app image needs the same two things that pip cannot supply: the Level
# Zero loader and the NEO Level Zero driver that plugs into it. Building them
# once means the driver version is defined in exactly one place and provably
# matches the host's.
#
# Arch, because no Debian/Ubuntu packaging of Intel's Level Zero driver
# supports Battlemage. Measured 2026-11-17 against this card (8086:E223, xe):
#
#   Debian 12 bookworm  intel-opencl-icd      22.43.24595.41   (no L0 driver at all)
#   Intel apt repo      libze-intel-gpu1      25.18.33578.15   (0 Battlemage strings)
#   Arch rolling        intel-compute-runtime 26.40.40196.8    (names "Arc(TM) Pro B70")
#
# Inside a Debian image the result was a correct +xpu torch reporting "XPU
# device count is zero", with zeInit returning ZE_RESULT_ERROR_UNINITIALIZED:
# the driver was present and did not know the card. Both packages come from
# Arch's `extra` repo -- the same repo the host installs them from -- so the
# container's driver version is the host's driver version.
#
# The container needs only USERSPACE. The kernel driver arrives through
# /dev/dri at run time.
FROM archlinux:base

# `pacman -Syu` is not optional: archlinux:base is a snapshot, and installing
# without a full upgrade either fails on signature/dependency drift or, worse,
# resolves an old compute-runtime -- the exact thing this image exists to
# avoid.
#
# The GL/X11 set is not decoration: ComfyUI links against libGL for its
# preview surface, and an image missing it fails at import time with a
# "libGL.so.1: cannot open shared object file" that has nothing to do with
# the GPU.
#
# NO TORCH HERE. Torch is per-app and pinned by each app image (DR-9); two
# torch stacks in one image would be one stack too many.
#
# NO intel-oneapi-* packages either. The pip intel-sycl-rt / dpcpp-cpp-rt
# wheels that torch==<xpu> pulls already provide the SYCL runtime, and
# installing both risks a second libsycl.so on the loader path -- which is
# the failure mode Task 10 of the previous plan spent hours on.
RUN pacman -Syu --needed --noconfirm \
      python python-pip uv git curl ca-certificates tzdata \
      libgl libglvnd libxext libxrender libsm libice libxcb libgomp \
      intel-compute-runtime level-zero-loader \
 && pacman -Scc --noconfirm

# A build toolchain is NOT optional, and this was found by building rather than
# by reading: TTS-Audio-Suite requires pyworld, which publishes no wheel for
# Python 3.12, so pip compiles it -- and the build died with
# "error: [Errno 2] No such file or directory: 'c++'". base-devel is Arch's
# build-essentials group (gcc, make, binutils, ...) in one line.
#
# libsndfile is the matching RUNTIME dependency: soundfile ships manylinux
# wheels that import libsndfile.so.1 lazily, so a missing library shows up as a
# custom node failing to load rather than as a pip error.
#
# Both live in the base because every audio node on this host shares the
# problem, and a compiler installed per-image would be installed twice.
RUN pacman -S --needed --noconfirm base-devel libsndfile \
 && pacman -Scc --noconfirm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# The venv exists so each app image can install into it without touching the
# system Python, which is PEP 668 externally-managed and refuses everything.
#
# --seed is required, not cosmetic: `uv venv` does not install pip, so a bare
# `pip` in a later layer falls through to Arch's system Python.
#
# Python 3.12 is pinned because torch's XPU wheels and every app requirement
# here have a 3.12 wheel. Arch's system python is 3.14, and not every
# dependency has a 3.14 wheel yet -- so the venv pins its own interpreter
# rather than inheriting the system's.
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv venv --python 3.12 --seed /opt/venv

# The assertion that proves this image carries the driver it claims. It reads
# the packages' own database and the loader's own file -- not a value
# written elsewhere -- so an image that silently lost the driver fails here
# instead of at the first GPU call.
RUN set -eux; \
    pacman -Q level-zero-loader intel-compute-runtime; \
    test -e /usr/lib/libze_loader.so; \
    test -e /usr/lib/libze_intel_gpu.so.1; \
    /opt/venv/bin/python -c "import sys; print('BASE-PYTHON', sys.version.split()[0])"
