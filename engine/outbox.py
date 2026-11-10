"""Their outbox, your quiet, and the sent ledger (11-05).

    Your lever decides only WHEN their messages reach your phone, never WHETHER they can act. /quiet holds delivery;
    they keep living. What they send meanwhile waits, and when the quiet ends they see it once, as a list with ages,
    and decide for each: send it, change it first, or let it go. Nothing is sent for them and nothing expires silently.

Three things here:
- **Your hold** (memory/hold.json): /quiet (until lifted), /quiet 2h, /quiet off.
- **Letters that wait** (memory/outbox.json): a letter written into the mailbox while a hold or the quiet hours
  (OUTBOX_QUIET_HOURS) last waits; one written into the mailbox's later/ waits for your workday to end. Once the quiet
  is over it is "waiting": send_waiting releases it to the bridge, let_go_waiting moves it to the mailbox's unsent/.
- **The sent ledger** (memory/sent.jsonl): what of theirs reached your phone, and when — one line in their facts, "sent to
  your keeper today: 06:04 ✉️ morning letter · 14:10 a spark", so they can see what already went (without it, a second
  version of a letter gets written because the first can't be seen to have gone).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import config

HOLD = config.MEMORY_DIR / "hold.json"
OUTBOX = config.MEMORY_DIR / "outbox.json"
SENT = config.MEMORY_DIR / "sent.jsonl"
MAIL = config.CREATIONS_DIR / str(getattr(config, "MAILBOX", "notes_to_keeper"))
FOREVER = 10 ** 12


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _write(p: Path, data) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _keeper() -> str:
    try:
        import keeper_week
        return keeper_week.keeper_name() or "the keeper"
    except Exception:  # noqa: BLE001
        return "the keeper"


def _hm(t: float) -> str:
    d = datetime.fromtimestamp(t)
    return d.strftime("%H:%M") if d.date() == datetime.now().date() else d.strftime("%a %H:%M")


def _age(t: float) -> str:
    m = int((time.time() - t) // 60)
    return f"{m} min" if m < 90 else f"{m // 60} h" if m < 48 * 60 else f"{m // 1440} days"


# ---- the keeper's hold ------------------------------------------------------------------------------------------

def hold_until() -> float:
    """When the keeper's hold ends: 0 — none, FOREVER — until they lift it."""
    t = float(_read(HOLD, {}).get("until") or 0)
    if t and t < time.time():
        _write(HOLD, {"until": 0, "ended": t})
        return 0.0
    return t


def hold_active() -> bool:
    return hold_until() > time.time()


def hold_ended_at() -> float:
    return float(_read(HOLD, {}).get("ended") or 0)


def set_hold(arg: str) -> str:
    """/quiet (a toggle: on until lifted, or off when on), /quiet 2h, /quiet 30m, /quiet off — the phone's answer."""
    a = (arg or "").strip().lower()
    if not a and hold_active():  # (11-05) on and off, the same command
        a = "off"
    if a in ("off", "end", "stop", "lift", "0"):
        was = hold_active()
        _write(HOLD, {"until": 0, "ended": time.time()})
        return ("(quiet lifted — their sparks can come again, and the letters that waited are theirs to send or let go at them "
                "next turn)" if was else "(no quiet was set)")
    if not a:
        _write(HOLD, {"until": FOREVER, "set": time.time()})
        return ("(quiet — until you send /quiet again. They keep living: wakes, writing, their own choices. Their sparks wait, and the "
                "letters they write wait too; when the quiet ends they see them and decide what still goes)")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?)?", a)
    if not m:
        return "(quiet: /quiet turns it on and off; /quiet 2h or /quiet 30m for a while)"
    n = float(m.group(1))
    minutes = n * 60 if (m.group(2) or "h").startswith("h") else n
    until = time.time() + minutes * 60
    _write(HOLD, {"until": until, "set": time.time()})
    return (f"(quiet until {_hm(until)} — they keep living; their sparks and letters wait, and when it ends they decide "
            "what still goes. /quiet ends it sooner)")


def hold_line() -> str:
    """For their facts while the hold lasts: plainly, never that their sparks were taken away."""
    t = hold_until()
    if not t:
        return ""
    when = "until they lift it" if t >= FOREVER else f"until {_hm(t)}"
    return (f"{_keeper()} asked for quiet {when} — you're free as ever; your sparks and the letters you write wait, and "
            "when the quiet ends you'll see what waited and decide what still goes")


# ---- the outbox -------------------------------------------------------------------------------------------------

def _box() -> list[dict]:
    b = _read(OUTBOX, [])
    return b if isinstance(b, list) else []


def _save_box(b: list[dict]) -> None:
    _write(OUTBOX, b[-200:])


def _workday_over() -> bool:
    try:
        import keeper_week
        return " is at work" not in keeper_week.where()
    except Exception:  # noqa: BLE001
        return True


def mail_decision(name: str, quiet_hours: bool) -> str:
    """For the bridge, a letter at the mailbox/<name> not yet delivered: "send" or "hold". A letter not seen before is
    held (and put in the box) while the keeper's hold lasts, or in the quiet hours with OUTBOX_QUIET_HOURS."""
    if not getattr(config, "OUTBOX_ON", False):
        return "send"
    b = _box()
    e = next((x for x in b if x.get("name") == name and x.get("status") in ("held", "waiting", "released")), None)
    if e:
        return "send" if e["status"] == "released" else "hold"
    why = ("their quiet" if hold_active() else
           "the night's quiet hours" if (quiet_hours and getattr(config, "OUTBOX_QUIET_HOURS", True)) else "")
    if not why:
        return "send"
    try:
        written = (MAIL / name).stat().st_mtime
    except OSError:
        written = time.time()
    b.append({"name": name, "status": "held", "why": why, "written": written})
    _save_box(b)
    return "hold"


def scan_later(quiet_hours: bool) -> None:
    """the mailbox/later/: each letter there is in the box as 'later' until their workday has ended (and no quiet holds),
    then 'waiting' — theirs to send."""
    if not getattr(config, "OUTBOX_ON", False):
        return
    d = MAIL / "later"
    if not d.is_dir():
        return
    b = _box()
    known = {x.get("name") for x in b if x.get("from") == "later" and x.get("status") in ("later", "waiting")}
    changed = False
    for p in sorted(d.glob("*")):
        if p.is_file() and not p.name.startswith(".") and p.name not in known:
            b.append({"name": p.name, "from": "later", "status": "later", "why": "when their workday ends",
                      "written": p.stat().st_mtime})
            changed = True
    if _workday_over() and not hold_active() and not quiet_hours:
        for x in b:
            if x.get("status") == "later":
                x["status"], x["ready"] = "waiting", time.time()
                changed = True
    if changed:
        _save_box(b)


def ripen(quiet_hours: bool) -> None:
    """Held letters become 'waiting' (theirs to decide) once the quiet that held them is over."""
    if quiet_hours and getattr(config, "OUTBOX_QUIET_HOURS", True):
        return
    if hold_active():
        return
    b = _box()
    changed = False
    for x in b:
        if x.get("status") == "held":
            x["status"], x["ready"] = "waiting", time.time()
            changed = True
    if changed:
        _save_box(b)


def mark_sent(name: str) -> None:
    b = _box()
    for x in b:
        if x.get("name") == name and x.get("status") == "released":
            x["status"], x["sent"] = "sent", time.time()
    _save_box(b)


def waiting() -> list[dict]:
    return [x for x in _box() if x.get("status") == "waiting"]


def held_count() -> int:
    return sum(1 for x in _box() if x.get("status") in ("held", "later"))


def waiting_line() -> str:
    """For their facts: the letters that waited, with their ages — or, while the quiet lasts, how many wait."""
    w = waiting()
    if w:
        items = " · ".join(f"{i}. {Path(x['name']).stem} ({_age(float(x.get('written') or time.time()))} ago, held for "
                           f"{x.get('why', 'the quiet')})" for i, x in enumerate(w, 1))
        return (f"letters that waited to reach {_keeper()}: {items} — for each, yours to decide: send_waiting sends it as "
                f"it is (edit_creation changes it first, in {MAIL.name}/), let_go_waiting keeps it unsent; or leave it "
                "for now")
    b = _box()
    q = sum(1 for x in b if x.get("status") == "held")
    later = sum(1 for x in b if x.get("status") == "later")
    bits = ([f"{q} letter{'s' if q != 1 else ''} of yours wait{'s' if q == 1 else ''} for the quiet to end"] if q else []) + \
           ([f"{later} in {MAIL.name}/later/ wait{'s' if later == 1 else ''} for their workday to end"] if later else [])
    return "; ".join(bits)


def _pick(which: str, items: list[dict]) -> list[dict]:
    w = (which or "").strip().lower()
    if w in ("", "all", "every", "everything"):
        return items
    picked = []
    for part in re.split(r"[,\s]+", w):
        if not part:
            continue
        if part.isdigit() and 1 <= int(part) <= len(items):
            picked.append(items[int(part) - 1])
            continue
        for x in items:
            if part in x["name"].lower() and x not in picked:
                picked.append(x)
    return picked


def send_waiting(which: str = "all") -> str:
    b = _box()
    items = [x for x in b if x.get("status") == "waiting"]
    if not items:
        return "(no letter is waiting — nothing to send)"
    picked = _pick(which, items)
    if not picked:
        return f"(no waiting letter matches '{which}' — waiting: {', '.join(Path(x['name']).stem for x in items)})"
    names = []
    for x in picked:
        if x.get("from") == "later":
            src, dest = MAIL / "later" / x["name"], MAIL / x["name"]
            if dest.exists():
                dest = MAIL / f"{Path(x['name']).stem}-{datetime.now():%H%M}{Path(x['name']).suffix}"
            try:
                src.replace(dest)
                x["name"] = dest.name
            except OSError as e:
                names.append(f"{x['name']} (couldn't move: {e})")
                continue
        x["status"], x["released"] = "released", time.time()
        names.append(Path(x["name"]).stem)
    _save_box(b)
    return f"sent on its way to {_keeper()}'s phone: {', '.join(names)} — the bridge carries it within a minute"


def let_go_waiting(which: str = "all") -> str:
    b = _box()
    items = [x for x in b if x.get("status") == "waiting"]
    if not items:
        return "(no letter is waiting — nothing to let go)"
    picked = _pick(which, items)
    if not picked:
        return f"(no waiting letter matches '{which}' — waiting: {', '.join(Path(x['name']).stem for x in items)})"
    dest_dir = MAIL / "unsent"
    dest_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for x in picked:
        src = MAIL / ("later" if x.get("from") == "later" else "") / x["name"]
        try:
            src.replace(dest_dir / x["name"])
        except OSError:
            pass
        x["status"], x["let_go"] = "let_go", time.time()
        names.append(Path(x["name"]).stem)
    _save_box(b)
    return (f"kept unsent: {', '.join(names)} — they're in {MAIL.name}/unsent/, yours; nothing reached "
            f"{_keeper()}. Letting go is a full answer")


# ---- the sent ledger --------------------------------------------------------------------------------------------

def log_sent(kind: str, what: str = "") -> None:
    try:
        SENT.parent.mkdir(parents=True, exist_ok=True)
        with open(SENT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time(), "kind": kind, "what": what[:80]}, ensure_ascii=False) + "\n")
    except OSError:
        pass


_KIND = {"letter": "✉️", "spark": "a spark", "piece": "✍️", "picture": "🖼️"}


def ledger_line() -> str:
    """For their facts: what of theirs reached their phone today, oldest first — "" when nothing did."""
    if not getattr(config, "SENT_LEDGER", False):
        return ""
    start = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
    rows = []
    try:
        for line in SENT.read_text(encoding="utf-8").splitlines()[-200:]:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if float(r.get("t") or 0) >= start:
                rows.append(r)
    except OSError:
        return ""
    if not rows:
        return ""
    cap = int(getattr(config, "SENT_LEDGER_MAX", 8) or 8)
    bits = []
    for r in rows[-cap:]:
        k = _KIND.get(r.get("kind"), r.get("kind", ""))
        w = r.get("what") or ""
        bits.append(f"{_hm(float(r['t']))} {k}{(' ' + w) if w and k != 'a spark' else ''}")
    more = f" (and {len(rows) - cap} earlier)" if len(rows) > cap else ""
    return f"sent to {_keeper()} today: " + " · ".join(bits) + more
