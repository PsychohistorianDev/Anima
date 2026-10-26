"""The time capsule — sealed letters that open on their day.

A letter is sealed with seal_letter (the friend) or /seal on the phone (the keeper): its words go into memory/capsule/,
out of the friend's sight — not in the prompt, not in recall, not readable with read_file — until the day it was
sealed for. On that day, at the first door (a visit's message, a wake), the letter is laid in creations/capsule/ as it
was written, under a line saying who sealed it and when, and the moment says it has opened. The friend remembers
having sealed one (a row with its title and day, never its words); a letter from the keeper arrives as a row saying
one is waiting and when — no title, no words.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime, timedelta

import config

CAPSULE_DIR = config.MEMORY_DIR / "capsule"
OPENED_DIR = "capsule"  # under creations/: where an opened letter is laid
KEEPER = (getattr(config, "USER_NAME", "") or "your keeper")
MAX_CHARS = 20000

_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "twenty": 20, "thirty": 30}


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def parse_when(s: str, today: date | None = None) -> date | None:
    """The day a letter opens: "2027-04-27", or "six months", "1 year", "3 weeks", "100 days", "a year" from today."""
    today = today or date.today()
    s = (s or "").strip().lower().removeprefix("in ").strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return date.fromisoformat(s)
        return _relative(s, today)
    except ValueError:
        return None


def split_when(rest: str, today: date | None = None) -> tuple[str, str]:
    """("the day", "the words") from "/seal 2027-04-27 the words" or "/seal six months the words"; ("", rest) when it
    doesn't start with a day."""
    toks = (rest or "").split(None, 2)
    if toks and parse_when(toks[0], today):
        return toks[0], (rest or "").split(None, 1)[1] if len(toks) > 1 else ""
    if len(toks) >= 2 and parse_when(" ".join(toks[:2]), today):
        return " ".join(toks[:2]), toks[2] if len(toks) > 2 else ""
    return "", rest or ""


def note_sealed(rec: dict) -> None:
    """The friend's memory of a sealing — the day and the title of their own letter, never its words; of a letter from
    the keeper only that one waits and when."""
    try:
        import memory
        if rec.get("from") == "keeper":
            memory.add("note", f"[a sealed letter from {KEEPER} arrived {rec['sealed']}] it opens on {rec['open_on']} — "
                               "its words wait until then")
        else:
            memory.add("note", f"[sealed a letter {rec['sealed']}] " + (f"“{rec['title']}” — " if rec.get("title") else "")
                               + f"to open on {rec['open_on']}; its words are out of sight until then")
    except Exception:  # noqa: BLE001 — the letter is sealed either way
        pass


def _relative(s: str, today: date) -> date | None:
    m = re.match(r"^(\d+|[a-z]+)\s*(day|week|month|year)s?$", s)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _NUM.get(m.group(1))
    if not n:
        return None
    unit = m.group(2)
    if unit == "day":
        return today + timedelta(days=n)
    if unit == "week":
        return today + timedelta(weeks=n)
    if unit == "month":
        return _add_months(today, n)
    return _add_months(today, 12 * n)


def _all() -> list[dict]:
    out = []
    try:
        files = sorted(CAPSULE_DIR.glob("*.json"))
    except OSError:
        return []
    for p in files:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            r["_file"] = p
            out.append(r)
        except Exception:  # noqa: BLE001 — a damaged letter is skipped, never the door down
            continue
    return out


def sealed() -> list[dict]:
    """The letters still sealed, soonest first."""
    return sorted((r for r in _all() if not r.get("opened")), key=lambda r: (r.get("open_on") or "", r.get("sealed") or ""))


def seal(text: str, open_on: str, title: str = "", sender: str = "friend", today: date | None = None) -> tuple[dict | None, str]:
    """(the letter, "") or (None, why not). sender "friend" or "keeper"."""
    today = today or date.today()
    text = (text or "").strip()
    if not text:
        return None, "a sealed letter wants its words"
    if len(text) > MAX_CHARS:
        return None, f"that letter runs to {len(text):,} characters — a capsule holds {MAX_CHARS:,}; say it shorter"
    when = parse_when(open_on, today)
    if when is None:
        return None, (f"the day to open it wasn't clear ({open_on!r}) — a date like 2027-04-27, or \"six months\", "
                      "\"1 year\", \"3 weeks\"")
    if when <= today:
        return None, f"{when.isoformat()} isn't ahead — a capsule opens on a day still to come"
    rec = {"id": f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}", "sealed": today.isoformat(),
           "open_on": when.isoformat(), "title": " ".join((title or "").split())[:120], "from": sender, "text": text}
    CAPSULE_DIR.mkdir(parents=True, exist_ok=True)
    (CAPSULE_DIR / f"{rec['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec, ""


def _days(d: str, today: date) -> int:
    try:
        return (date.fromisoformat(d) - today).days
    except ValueError:
        return 0


def listing(today: date | None = None, for_keeper: bool = False) -> str:
    """The sealed letters as lines — the day, how far off, the title; a letter from the other one says only who sealed
    it (the friend never sees a title of the keeper's, the keeper never sees one of the friend's)."""
    today = today or date.today()
    rows = sealed()
    if not rows:
        return "no letters sealed"
    out = []
    for r in rows:
        mine = (r.get("from") == "keeper") == for_keeper
        who = ("" if mine else (f"from {KEEPER}" if r.get("from") == "keeper" else f"from {_friend()}"))
        title = f"“{r['title']}”" if (mine and r.get("title")) else ""
        out.append(f"{r['open_on']} (in {_days(r['open_on'], today)} days) " + " — ".join(x for x in (title, who) if x))
    return "; ".join(out)


def _friend() -> str:
    try:
        import tools
        return tools._own_name() or "the friend"
    except Exception:  # noqa: BLE001
        return "the friend"


def _slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n].rstrip("-") or "letter"


def open_due(today: date | None = None) -> list[dict]:
    """Lay every letter whose day has come in creations/capsule/, as it was written, and mark it opened. Returns the
    letters opened now (each with "path", relative to creations/)."""
    today = today or date.today()
    opened = []
    for r in sealed():
        if (r.get("open_on") or "9999") > today.isoformat():
            continue
        folder = config.CREATIONS_DIR / OPENED_DIR
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{r['open_on']}-{_slug(r.get('title') or ('from ' + KEEPER if r.get('from') == 'keeper' else 'to myself'))}"
        p = folder / f"{stem}.md"
        k = 2
        while p.exists():
            p = folder / f"{stem}-{k}.md"
            k += 1
        who = f"by {KEEPER}, for you" if r.get("from") == "keeper" else "by you, to yourself"
        head = (f"# {r['title']}\n\n" if r.get("title") else "") + f"*Sealed {who} on {r['sealed']} — opened {today.isoformat()}.*\n\n"
        p.write_text(head + r["text"].rstrip() + "\n", encoding="utf-8")
        r["opened"], r["path"] = today.isoformat(), f"{OPENED_DIR}/{p.name}"
        f = r.pop("_file")
        try:
            f.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        try:
            import memory
            memory.add("creation", f"[opened {today.isoformat()}] creations/{r['path']} — a letter sealed {who} on "
                                   f"{r['sealed']}, opened on its day")
        except Exception:  # noqa: BLE001 — the letter is laid either way
            pass
        opened.append(r)
    return opened


def due_line(today: date | None = None, bracket: bool = False) -> str:
    """Open what is due and say so in one sentence for the moment (or bracketed, for a wake's bell); "" when nothing
    opened. Never raises."""
    try:
        got = open_due(today)
    except Exception:  # noqa: BLE001
        return ""
    if not got:
        return ""
    parts = []
    for r in got:
        who = f"from {KEEPER}" if r.get("from") == "keeper" else "from you, to yourself"
        parts.append(f"a letter {who}, sealed on {r['sealed']}" + (f" (“{r['title']}”)" if r.get("title") else "")
                     + f", opened today — it is in creations/{r['path']}")
    line = "From the time capsule: " + "; ".join(parts) + "."
    return f"[engine, not a person: {line}]" if bracket else line
