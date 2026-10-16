"""Find what the brain's door needs, and start it. Standard library only.

    py engine\\brain_find.py          prints the llama-server command it would run
    py engine\\brain_find.py --run    prints it, then runs it (bat\\brain.bat)

Nothing is hardcoded; things are found in the order a stranger expects. The
program: the PATH first (what an installer gives), then a llama\\ folder beside
the engine (the zip from llama.cpp's releases page). The model: Ollama's own
manifest for CHAT_MODEL — under OLLAMA_MODELS when that is set, else
~/.ollama/models — whose model and projector layers name the blobs Ollama
already has on disk, so nothing is downloaded twice. BRAIN_MODEL_FILE and
BRAIN_MMPROJ_FILE are for a GGUF from elsewhere.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

MODEL_LAYER = "application/vnd.ollama.image.model"
PROJECTOR_LAYER = "application/vnd.ollama.image.projector"


def find_server() -> str | None:
    """llama-server on the PATH, else in llama\\ beside the engine; None when neither."""
    found = shutil.which("llama-server")
    if found:
        return found
    for name in ("llama-server.exe", "llama-server"):
        p = ROOT / "llama" / name
        if p.is_file():
            return str(p)
    return None


def models_dir() -> Path:
    env = os.environ.get("OLLAMA_MODELS", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".ollama" / "models"


def manifest_path(model_tag: str) -> Path:
    """name:tag as Ollama files it: a bare name is library/<name> on registry.ollama.ai,
    one slash a user's namespace there, a host in front its own registry."""
    name, tag = model_tag, "latest"
    if ":" in model_tag.rsplit("/", 1)[-1]:
        name, tag = model_tag.rsplit(":", 1)
    parts = [p for p in name.split("/") if p]
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library"] + parts
    elif len(parts) == 2:
        parts = ["registry.ollama.ai"] + parts
    return models_dir().joinpath("manifests", *parts, tag)


def _blob(digest: str) -> Path:
    return models_dir() / "blobs" / digest.replace(":", "-")


def find_blobs(model_tag: str) -> tuple[str, str | None] | None:
    """(model blob, projector blob or None) from Ollama's manifest; None when the manifest
    or the model blob isn't there."""
    try:
        layers = json.loads(manifest_path(model_tag).read_text(encoding="utf-8")).get("layers") or []
    except (OSError, ValueError, AttributeError):
        return None
    model = next((l.get("digest") for l in layers if l.get("mediaType") == MODEL_LAYER), None)
    proj = next((l.get("digest") for l in layers if l.get("mediaType") == PROJECTOR_LAYER), None)
    if not model or not _blob(model).is_file():
        return None
    return str(_blob(model)), (str(_blob(proj)) if proj and _blob(proj).is_file() else None)


def slot_warning() -> str:
    """A word when BRAIN_SLOT_DIR names a folder that isn't there (a RAM disk is gone after a reboot until
    it is made again): the door then opens without --slot-save-path and saves nothing. "" otherwise."""
    import config

    slot_dir = str(getattr(config, "BRAIN_SLOT_DIR", "") or "")
    if slot_dir and not Path(slot_dir).is_dir():
        return (f"the slot folder {slot_dir} isn't there — the RAM disk didn't come back after the reboot? "
                "the brain saves nothing this time")
    return ""


def ensure_slot_dir() -> str:
    """BRAIN_SLOT_DIR made when its drive is there and the folder is not (R:\\ back after a reboot, R:\\kv not
    made yet): the last folder only, never the drive or the way to it — a drive that isn't there stays
    slot_warning's word. "" when nothing was made, else a word on it."""
    import config

    d = str(getattr(config, "BRAIN_SLOT_DIR", "") or "").strip()
    if not d:
        return ""
    p = Path(d)
    if p.is_dir() or not p.is_absolute() or p.parent == p or not p.parent.is_dir():
        return ""
    try:
        p.mkdir()
    except OSError:
        return ""
    return f"made the slot folder {d}"


def command() -> tuple[list[str] | None, str]:
    """The command line for the door, and a word on what was found (or what is missing)."""
    import config

    server = find_server()
    if not server:
        return None, ("llama-server not found — put it on the PATH, or unzip llama.cpp's release "
                      f"into {ROOT / 'llama'}")
    model = str(getattr(config, "BRAIN_MODEL_FILE", "") or "")
    mmproj = str(getattr(config, "BRAIN_MMPROJ_FILE", "") or "")
    said = "the model from BRAIN_MODEL_FILE"
    if not model:
        found = find_blobs(config.CHAT_MODEL)
        if not found:
            return None, (f"no Ollama manifest for {config.CHAT_MODEL} under {models_dir()} — "
                          f"`ollama pull {config.CHAT_MODEL}`, or set BRAIN_MODEL_FILE to a GGUF")
        model = found[0]
        mmproj = mmproj or (found[1] or "")
        said = f"the model from Ollama's manifest for {config.CHAT_MODEL}"
    port = urlparse(str(getattr(config, "BRAIN_URL", "") or "http://127.0.0.1:8768")).port or 8768
    cmd = [server, "-m", model]
    if mmproj:
        cmd += ["--mmproj", mmproj]
    cmd += ["-c", str(int(getattr(config, "NUM_CTX", 8192))), "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0",
            "-np", "1", "--reasoning-format", "deepseek", "--port", str(port), "--host", "127.0.0.1"]
    slot_dir = str(getattr(config, "BRAIN_SLOT_DIR", "") or "")
    made = ensure_slot_dir()
    warn = slot_warning()
    if slot_dir and not warn:  # a folder that isn't there would stop the server at its start: left out, and said
        cmd += ["--slot-save-path", slot_dir]
    # host RAM for the prompt caches a slot lets go (the visit's and a wake's take turns on the one slot): with
    # room, both stay warm. 0 is the server's own default — the flag left out (0 passed would turn it off)
    cram = int(getattr(config, "BRAIN_CACHE_RAM_MB", 0) or 0)
    if cram > 0:
        cmd += ["--cache-ram", str(cram)]
    return cmd, (f"llama-server at {server}; {said}" + ("" if mmproj else " (no projector: no eyes)")
                 + (f"; {made}" if made else "")
                 + (f"; {warn} (opened without --slot-save-path)" if warn else ""))


def _shown(cmd: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(cmd)
    import shlex
    return shlex.join(cmd)


def main(argv: list[str]) -> int:
    cmd, said = command()
    if cmd is None:
        print(said)
        return 1
    print(said)
    print(_shown(cmd))
    if "--run" not in argv:
        return 0
    # A door opened by hand is still the house's door: marked with the server's own pid, so the panel lights
    # its tile and its Stop — and the painter, the ears, /release — can close it; unmarked on the way out.
    import brain
    import doors

    try:
        proc = subprocess.Popen(cmd)
    except OSError as e:
        print(f"(couldn't start llama-server: {e})")
        return 1
    doors.mark(brain.DOOR, "bat\\brain.bat", pid=proc.pid, port=brain.port(), image=brain.IMAGE)
    try:
        return proc.wait()
    except KeyboardInterrupt:  # Ctrl+C reached the server too (one console): its goodbye is waited for
        try:
            proc.wait(timeout=15)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.kill()
        return 0
    finally:
        doors.unmark(brain.DOOR, pid=proc.pid)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
