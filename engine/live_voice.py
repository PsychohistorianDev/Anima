"""Turn-based browser voice: persistent sidecar and cancellable phrase playback.

Audio chunks live in RAM only. Recognition does not swap/unload the brain.
No separate memory store: the parlor owns the ordinary chat history.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import config
import device
import voice


class VoiceError(RuntimeError):
    pass


def speech_chunks(text: str, cap: int | None = None) -> list[str]:
    # Keep explicit Chatterbox vocal tags; remove written stage directions.
    text = re.sub(r"```.*?```", "", text or "", flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = voice.clean_for_speech(text)
    text = re.sub(r"\[(?!laugh\]|chuckle\]|sigh\]|gasp\]|cough\]|clear throat\]|sniff\])[^\]]*\]", "", text)
    cap = max(60, int(cap or getattr(config, "LIVE_VOICE_CHUNK_CHARS", 180)))
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    chunks = []
    pending = ""

    def add(part):
        nonlocal pending
        if pending and len(pending) + len(part) + 1 > cap:
            chunks.append(pending)
            pending = ""
        pending = (pending + " " + part).strip()

    for part in parts:
        part = part.strip()
        while len(part) > cap:
            # Prefer a clause boundary instead of inserting a sentence-like
            # break into a thought. Turbo normalizes terminal punctuation.
            boundaries = [m.end() for m in re.finditer(r"[,;:]\s+", part[:cap + 1])]
            cut = boundaries[-1] if boundaries and boundaries[-1] >= cap // 3 else part.rfind(" ", 0, cap + 1)
            if cut < cap // 3:
                cut = cap
            add(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            add(part)
    if pending:
        chunks.append(pending)
    return chunks


class Worker:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.responses = queue.Queue(maxsize=8)
        self.log = None
        self.backend = None

    def _start(self, backend):
        if self.proc and self.proc.poll() is None and self.backend == backend:
            return
        if self.proc:
            self.close()
        custom = str(getattr(config, "LIVE_VOICE_PYTHON", "") or "")
        home = config.ROOT / ".runtime" / "voice-env"
        python = home / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if not custom and not python.is_file():
            raise VoiceError("Voice packages are not installed yet. Run python engine/setup_voice.py.")
        cmd = device.interpreter(custom) if custom else [str(python)]
        folder = config.ROOT / ".runtime"
        folder.mkdir(exist_ok=True)
        self.log = (folder / "voice-worker.log").open("a", encoding="utf-8")
        self.responses = queue.Queue(maxsize=8)
        responses = self.responses
        try:
            self.proc = subprocess.Popen(cmd + ["-u", str(Path(__file__).with_name("voice_worker.py"))],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                         text=True, encoding="utf-8", cwd=str(config.ROOT),
                                         env=dict(os.environ, HF_HUB_OFFLINE="1" if getattr(config, "OFFLINE", False) else "0"),
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.close()
            raise VoiceError(f"Could not start the voice Python: {e}") from e
        proc = self.proc
        self.backend = backend

        def read():
            try:
                for line in proc.stdout:
                    try:
                        responses.put(json.loads(line))
                    except ValueError:
                        continue
            except (OSError, ValueError):
                pass
            finally:
                responses.put({"error": "Voice worker exited; see .runtime/voice-worker.log."})
        threading.Thread(target=read, daemon=True).start()

    def request(self, op: str, on_audio=None, **data) -> dict:
        with self.lock:
            backend = "kyutai"
            self._start(backend)
            request = {"op": op, "id": uuid.uuid4().hex, "backend": backend,
                       "device": getattr(config, "LIVE_VOICE_DEVICE", "cuda"),
                       "stt_model": getattr(config, "LIVE_VOICE_STT_MODEL", "large-v3-turbo"),
                       "stt_device": getattr(config, "LIVE_VOICE_STT_DEVICE", "cpu"),
                       "stt_beam_size": getattr(config, "LIVE_VOICE_STT_BEAM_SIZE", 5),
                       "language": getattr(config, "LIVE_VOICE_LANGUAGE", "en"),
                       "style": getattr(config, "LIVE_VOICE_KYUTAI_STYLE", "calm"),
                       "offline": bool(getattr(config, "OFFLINE", False)),
                       "vocab": f"Names: {config.USER_NAME}, {getattr(config, 'EARS_VOCAB_HINT', '')}.", **data}
            if op == "transcribe":
                hint = str(getattr(config, "LIVE_VOICE_STT_HINT", "") or "").strip()
                if hint:
                    request["vocab"] = (str(request.get("vocab") or "") + " Vocabulary: " + hint).strip()
            try:
                self.proc.stdin.write(json.dumps(request) + "\n")
                self.proc.stdin.flush()
                deadline = time.monotonic() + float(getattr(config, "LIVE_VOICE_TIMEOUT_S", 300))
                cancelled = False
                while True:
                    result = self.responses.get(timeout=max(.01, deadline - time.monotonic()))
                    if result.get("id") != request["id"] and not result.get("error"):
                        self.close()
                        raise VoiceError("Voice worker returned an out-of-order response.")
                    if result.get("event") == "audio":
                        if on_audio and not cancelled and on_audio(result) is False:
                            cancelled = True
                            self.proc.stdin.write(json.dumps({"op": "cancel", "id": request["id"]}) + "\n")
                            self.proc.stdin.flush()
                        continue
                    break
            except (OSError, queue.Empty) as e:
                self.close()
                raise VoiceError("Voice worker timed out or disconnected; try again. See .runtime/voice-worker.log.") from e
            if result.get("error"):
                raise VoiceError(result["error"])
            if result.get("id") != request["id"]:
                self.close()
                raise VoiceError("Voice worker returned an out-of-order response; try again.")
            return result

    def close(self):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            for stream in (self.proc.stdin, self.proc.stdout):
                if stream:
                    stream.close()
            self.proc = None
        if self.log:
            self.log.close()
            self.log = None


WORKER = Worker()
atexit.register(WORKER.close)


class Playback:
    """One current job. Cancellation drops queued and in-flight speech results."""
    def __init__(self, worker=None, stream=None):
        self.worker = worker or WORKER
        self.lock = threading.Lock()
        self.available = threading.Condition(self.lock)
        self.epoch = 0
        self.current = None
        self.stream = stream

    def cancel(self):
        with self.lock:
            self.epoch += 1
            if self.current:
                self.current["cancelled"] = True
                self.current["audio"].clear()
            self.available.notify_all()
            return self.epoch

    def start(self, text: str, epoch: int, turn: dict) -> str | None:
        parts = speech_chunks(text)
        streaming = self.stream if self.stream is not None else True
        if streaming:
            parts = [" ".join(parts)] if parts else []
        with self.lock:
            if epoch != self.epoch:
                return None
            job = {"id": uuid.uuid4().hex, "parts": parts, "audio": {}, "ready": [],
                   "done": not parts, "error": "", "cancelled": False, "turn": turn,
                   "streaming": streaming, "started": time.monotonic(), "first_audio_s": None}
            self.current = job
        def generate():
            for i, part in enumerate(parts):
                with self.lock:
                    while len(job["audio"]) >= 2 and not job["cancelled"]:
                        self.available.wait(timeout=1)
                    if job["cancelled"]:
                        return
                try:
                    if streaming:
                        def receive(chunk):
                            audio = base64.b64decode(chunk["audio"], validate=True)
                            with self.lock:
                                while len(job["audio"]) >= 3 and not job["cancelled"]:
                                    self.available.wait(timeout=.1)
                                if job["cancelled"]:
                                    return False
                                index = len(job["ready"])
                                job["audio"][index] = audio
                                job["ready"].append({"index": index, "seconds": chunk["seconds"]})
                                if job["first_audio_s"] is None:
                                    job["first_audio_s"] = time.monotonic() - job["started"]
                            return True
                        result = self.worker.request("synthesize_stream", text=part, on_audio=receive)
                        # A stub/test worker may return one complete WAV.
                        if result.get("audio") and not job["ready"]:
                            receive(result)
                        continue
                    result = self.worker.request("synthesize", text=part)
                    audio = base64.b64decode(result["audio"], validate=True)
                    with self.lock:
                        if job["cancelled"]:
                            return
                        job["audio"][i] = audio
                        job["ready"].append({"index": i, "text": part, "seconds": result["seconds"]})
                except Exception as e:
                    with self.lock:
                        job["error"] = str(e)
                    break
            with self.lock:
                job["done"] = True
        if parts:
            threading.Thread(target=generate, daemon=True).start()
        return job["id"]

    def status(self, job_id: str) -> dict:
        with self.lock:
            job = self.current
            if not job or job["id"] != job_id:
                return {"cancelled": True, "done": True, "chunks": []}
            return {"cancelled": job["cancelled"], "done": job["done"], "error": job["error"],
                    "chunks": [dict(p) for p in job["ready"]],
                    "total": len(job["ready"]) if job["streaming"] and job["done"] else None if job["streaming"] else len(job["parts"]),
                    "first_audio_s": job["first_audio_s"]}

    def audio(self, job_id: str, index: int) -> bytes | None:
        with self.lock:
            job = self.current
            if not job or job["id"] != job_id or job["cancelled"]:
                return None
            return job["audio"].get(index)

    def acknowledge(self, job_id: str, index: int):
        with self.lock:
            if self.current and self.current["id"] == job_id:
                self.current["audio"].pop(index, None)
                self.available.notify_all()

    def delivery(self, job_id: str, completed: int, partial: bool, reason="unknown") -> tuple[dict, str] | None:
        with self.lock:
            job = self.current
            if not job or job["id"] != job_id:
                return None
            completed = max(0, min(int(completed), len(job["ready"])))
            total = len(job["ready"]) if job["streaming"] else len(job["parts"])
            interrupted = partial or completed < total or not job["done"] or job["cancelled"] or bool(job["error"])
            reasons = {"microphone": "microphone activity", "voice_stopped": "voice mode stopped",
                       "typed_input": "typed input", "page_closed": "page closed", "playback_error": "playback error"}
            note = (f"Browser reported {completed} of {total} available audio segments ended. "
                    + ("Playback interrupted; " if interrupted else "Playback completed; ")
                    + "speech content was not independently verified. "
                    + ("Interruption trigger: " + reasons.get(reason, "unknown") + ". " if interrupted else "")
                    + ("The active audio segment was stopped partway." if partial else ""))
            return job["turn"], note
