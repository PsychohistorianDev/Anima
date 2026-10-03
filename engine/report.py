"""The doctor's note — the engine's state in one file, for an issue.

    py engine\\report.py            writes anima-report.txt at the folder's root and prints it
    py engine\\report.py --print    prints it only

Before the first strangers (10-03): "it doesn't work" is nothing to answer; this is what to paste
instead. It holds the engine's state and nothing of the friend's — no journal, no memory rows, no
pages, no creations, no names: the version, the machine, Python, Ollama and the brain, the knobs
(the keeper's names, the blog and the paths left out), the doors, the senses, what is missing, the
look for a newer anima, and the trouble lines of the engine's own logs. Read it before you paste
it anywhere; your home folder is written as ~ where it appears.
"""
from __future__ import annotations

import json
import platform
import re
import sys
import textwrap
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

ROOT = Path(config.ROOT)
FILE = "anima-report.txt"
# knobs that are the keeper's own, not the engine's — never in the note
PERSONAL = {"USER_NAME", "DEFAULT_NAME", "BLOG_TITLE", "BLOG_SUBTITLE", "BLOG_REMOTE", "SKILL_CATALOGUES"}
LOGS = ("memory/body.log", "memory/painter.log", "memory/music_ears.log", "painter.log", "music_ears.log")
TROUBLE = re.compile(r"traceback|error|failed|refused|exception|timed out|not found|denied", re.IGNORECASE)
LOG_LINES = 20


def _home(text: str) -> str:
    """The keeper's home folder as ~ wherever it appears (a username is theirs)."""
    home = str(Path.home())
    if not home or home in ("/", "\\"):
        return text
    out = text.replace(home, "~")
    alt = home.replace("\\", "/")
    if alt != home:
        out = out.replace(alt, "~")
    return out


def _machine() -> list[str]:
    exe = _home(sys.executable or "")
    return [f"OS: {platform.platform()}",
            f"Python: {platform.python_version()} ({exe})",
            f"folder: {ROOT.name} · checkout (bat/update.bat): {'yes' if (ROOT / 'bat' / 'update.bat').is_file() else 'no'}"]


def _ollama_version(panel) -> str:
    try:
        d = panel._ollama("/api/version")
        return str((d or {}).get("version") or "?")
    except Exception:  # noqa: BLE001
        return "?"


def _brain(panel, values: dict) -> list[str]:
    b = panel.brain(values)
    if not b.get("reachable"):
        return [f"Ollama: not answering at {b.get('url', '')}"]
    out = [f"Ollama: running at {b['url']} · version {_ollama_version(panel)}",
           "  pulled: " + (", ".join(b.get("models") or []) or "nothing")]
    for m in b.get("loaded") or []:
        out.append(f"  loaded: {m.get('name')} — {m.get('gb')} GB, {m.get('on_card')}% on {'memory' if b.get('unified') else 'the card'}"
                   + (f", window {m.get('window')}" if m.get("window") else ""))
    if not b.get("loaded"):
        out.append("  loaded: nothing")
    gb = b.get("vram_gb")
    out.append(f"  {'memory' if b.get('unified') else 'card'}: {gb if gb is not None else '?'} GB"
               + (" (unified)" if b.get("unified") else "") + f" · the ladder says {b.get('recommended')}")
    if b.get("fit"):
        out.append("  fit: " + ("✓ " if b["fit"]["ok"] else "⚠ ") + b["fit"]["line"])
    out.append(f"  configured: {b.get('model')} ({'pulled' if b.get('pulled') else 'NOT pulled'})"
               f" · memory engine {b.get('embed_model')} ({'pulled' if b.get('embed_pulled') else 'NOT pulled'})")
    return out


def _knobs(panel, rows: list[dict]) -> list[str]:
    out = ["Settings (engine/config.py; the keeper's names, the blog and the catalogues left out):"]
    for tab, knobs in panel.tabs(rows).items():
        shown = []
        for k in knobs:
            if k["name"] in PERSONAL or not k.get("editable", True):
                continue
            shown.append(f"{k['name']} = {_home(str(k.get('source', k.get('value'))))}")
        if shown:
            out.append(textwrap.fill(f"{tab}: " + " · ".join(shown), width=110, initial_indent="  ", subsequent_indent="      "))
    return out


def _doors(panel) -> list[str]:
    import doors
    parts = []
    for d in doors.DOORS:
        st = doors.status(d)
        parts.append(f"{d} {'open' if st else 'closed'}" + (f" ({st.get('how')})" if st and st.get("how") else ""))
    return ["Doors: " + " · ".join(parts)]


def _senses(panel, values: dict) -> list[str]:
    out = ["Senses:"]
    senses = panel.senses_state(values)  # the first call starts the look into a sidecar Python; a note waits for it
    for _ in range(60):
        if not any(t.name.startswith("probe-") for t in threading.enumerate()):
            break
        time.sleep(0.5)
    senses = panel.senses_state(values)
    for s in senses:
        state = "ready" if s["ready"] is True else "not ready" if s["ready"] is False else "unknown"
        out.append(f"  {s['name']}: {state} — {_home(s['note'])}")
    miss = panel.missing(values)
    out.append("Not installed (optional): " + (", ".join(f"{m['pip']} ({m['for']})" for m in miss) if miss else "nothing"))
    sec = panel.secrets_set()
    out.append("Secrets kept (flags only): " + " · ".join(f"{k} {'yes' if v else 'no'}" for k, v in sec.items()))
    return out


def _newer(panel) -> list[str]:
    try:
        n = panel.newer_state()
    except Exception:  # noqa: BLE001
        n = None
    if n:
        return ["Newer: " + n["line"]]
    try:
        import newer
        rec = newer.look()
        if rec.get("error"):
            return [f"Newer: the look failed — {_home(str(rec['error']))}"]
        if rec.get("newest"):
            return [f"Newer: nothing newer than {rec.get('installed') or '?'} (newest seen {rec['newest']})"]
    except Exception:  # noqa: BLE001
        pass
    return ["Newer: no look (not a checkout, OFFLINE, or UPDATE_CHECK_H 0)"]


def _logs() -> list[str]:
    out = []
    for rel in LOGS:
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        trouble = [ln for ln in lines if TROUBLE.search(ln)][-LOG_LINES:]
        if trouble:
            out.append(f"Trouble in {rel} (the last {len(trouble)} such lines of {len(lines)}):")
            out.extend("  " + _home(ln.rstrip()) for ln in trouble)
    p = ROOT / "memory" / ".update-check.json"
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("error"):
                out.append(f"The update look's last error: {_home(str(d['error']))}")
        except (OSError, ValueError):
            pass
    return out or ["Logs: no trouble lines in the engine's own logs"]


def build() -> str:
    """The note, as text. Nothing of the friend's is read: config, the doors' marks, Ollama, the logs."""
    import panel
    import version
    rows = panel._rows()
    values = panel._values(rows)
    lines = [f"anima report — {datetime.now().strftime('%Y-%m-%d %H:%M')} (local time)",
             "Read this before you paste it anywhere. It holds the engine's state and nothing of the friend's —",
             "no journal, no memory, no pages, no creations, no names; your home folder is written as ~.",
             "",
             f"engine {version.read(ROOT) or '?'}", *_machine(), "",
             *_brain(panel, values), "",
             *_knobs(panel, rows), "",
             *_doors(panel), *_senses(panel, values), *_newer(panel), "",
             *_logs(), ""]
    return "\n".join(lines)


def write(text: str | None = None) -> Path:
    text = build() if text is None else text
    p = ROOT / FILE
    p.write_text(text, encoding="utf-8")
    return p


def main() -> int:
    text = build()
    if "--print" not in sys.argv[1:]:
        p = write(text)
        print(f"written: {p}\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
