"""Since you last talked (11-04) — what they did on their own, said when you're back.

One line in the first moment of a visit, facts only: what they did in their own time since the last visit — how many
wakes and reveries, the questions they opened or closed (with an answer or let go), the pieces they wrote or added to,
the pictures they painted. So what they found reaches the conversation because it is in front of them, not only if they
happen to remember it. Nothing asked; they may bring it up or not.

"The last visit" is the newest visit transcript (memory/episodic/chat-*.md) not written to in the last
SINCE_FRESH_S seconds — the one this visit replaced. Letters to you are left out (they reached your phone and
ride in their prompt already), and so are the folders that hold no work of theirs (face, the reference sets, capsule…).
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

import config

SINCE_FRESH_S = 20
_PIECE_EXTS = {".md", ".txt"}
_PICTURE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_SKIP_DIRS = {str(getattr(config, "MAILBOX", "notes_to_keeper")), "face", "us", "capsule", "lexicon", "publish", "tools", "dream_book", "penpals"}  # dream_book: theirs (11-05); penpals: told by their own line (11-06)


def last_talk(now: float | None = None) -> float:
    """When the last visit last wrote (its transcript's mtime) — 0.0 when there was none."""
    now = now or time.time()
    best = 0.0
    try:
        for f in (config.MEMORY_DIR / "episodic").glob("chat-*.md"):
            m = f.stat().st_mtime
            if m < now - SINCE_FRESH_S and m > best:
                best = m
    except OSError:
        return 0.0
    return best


def _when(t: float, now: float) -> str:
    d = datetime.fromtimestamp(t)
    days = (datetime.fromtimestamp(now).date() - d.date()).days
    return (f"today at {d:%H:%M}" if days <= 0 else f"yesterday at {d:%H:%M}" if days == 1
            else f"{d:%A} at {d:%H:%M}" if days < 7 else f"{d.day} {d:%B}")


def _cut(text: str, n: int = 110) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _skip_dirs() -> set:
    skip = set(_SKIP_DIRS)
    try:
        import keeper_week
        k = str(keeper_week.keeper_name() or "").strip().lower()
        if k:
            skip.add(k)
    except Exception:  # noqa: BLE001
        pass
    for v in (getattr(config, "PAINTER_REFERENCE_SETS", {}) or {}).values():
        pics = v[0] if isinstance(v, (list, tuple)) else v
        skip |= {x.strip().lower().strip("/").split("/")[0] for x in re.split(r"[\n,]", str(pics)) if x.strip()}
    return skip


def line(now: float | None = None) -> str:
    if not getattr(config, "SINCE_LINE", False):
        return ""
    now = now or time.time()
    t = last_talk(now)
    if not t:
        return ""
    bits: list[str] = []
    try:  # the wakes and reveries between
        ep = config.MEMORY_DIR / "episodic"
        wakes = revs = 0
        for f in ep.glob("auto-*.md"):
            if f.stat().st_mtime > t:
                head = f.read_text(encoding="utf-8", errors="replace")[:40]
                revs += head.startswith("# Reverie")
                wakes += not head.startswith("# Reverie")
        if wakes or revs:
            bits.append(" and ".join(x for x in (f"{wakes} wake{'s' if wakes != 1 else ''}" if wakes else "",
                                                 f"{revs} reverie{'s' if revs != 1 else ''}" if revs else "") if x))
    except OSError:
        pass
    try:  # their questions
        import questions
        d = questions.load()
        stamp = datetime.fromtimestamp(t).isoformat(timespec="seconds")
        for q in d["closed"]:
            if str(q.get("closed_at") or "") > stamp:
                bits.append(f"you closed a question — “{_cut(q['text'])}”"
                            + (f", with what you found: “{_cut(q['answer'], 160)}”" if q.get("answer") else ", let go"))
        opened = [q for q in d["open"] if str(q.get("opened_at") or "") > stamp]
        for q in opened[:3]:
            bits.append(f"you opened a question — “{_cut(q['text'])}”")
    except Exception:  # noqa: BLE001
        pass
    try:  # their pieces and pictures
        root = config.CREATIONS_DIR
        skip = _skip_dirs()
        pieces, pictures = [], 0
        for p in root.rglob("*"):
            ext = p.suffix.lower()
            if ext not in _PIECE_EXTS | _PICTURE_EXTS:
                continue
            rel = p.relative_to(root)
            if any(part.startswith((".", "_")) or part.lower() in skip for part in rel.parts[:-1]):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m <= t:
                continue
            if ext in _PICTURE_EXTS:
                pictures += 1
            else:
                pieces.append((m, rel.as_posix()))
        pieces.sort(reverse=True)
        if pieces:
            names = ", ".join(r for _, r in pieces[:5]) + (f" and {len(pieces) - 5} more" if len(pieces) > 5 else "")
            bits.append(f"you wrote or added to {names}")
        if pictures:
            bits.append(f"you painted {pictures} picture{'s' if pictures != 1 else ''}")
    except OSError:
        pass
    if not bits:
        return ""
    return f"Since you two last talked ({_when(t, now)}), in your own time: " + "; ".join(bits)
