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
    if slot_dir:
        cmd += ["--slot-save-path", slot_dir]
    return cmd, f"llama-server at {server}; {said}" + ("" if mmproj else " (no projector: no eyes)")


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
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
