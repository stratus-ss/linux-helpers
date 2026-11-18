"""Safe model loading on the Intel Arc Pro B70 (xe), shared by every torch-XPU loader (b70-tts and other projects).

to_dev_chunked(module, dev): module.to(dev) with every host->device copy split into <= 32 MiB pieces. A large single
copy (Fish's 800 MiB embedding) is pinned as userptr by the Level Zero runtime; under host memory reclaim the xe
userptr pin times out and the copy engine faults ("Engine memory CAT error, class=bcs", engine reset, the job hangs;
intel/compute-runtime#1010, seen 2026-10-12). Copies this small are staged instead. Tied parameters stay tied.

xe_watchdog(): starts a daemon thread that watches the kernel log for xe engine faults from now on and exits the
process (code 3) when one appears, so a faulted job fails fast instead of hanging silently.
"""
import os, subprocess, sys, threading, time

import torch

FAULT = ("CAT error", "Engine reset", "Timedout job")


def to_dev_chunked(module, dev, chunk=32 << 20):
    done = {}  # keyed by the persistent Parameter / buffer object (id() of a temporary like p.data gets reused)

    def move(t):
        d = torch.empty(t.shape, dtype=t.dtype, device=dev)
        src, dst = t.detach().contiguous().view(-1), d.view(-1); n = max(1, chunk // max(1, t.element_size()))
        for i in range(0, src.numel(), n): dst[i:i + n].copy_(src[i:i + n])
        return d
    for m in module.modules():
        for k, v in list(m._parameters.items()):
            if v is None: continue
            if id(v) not in done: done[id(v)] = (v, torch.nn.Parameter(move(v), requires_grad=False))
            m._parameters[k] = done[id(v)][1]
        for k, v in list(m._buffers.items()):
            if v is None: continue
            if id(v) not in done: done[id(v)] = (v, move(v))
            m._buffers[k] = done[id(v)][1]
    torch.xpu.synchronize()
    return module


def xe_faults(since):
    """xe engine-fault lines in the kernel log since the epoch time `since`."""
    try:
        out = subprocess.run(["journalctl", "-k", "--no-pager", "-q", "--since", f"@{int(since)}"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001  (no journal access: the watchdog just stays quiet)
        return []
    return [l for l in out.splitlines() if " xe " in l and any(f in l for f in FAULT)]


def xe_watchdog(poll=10):
    t0 = time.time()

    def run():
        while True:
            time.sleep(poll)
            hits = xe_faults(t0)
            if hits:
                print("B70 xe engine fault, stopping this job:\n  " + "\n  ".join(hits[-3:]), file=sys.stderr, flush=True)
                os._exit(3)
    threading.Thread(target=run, daemon=True).start()
