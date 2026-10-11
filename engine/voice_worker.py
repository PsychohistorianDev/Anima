"""Persistent speech sidecar. JSON lines in/out; model diagnostics go to stderr.

Only this interpreter imports speech dependencies. No identity, journal or
memory is read or written here. Models are downloaded to .runtime/models.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import sys
import queue
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / ".runtime" / "models"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
_tts = None
_stt = None
_stt_key = None
_stt_warmed = False
_warmed = False


class SpeechCancelled(Exception):
    pass


def cuda_memory_stats() -> dict:
    torch = sys.modules.get("torch")
    if torch is None or not torch.cuda.is_initialized():
        return {"allocated_bytes": 0, "reserved_bytes": 0}
    return {"allocated_bytes": int(torch.cuda.memory_allocated()),
            "reserved_bytes": int(torch.cuda.memory_reserved())}


def release_cuda_cache() -> None:
    """Free unused allocator/graph storage; keep the live speech models loaded."""
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_initialized():
        import gc
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except RuntimeError as e:
            # Cache cleanup must not replace valid speech or the original error.
            print(f"Unused CUDA cache could not be released: {e}", file=sys.stderr)


def encode_audio(samples, rate):
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="PCM_16")
    return {"audio": base64.b64encode(buf.getvalue()).decode("ascii"), "seconds": len(samples) / rate}


def check(req) -> dict:
    import importlib.util
    missing = [name for name in ("moshi", "torch", "faster_whisper", "soundfile")
               if importlib.util.find_spec(name) is None]
    return {"installed": not missing, "missing": missing}


def models(req: dict, speech=True):
    global _tts, _stt, _stt_key, _stt_warmed
    name = req.get("stt_model") or "large-v3-turbo"
    stt_device = req.get("stt_device") or "cpu"
    if stt_device not in ("cpu", "cuda"):
        raise ValueError("Speech recognition device must be cpu or cuda.")
    compute_type = "float16" if stt_device == "cuda" else "int8"
    stt_key = (name, stt_device, compute_type)
    if _stt is None or stt_key != _stt_key:
        from faster_whisper import WhisperModel
        _stt = WhisperModel(name, device=stt_device, compute_type=compute_type,
                            download_root=str(ROOT / ".runtime" / "models" / "whisper"),
                            local_files_only=bool(req.get("offline")))
        _stt_key = stt_key
        _stt_warmed = False
    if speech and _tts is None:
        from kyutai_voice import KyutaiVoice
        _tts = KyutaiVoice(req.get("device") or "cuda", offline=bool(req.get("offline")))


def handle(req: dict, emit=None, cancel=None) -> dict:
    if req.get("op") == "memory_stats":
        return cuda_memory_stats()
    if req.get("op") in {"warmup", "transcribe", "synthesize", "synthesize_stream", "download"}:
        try:
            return _handle(req, emit=emit, cancel=cancel)
        finally:
            release_cuda_cache()
    return _handle(req, emit=emit, cancel=cancel)


def _handle(req: dict, emit=None, cancel=None) -> dict:
    global _warmed, _stt_warmed
    if req["op"] == "check":
        return check(req)
    if req["op"] == "warmup":
        models(req)
        if not _stt_warmed:
            import numpy as np
            # Initialize recognition kernels before microphone capture starts.
            # The synthetic silence and any decoded text are discarded.
            segments, _ = _stt.transcribe(np.zeros(16000, dtype=np.float32),
                                         language=req.get("language") or None,
                                         vad_filter=False, beam_size=int(req.get("stt_beam_size") or 1),
                                         max_new_tokens=1, condition_on_previous_text=False)
            list(segments)
            _stt_warmed = True
        if not _warmed:
            # Pay first CUDA/kernel and watermark initialization before
            # listening, instead of adding it to the first spoken reply.
            generate(req, "Hello.")
            _warmed = True
        return {"ready": True}
    if req["op"] == "download":
        models(req)
        return {"downloaded": True}
    if req["op"] == "transcribe":
        import soundfile as sf
        import numpy as np
        raw = base64.b64decode(req["audio"], validate=True)
        samples, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
        if rate != 16000 or len(samples) > 16000 * 31 or samples.shape[1] != 1:
            raise ValueError("Expected mono 16 kHz audio, at most 31 seconds.")
        models(req, speech=False)
        segments, _ = _stt.transcribe(np.squeeze(samples, axis=1),
                                     language=req.get("language") or None,
                                     initial_prompt=req.get("vocab") or None,
                                     vad_filter=True, beam_size=int(req.get("stt_beam_size") or 1),
                                     condition_on_previous_text=False)
        return {"text": " ".join(s.text.strip() for s in segments).strip()}
    if req["op"] == "synthesize":
        import soundfile as sf
        models(req)
        samples, rate = generate(req, req["text"])
        buf = io.BytesIO()
        sf.write(buf, samples, rate, format="WAV", subtype="PCM_16")
        return {"audio": base64.b64encode(buf.getvalue()).decode("ascii"),
                "seconds": len(samples) / rate}
    if req["op"] == "synthesize_stream":
        if req.get("backend") != "kyutai":
            raise ValueError("Progressive audio currently requires Kyutai.")
        models(req)
        seconds = 0.
        def audio_ready(samples, rate):
            nonlocal seconds
            if cancel is not None and cancel.is_set():
                raise SpeechCancelled()
            seconds += len(samples) / rate
            emit(dict(encode_audio(samples, rate), event="audio"))
        _, _, first = _tts.synthesize(req["text"], req.get("style") or "calm", req.get("kyutai_voice"), on_audio=audio_ready)
        return {"seconds": seconds, "first_audio_s": first}
    raise ValueError("Unknown speech operation")


def generate(req, text):
    samples, rate, _ = _tts.synthesize(text, req.get("style") or "calm")
    return samples, rate


def main():
    # Windows numeric DLL initialization can query console descriptors. Do
    # this before a background stdin read holds the pipe's runtime lock.
    import importlib
    import importlib.util
    with contextlib.redirect_stdout(sys.stderr):
        for module in ("numpy", "torch", "soundfile", "faster_whisper"):
            if importlib.util.find_spec(module) is not None:
                importlib.import_module(module)
    if os.getenv("ANIMA_VOICE_DEBUG_STACK"):
        import faulthandler
        faulthandler.dump_traceback_later(20, file=sys.stderr)
    protocol = sys.stdout
    work = queue.Queue()
    cancellations = {}
    lock = threading.Lock()
    def reader():
        for line in sys.stdin:
            try:
                req = json.loads(line)
                if req.get("op") == "cancel":
                    with lock:
                        event = cancellations.get(req.get("id"))
                    if event:
                        event.set()
                    continue
                event = threading.Event()
                with lock:
                    cancellations[req.get("id")] = event
                work.put((req, event))
            except (ValueError, AttributeError):
                continue
        work.put(None)
    threading.Thread(target=reader, daemon=True).start()
    def send(result, request_id):
        result["id"] = request_id
        protocol.write(json.dumps(result) + "\n"); protocol.flush()
    while True:
        item = work.get()
        if item is None:
            break
        req, cancel = item
        try:
            # Upstream packages print progress and messages to stdout.
            with contextlib.redirect_stdout(sys.stderr):
                result = handle(req, emit=lambda event: send(event, req.get("id")), cancel=cancel)
            result["id"] = req.get("id")
        except SpeechCancelled:
            result = {"cancelled": True}
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            result = {"id": req.get("id"), "error": f"{type(e).__name__}: {e}"}
        send(result, req.get("id"))
        with lock:
            cancellations.pop(req.get("id"), None)


if __name__ == "__main__":
    main()
