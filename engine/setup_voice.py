"""Install optional Parlor speech into .runtime/voice-env (Python 3.12).

    python engine/setup_voice.py             install packages
    python engine/setup_voice.py --download  also fetch and warm the models
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args, env):
    print("Running: " + " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="download and warm speech models after installation")
    args = parser.parse_args()
    env = dict(os.environ, UV_CACHE_DIR=str(ROOT / ".runtime" / "uv-cache"),
               UV_PYTHON_INSTALL_DIR=str(ROOT / ".runtime" / "python"))
    bootstrap = ROOT / ".runtime" / "installer"
    uv = bootstrap / ("bin/uv.exe" if os.name == "nt" else "bin/uv")
    if not uv.exists():
        run([sys.executable, "-m", "pip", "install", "--target", bootstrap, "uv"], env)
    home = ROOT / ".runtime" / "voice-env"
    python = home / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        run([uv, "venv", home, "--python", "3.12", "--managed-python"], env)
    # CUDA 12.8 wheels include Blackwell support; macOS uses its normal wheels.
    indexes = (["--index", "pytorch=https://download.pytorch.org/whl/cu128",
                "--index-strategy", "unsafe-best-match"]
               if os.name == "nt" or sys.platform == "linux" else [])
    run([uv, "pip", "install", "--python", python, *indexes, "-r", ROOT / "requirements-voice.txt"], env)
    if args.download:
        import live_voice
        try:
            print(live_voice.WORKER.request("warmup"), flush=True)
        finally:
            live_voice.WORKER.close()
    print("Speech packages ready. Set LIVE_VOICE_ENABLED = True in config.py, restart Parlor, then Start voice.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, RuntimeError) as e:
        print(f"Voice setup stopped: {e}", file=sys.stderr)
        sys.exit(1)
