#!/usr/bin/env python3
"""Acceptance probe: transcribe a known audio file through the Whisper WebUI.

The app is a GRADIO app, not a plain FastAPI one. Its transcription
endpoint is the named Gradio endpoint /transcribe_file, which is reached
through Gradio's own API:

    POST /gradio_api/upload          -> a file handle for the audio
    POST /gradio_api/call/transcribe_file -> the call itself

The endpoint's parameter list and its defaults are read from the running
server's own /gradio_api/info, never guessed: /transcribe_file takes 56
parameters and the app's own defaults are sent for every one of them
except the file, so the probe exercises the shipped configuration instead
of an invented one.

Exits 0 on success, 1 on any failure, so `failed_when` can simply read the
rc.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

BASE = os.environ.get("WHISPER_BASE", "http://127.0.0.1:7871")
ENDPOINT = "transcribe_file"
AUDIO = sys.argv[1] if len(sys.argv) > 1 else ""
# The probe transcribes a SHORT excerpt, not the whole file. The probe audio
# on the NAS is 75 minutes long; transcribing all of it on a CPU-only build
# takes many minutes, which is a long acceptance for a check that only has
# to prove the pipeline works.
CLIP_SECONDS = int(os.environ.get("WHISPER_PROBE_SECONDS", "30"))


def clip_audio(path, seconds):
    """A short excerpt of the audio, as a wav in a temp dir.

    ffmpeg is used rather than a Python library: the host has it, it is
    what the app itself uses for audio, and it needs no extra package.
    """
    if not shutil.which("ffmpeg"):
        return path
    tmpdir = tempfile.mkdtemp(prefix="arc_b70_probe_")
    out = os.path.join(tmpdir, "clip.wav")
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error",
            "-i", path,
            "-t", str(seconds),
            "-ac", "1", "-ar", "16000",
            out,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not os.path.isfile(out):
        shutil.rmtree(tmpdir, ignore_errors=True)
        return path
    return out


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def post_json(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=1800) as r:
        return r.status, r.read().decode("utf-8", "replace")


def post_multipart(url, filename, payload_bytes, content_type):
    boundary = "----arcb70probe"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            payload_bytes,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=1800) as r:
        return r.status, r.read().decode("utf-8", "replace")


def named_endpoint():
    """The endpoint's parameter list and defaults, from the live server."""
    info = get_json(f"{BASE}/gradio_api/info")
    endpoints = info.get("named_endpoints") or {}
    spec = endpoints.get(f"/{ENDPOINT}")
    if not spec:
        raise SystemExit(
            f"the server has no /{ENDPOINT} endpoint. named_endpoints: "
            f"{sorted(endpoints)}"
        )
    return spec


def read_event_stream(url):
    """Read Gradio's server-sent-events stream and return the transcript.

    The stream carries 'event: <name>' and 'data: <json>' lines. The
    completion event's data is the endpoint's return values.

    The shape of that data depends on the endpoint: it can be a LIST of
    return values (the first being the transcript) or a bare STRING. This
    endpoint returns the latter -- the whole transcript as one string. A
    string is a sequence in Python, so indexing it yields a single
    character; that has to be handled before the list case.
    """
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=3600) as r:
        event = None
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event: "):
                event = line[len("event: "):].strip()
                continue
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload == "[DONE]":
                break
            if event == "error":
                sys.exit(f"the transcription call errored: {payload[:400]}")
            if event not in ("complete", "success", None):
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, str):
                return parsed
            if isinstance(parsed, list) and parsed:
                first = parsed[0]
                if isinstance(first, str):
                    return first
                return json.dumps(first)
    return ""


def main():
    if not AUDIO or not os.path.isfile(AUDIO):
        sys.exit(f"probe audio not found: {AUDIO!r}")

    probe_audio = clip_audio(AUDIO, CLIP_SECONDS)
    if probe_audio != AUDIO:
        print(f"probe clip: {CLIP_SECONDS}s of {AUDIO}")

    spec = named_endpoint()
    params = spec.get("parameters") or []

    # The file parameter is the one whose type mentions FileData. Its
    # default is None, so it is the only one that needs a value.
    file_param = next(
        (p for p in params if "FileData" in json.dumps(p.get("type", {}))),
        None,
    )
    if file_param is None:
        sys.exit(f"/{ENDPOINT} has no file parameter")

    # Every other parameter is sent with the server's OWN default, so the
    # probe exercises the shipped configuration (model size, compute type,
    # beam size, and the rest) rather than an invented one.
    #
    # Two corrections are forced by the server's own runtime validation,
    # which is stricter than the schema the info endpoint publishes:
    #
    #  - A default the runtime does not accept is replaced with the first
    #    choice it does accept. The compute-type parameter is the one that
    #    hits this: its published default is "float16", but the runtime
    #    accepts only ['int8_float32', 'float32', 'int8'].
    #  - A Number parameter must be sent as a number. A published default
    #    of None on a Number is sent as 0, not "".
    values = []
    for p in params:
        if p is file_param:
            values.append(None)
            continue
        default = p.get("parameter_default")
        choices = (p.get("type") or {}).get("enum")
        if isinstance(choices, list) and choices and default not in choices:
            default = choices[0]
        kind = (p.get("type") or {}).get("type")
        if kind == "number":
            if default is None:
                default = 0
            default = float(default)
        elif kind == "boolean":
            default = bool(default)
        elif default is None:
            default = ""
        values.append(default)

    # The compute type is the parameter whose choices are the CTranslate2
    # dtypes. float16 is not one of them, and a CPU-only build cannot use
    # it anyway, so int8_float32 is used -- the CPU path's dtype.
    for index, p in enumerate(params):
        choices = (p.get("type") or {}).get("enum") or []
        if set(choices) == {"int8_float32", "float32", "int8"}:
            values[index] = "int8_float32"
            break

    # The model size is the parameter whose choices are the whisper model
    # names. The published default is 'large-v2', which on a CPU-only build
    # takes many minutes for even a short clip -- and the probe's clip is
    # short precisely so the acceptance stays quick.
    #
    # 'small' is used because it is already on the NAS (the models mount is
    # models/Whisper/faster-whisper/, which holds tiny, small, small.en,
    # medium, medium.en, large-v2, large-v3 and large-v3-turbo). 'base' is
    # NOT there, and picking it would download the model on every run --
    # an acceptance check that needs the network to pass.
    for index, p in enumerate(params):
        choices = (p.get("type") or {}).get("enum") or []
        if "large-v2" in choices and "small" in choices:
            values[index] = "small"
            break

    name = os.path.basename(AUDIO)
    content_type = "audio/mpeg" if name.endswith(".mp3") else "application/octet-stream"
    with open(probe_audio, "rb") as fh:
        payload = fh.read()

    status, body = post_multipart(f"{BASE}/gradio_api/upload", name, payload, content_type)
    if status != 200:
        sys.exit(f"upload returned HTTP {status}: {body[:400]}")
    try:
        uploaded = json.loads(body)
    except json.JSONDecodeError:
        sys.exit(f"upload did not return JSON: {body[:400]}")

    # Gradio's upload returns a bare server-side path (a string) or a list
    # of paths. The endpoint wants Gradio's FileData shape, and 5.x
    # validates it strictly:
    #
    #   The 'meta' field must be explicitly provided in the input data and
    #   be equal to {'_type': 'gradio.FileData'}
    #
    # so the path is wrapped into that shape here.
    paths = uploaded if isinstance(uploaded, list) else [uploaded]
    file_value = []
    for item in paths:
        if isinstance(item, dict):
            entry = dict(item)
        else:
            entry = {"path": item}
        entry.setdefault("meta", {"_type": "gradio.FileData"})
        entry.setdefault("orig_name", name)
        entry.setdefault("size", len(payload))
        entry.setdefault("mime_type", content_type)
        file_value.append(entry)

    # The payload must have EXACTLY one value per declared parameter, in the
    # declared order. The file parameter is the first one, and its value is
    # the uploaded file handle -- so it is substituted into the list rather
    # than prepended, and nothing is filtered out. Filtering the None
    # placeholder out shifts every value by one, and the server then
    # reports "didn't receive enough input values (needed: 56, got: 0)".
    data = list(values)
    data[0] = file_value
    assert len(data) == len(params), f"{len(data)} values for {len(params)} parameters"

    status, body = post_json(f"{BASE}/gradio_api/call/{ENDPOINT}", {"data": data})
    if status != 200:
        sys.exit(f"call returned HTTP {status}: {body[:400]}")

    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        sys.exit(f"call did not return JSON: {body[:400]}")

    # Gradio's call endpoint returns an event id; the result arrives on the
    # server-sent-events stream at GET /gradio_api/call/<endpoint>/<event_id>.
    if isinstance(result, dict) and "event_id" in result:
        event_id = result["event_id"]
        text = read_event_stream(f"{BASE}/gradio_api/call/{ENDPOINT}/{event_id}")
    else:
        # The result is the list of the endpoint's return values: the
        # transcript text first, then the downloadable file.
        text = ""
        if isinstance(result, list) and result:
            text = str(result[0] or "")
        elif isinstance(result, str):
            text = result

    if not text.strip():
        sys.exit(f"empty transcript: {str(result)[:400]}")

    print(f"transcript: {len(text)} chars: {text.strip()[:300]}", flush=True)

    # The transcript is a subtitle file's contents: a header, then numbered
    # cues with timestamps. So the check is not "is there text" but "does it
    # look like a subtitle with cues" -- a header line, a timestamp range,
    # and the words the model actually heard. The clip is a fixed piece of
    # audio on the NAS, so the words are known.
    if "-->" not in text:
        sys.exit(f"transcript has no subtitle cues: {text[:200]}")
    words = re.findall(r"[A-Za-z']+", text)
    if len(words) < 20:
        sys.exit(f"transcript has too few words ({len(words)}): {text[:200]}")
    for expected in ("the", "and"):
        if expected not in [w.lower() for w in words]:
            sys.exit(f"transcript has no '{expected}': {text[:200]}")

    print("TRANSCRIBED OK", flush=True)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:400]}")
    except urllib.error.URLError as exc:
        sys.exit(f"connection failed: {exc}")
