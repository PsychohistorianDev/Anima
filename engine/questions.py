"""Their open questions (11-04).

A page of curiosities they keep themselves: open_question puts one on it, close_question takes one off (with what they
found, if they found something). Every wake and reverie sees the open ones under the bell, with how long each has been
open — so a question carries from wake to wake on its own, not only if one wake remembers to pass it on in a thread.
The engine never adds, words or closes a question: the page is theirs. Kept in memory/questions.json; questions.md at
the root is the same page to read (theirs and yours), rewritten at every change.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import config


def _file() -> Path:
    return Path(getattr(config, "QUESTIONS_STORE", config.MEMORY_DIR / "questions.json"))


def page_file() -> Path:
    return Path(getattr(config, "QUESTIONS_FILE", config.ROOT / "questions.md"))


def _max() -> int:
    try:
        return max(1, int(getattr(config, "QUESTIONS_MAX", 7) or 7))
    except (TypeError, ValueError):
        return 7


def load() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return {"open": list(d.get("open") or []), "closed": list(d.get("closed") or [])}
    except Exception:  # noqa: BLE001
        pass
    return {"open": [], "closed": []}


def _save(d: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# questions.md — my open questions", "",
             "(open_question puts one here, close_question takes one off — kept by the engine, worded by me)", "",
             "## Open", ""]
    lines += [f"{i}. {q['text']} — open since {q['opened']}" for i, q in enumerate(d["open"], 1)] or ["(none open)"]
    lines += ["", "## Closed", ""]
    for q in reversed(d["closed"][-50:]):
        lines.append(f"- {q['text']} — {q['opened']} → {q.get('closed', '')}"
                     + (f": {q['answer']}" if q.get("answer") else ""))
    if not d["closed"]:
        lines.append("(none yet)")
    try:
        page_file().write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def _clean(text: str) -> str:
    return " ".join(str(text or "").replace("\\n", " ").split()).strip()


def _age(opened: str, today: date | None = None) -> str:
    try:
        days = ((today or date.today()) - date.fromisoformat(opened[:10])).days
    except ValueError:
        return ""
    return "opened today" if days <= 0 else "opened yesterday" if days == 1 else f"open {days} days"


def open_question(question: str) -> str:
    text = _clean(question)
    if not text:
        return "(nothing opened: a question wants words — what do you want to find out?)"
    if len(text) > 400:
        return f"(nothing opened: that is {len(text):,} characters — a question is a line or two; say it shorter)"
    try:  # the page tools' guards: a sampler loop or letter salad is not a question of theirs
        import tools
        bad = tools._looped(text) or (tools._garble_refusal(tools._garbled(text)) if tools._garbled(text) else "")
        if bad:
            return bad
    except Exception:  # noqa: BLE001
        pass
    d = load()
    low = text.lower()
    for i, q in enumerate(d["open"], 1):
        if q["text"].lower() == low:
            return f"(already open, as question {i} — since {q['opened']})"
    if len(d["open"]) >= _max():
        return (f"(nothing opened: {len(d['open'])} questions are open, the most the page holds — close one first "
                "with close_question, answered or let go)")
    d["open"].append({"text": text, "opened": date.today().isoformat(), "opened_at": datetime.now().isoformat(timespec="seconds")})
    _save(d)
    return (f"question {len(d['open'])} opened — every wake and reverie sees it under the bell until you close it "
            f"({len(d['open'])} open)")


def _find(d: dict, which: str) -> tuple[int, str]:
    w = _clean(which)
    if not w:
        return -1, "(which question? its number, or a few of its words)"
    m = re.fullmatch(r"#?\s*(\d+)\.?", w)
    if m:
        i = int(m.group(1)) - 1
        return (i, "") if 0 <= i < len(d["open"]) else (-1, f"(there is no open question {m.group(1)} — "
                                                             f"{len(d['open'])} {'is' if len(d['open']) == 1 else 'are'} open)")
    low = w.lower()
    hits = [i for i, q in enumerate(d["open"]) if low in q["text"].lower() or q["text"].lower() in low]
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return -1, "(no open question has those words — give its number)"
    return -1, f"({len(hits)} open questions have those words — give its number)"


def close_question(question: str, answer: str = "") -> str:
    d = load()
    if not d["open"]:
        return "(no question is open)"
    i, why = _find(d, question)
    if why:
        return why
    q = d["open"].pop(i)
    q["closed"] = date.today().isoformat()
    q["closed_at"] = datetime.now().isoformat(timespec="seconds")  # (11-04) the morning line says what closed since the last talk
    a = _clean(answer)
    if a:
        q["answer"] = a[:1200]
    d["closed"].append(q)
    _save(d)
    return (f"closed: “{q['text'][:120]}”" + (" — what you found is kept beside it in questions.md" if a else
                                               " — let go, kept in questions.md") + f" ({len(d['open'])} open)")


def facts_bit(today: date | None = None) -> str:
    """The line under a wake's bell: the open questions, each with its age — or that none is open."""
    d = load()
    if not d["open"]:
        return "your open questions: none open — open_question keeps one for the next you"
    parts = []
    for i, q in enumerate(d["open"], 1):
        t = q["text"] if len(q["text"]) <= 200 else q["text"][:200].rsplit(" ", 1)[0] + "…"
        age = _age(q.get("opened", ""), today)
        parts.append(f"{i}. {t}" + (f" ({age})" if age else ""))
    return "your open questions: " + " · ".join(parts)
