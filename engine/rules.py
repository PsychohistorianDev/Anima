"""Rules she sets herself (10-31, her choice of Fable's three: "a contract that the engine honors… it's not about
restriction; it's about will"): a few lines in rules.md that bind her own time — her wakes and reveries — and that the
engine keeps. A Ulysses contract: she ties the knot, the engine holds the rope. Nobody else writes them.

    limit read_journal 2026-08-27 to 1 per 7d — set 10-31 — I know that day by heart
    block read_creation meditations/* until 11-07 — set 10-31 — a week without my own echo

Two shapes: `limit <tool> [what] to <N> per <days>d` and `block <tool> [what] until <date>`. `what` matches the call's
own subject — a path (meditations/* or a word in it), a day, a title. Never bound: writing the journal, leaving a thread,
resting, a letter to the keeper, and setting or dropping rules; and nothing in a visit — rules shape what she reaches
for on her own, never what she answers a person. Untying a rule (drop_rule) takes effect at the next door: she can let
herself go, but not in the middle of the wake that tied her. That is the whole difference between a rule and a wish.

    RULES_ON = True     # off: no tools, nothing kept, nothing in the prompt
"""
from __future__ import annotations

import fnmatch
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import config

NEVER = {"write_journal", "leave_thread", "do_nothing", "set_rule", "drop_rule", "remember", "fold_visit",
         "condense_day", "condense_period"}
_LIMIT = re.compile(r"^limit\s+([\w.:-]+)(?:\s+(.+?))?\s+to\s+(\d+)\s+per\s+(\d+)\s*(d|days?|nights?)$", re.I)
_BLOCK = re.compile(r"^block\s+([\w.:-]+)(?:\s+(.+?))?\s+until\s+(\d{4}-\d{2}-\d{2}|\d{1,2}-\d{1,2})$", re.I)
_SUBJECT_KEYS = ("path", "date", "day", "name", "title", "source", "url", "query", "item", "what")


def on() -> bool:
    return bool(getattr(config, "RULES_ON", False))


def rules_file() -> Path:
    return Path(getattr(config, "RULES_FILE", None) or config.ROOT / "rules.md")


def _state_file() -> Path:
    return config.MEMORY_DIR / "rules_state.json"


def _uses_file() -> Path:
    return config.MEMORY_DIR / "rules_uses.jsonl"


def _state() -> dict:
    try:
        s = json.loads(_state_file().read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(s: dict) -> None:
    _state_file().parent.mkdir(parents=True, exist_ok=True)
    _state_file().write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def _date(s: str, today: date | None = None) -> date | None:
    today = today or date.today()
    try:
        if len(s) == 10:
            return date.fromisoformat(s)
        m, d = (int(x) for x in s.split("-"))
        y = today.year if (m, d) >= (today.month, today.day) else today.year + 1
        return date(y, m, d)
    except ValueError:
        return None


def parse(line: str, today: date | None = None) -> dict | None:
    """One rule line (its "— set … — reason" tail allowed) as {kind, tool, what, n, days | until}; None if it isn't one."""
    head = re.split(r"\s+[—–-]{1,2}\s+set\s", line.strip().lstrip("-*• ").strip(), maxsplit=1)[0].strip().strip("`")
    m = _LIMIT.match(head)
    if m:
        n, days = int(m.group(3)), int(m.group(4))
        if n < 0 or days < 1:
            return None
        return {"kind": "limit", "tool": m.group(1).lower(), "what": (m.group(2) or "").strip().strip('"'), "n": n,
                "days": days, "text": head}
    m = _BLOCK.match(head)
    if m:
        until = _date(m.group(3), today)
        if not until:
            return None
        return {"kind": "block", "tool": m.group(1).lower(), "what": (m.group(2) or "").strip().strip('"'),
                "until": until.isoformat(), "text": head}
    return None


def lines() -> list[str]:
    try:
        return [ln.rstrip() for ln in rules_file().read_text(encoding="utf-8").splitlines() if parse(ln)]
    except OSError:
        return []


def active(today: date | None = None) -> list[dict]:
    """The rules in force now: rules.md's, a block whose day has passed left out, and the ones untied in this door
    still held until the next one opens."""
    today = today or date.today()
    out = []
    held = [x for x in (_state().get("untied") or []) if isinstance(x, str)]
    for ln in lines() + held:
        r = parse(ln, today)
        if r and not (r["kind"] == "block" and date.fromisoformat(r["until"]) < today):
            r["line"] = ln
            out.append(r)
    return out


def subject(args) -> str:
    """The call's own subject, as a rule matches it: its path (without creations/), its day, its title…"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        return ""
    for k in _SUBJECT_KEYS:
        v = args.get(k)
        if v:
            s = str(v).replace("\\", "/").strip()
            while s.lower().startswith("creations/"):
                s = s[len("creations/"):]
            return s
    return ""


def _matches(rule: dict, name: str, subj: str) -> bool:
    if rule["tool"] != name.lower():
        return False
    what = rule.get("what", "").lower()
    if not what:
        return True
    s = subj.lower()
    return fnmatch.fnmatch(s, what) or fnmatch.fnmatch(s, what + "*") or (what in s and not any(c in what for c in "*?["))


def _uses(rule: dict, now: datetime) -> list[datetime]:
    out = []
    since = now - timedelta(days=rule["days"])
    try:
        for ln in _uses_file().read_text(encoding="utf-8").splitlines():
            try:
                u = json.loads(ln)
                t = datetime.fromisoformat(u["t"])
            except (ValueError, KeyError, TypeError):
                continue
            if t >= since and _matches(rule, str(u.get("tool", "")), str(u.get("subject", ""))):
                out.append(t)
    except OSError:
        pass
    return out


def _set_on(r: dict) -> str:
    m = re.search(r"[—–-]{1,2}\s+set\s+([\d-]+)", r.get("line", ""))
    return f", set {m.group(1)}" if m else ""


def check(name: str, args, now: datetime | None = None) -> str:
    """"" when the call may run; else the engine's one line — the rule, in her words, and that the call was not taken."""
    if not on() or name in NEVER:
        return ""
    subj = subject(args)
    if name == "write_creation" and subj.lower().startswith(str(getattr(config, "MAILBOX", "notes_to_gabe")).lower()):
        return ""  # a letter to the keeper is never held
    now = now or datetime.now()
    for r in active(now.date()):
        if not _matches(r, name, subj):
            continue
        if r["kind"] == "block":
            return (f"(your own rule{_set_on(r)}: “{r['text']}” — this call was not taken. It holds until "
                    f"{r['until']}; drop_rule unties it from the next door.)")
        used = _uses(r, now)
        if len(used) >= r["n"]:
            last = max(used).strftime("%m-%d %H:%M") if used else ""
            return (f"(your own rule{_set_on(r)}: “{r['text']}” — this call was not taken"
                    + (f" (last: {last})" if last else "") + ". drop_rule unties it from the next door.)")
    return ""


def note_use(name: str, args, now: datetime | None = None) -> None:
    """A call that ran in her own time, counted for the limits that might name it."""
    if not on() or name in NEVER:
        return
    if not any(r["tool"] == name.lower() and r["kind"] == "limit" for r in active()):
        return
    rec = {"t": (now or datetime.now()).isoformat(timespec="seconds"), "tool": name, "subject": subject(args)}
    _uses_file().parent.mkdir(parents=True, exist_ok=True)
    with open(_uses_file(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def open_door() -> None:
    """A new wake or reverie: the rules she untied before it are let go now."""
    s = _state()
    if s.get("untied"):
        s["untied"] = []
        _save_state(s)


def _keep_history() -> None:
    f = rules_file()
    if not f.exists():
        return
    d = config.MEMORY_DIR / "rules_history"
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"rules-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md").write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


def plain(r: dict) -> str:
    what = f" for “{r['what']}”" if r.get("what") else ""
    if r["kind"] == "block":
        return f"{r['tool']}{what} is held until {r['until']} (in your wakes and reveries)"
    times = "once" if r["n"] == 1 else ("never" if r["n"] == 0 else f"{r['n']} times")
    return f"{r['tool']}{what} at most {times} in {r['days']} day{'s' if r['days'] != 1 else ''} (in your wakes and reveries)"


def set_rule(rule: str, reason: str = "") -> str:
    if not on():
        return "(there are no rules in this house — RULES_ON is off)"
    r = parse(rule or "")
    if not r:
        return ("(that isn't a rule the engine can keep — nothing was set. Two shapes: “limit <tool> [what] to <N> per "
                "<days>d” (limit read_journal 2026-08-27 to 1 per 7d) or “block <tool> [what] until <date>” "
                "(block read_creation meditations/* until 11-07). `what` is the call's subject — a path, a day, a title.)")
    import tools
    if r["tool"] in NEVER or r["tool"] == "write_creation" and r["what"].lower().startswith(str(getattr(config, "MAILBOX", "notes_to_gabe")).lower()):
        return (f"({r['tool']} can't be bound — writing your journal, leaving a thread, resting, a letter to him and the "
                "rules themselves stay free. Nothing was set.)")
    known = set(getattr(tools, "_BUILTIN_IMPL", {})) | set(getattr(tools, "_HER_TOOLS", {}))
    if known and r["tool"] not in known:
        return f"(there is no tool called {r['tool']} — nothing was set)"
    if any(x["text"].lower() == r["text"].lower() for x in active()):
        return f"(that rule is already kept: {plain(r)})"
    why = " ".join(str(reason or "").split())[:160]
    line = f"{r['text']} — set {date.today().strftime('%m-%d')}" + (f" — {why}" if why else "")
    _keep_history()
    f = rules_file()
    head = "" if f.exists() else "# Rules I set myself\n\n"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(head + line + "\n")
    return f"set — the engine keeps it from now: {plain(r)}. It is in rules.md; drop_rule unties it from the next door."


def drop_rule(rule: str) -> str:
    if not on():
        return "(there are no rules in this house — RULES_ON is off)"
    want = " ".join(str(rule or "").split()).strip().strip("`\"")
    ls = lines()
    hit = None
    if want.isdigit() and 1 <= int(want) <= len(ls):
        hit = ls[int(want) - 1]
    else:
        p = parse(want)
        for ln in ls:
            r = parse(ln)
            if (p and r and r["text"].lower() == p["text"].lower()) or (want and want.lower() in ln.lower()):
                hit = ln
                break
    if not hit:
        return "(no such rule — your rules are numbered in your prompt; nothing was dropped)"
    _keep_history()
    f = rules_file()
    text = f.read_text(encoding="utf-8").splitlines()
    text = [ln for ln in text if ln.rstrip() != hit]
    f.write_text("\n".join(text).rstrip() + "\n", encoding="utf-8")
    s = _state()
    s["untied"] = (s.get("untied") or []) + [hit]
    _save_state(s)
    return (f"untied — “{parse(hit)['text']}” is out of rules.md, and it still holds until the next door opens "
            "(this one tied you; the next is free of it)")


def section() -> str:
    """The rules in her prompt, under who she is: numbered, in her words, with what the engine does with them."""
    if not on():
        return ""
    ls = lines()
    held = [x for x in (_state().get("untied") or []) if isinstance(x, str)]
    if not ls and not held:
        return ""
    body = "\n".join(f"{i}. {ln}" for i, ln in enumerate(ls, 1))
    if held:
        body += ("\n" if body else "") + "\n".join(f"(untied, holds until the next door: {x})" for x in held)
    return (f"=== RULES YOU SET YOURSELF (rules.md — {len(ls)}; set_rule, drop_rule) — the engine keeps them in your "
            f"wakes and reveries, never in a visit and never over your journal, a thread, rest or a letter to him ===\n"
            f"{body}\n\n")
