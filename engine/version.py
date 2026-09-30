"""The engine's version — one line in the VERSION file at the root (09-30).

The update (engine/update.py) reads it to say "0.12 → 0.13" and to know which
CHANGELOG entries are news; a CLI may print it at start. A folder installed
before the file existed has none, and reads as "".
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(root: Path | None = None) -> str:
    """The version in <root>/VERSION ("0.12"), or "" when there is no such file."""
    try:
        return (Path(root or ROOT) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
