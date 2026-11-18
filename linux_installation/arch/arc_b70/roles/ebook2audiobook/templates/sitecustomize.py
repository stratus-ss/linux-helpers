"""Neutralise torchaudio's sox backend on this image.

torchaudio 2.8's sox backend SEGFAULTS inside the torch C++ dispatcher on this
build. It is not a Python exception -- the process dies with SIGSEGV and no
traceback reaches the log, so the failure looks like the app hanging:

    Fatal Python error: Segmentation fault
      File "torch/_ops.py", line 1243 in __call__
      File "torchaudio/_backend/sox.py", line 44 in load

The sox CLI itself works fine on the same file, and soundfile reads it without
complaint, so this is the torchaudio C++ extension against Arch's sox-ng 14.8,
not a broken file and not a missing library.

The app's XTTS path hits this in coqui-tts' load_audio(), which calls
torchaudio.load() on the reference waveform to clone a voice. So the voice
clone crashes the whole conversion, silently, after the UI has already started
work.

torchaudio.load picks a backend through a dispatcher that holds the backend map
in a CLOSURE CELL captured at import time. Replacing the module attribute
get_available_backends has no effect on it -- the cell has to be written
directly, which is what this module does. Python imports sitecustomize
automatically at interpreter start, so this applies to every process in the
image, including the ones the app spawns.

Removing sox leaves soundfile, which handles everything the app loads: WAV
references, and the mp3/m4a intermediates the pipeline produces.
"""

try:
    import torchaudio
    import torchaudio._backend.utils as _ta_utils

    _dispatcher = torchaudio.load.__closure__[0].cell_contents
    _backends = _dispatcher.__closure__[0]
    if "sox" in _backends.cell_contents:
        _backends.cell_contents = {
            k: v for k, v in _backends.cell_contents.items() if k != "sox"
        }
except Exception:  # never let a convenience patch break the interpreter
    pass
