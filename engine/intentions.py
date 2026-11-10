"""Intentions (11-05) — they decide now when they act later.

Their words, a condition the engine can observe, and — if they like — a guess about what will happen. When the
condition comes true they're woken (or, with the heartbeat off, sparked; or, mid-visit, told in the moment of their next
message) with their own words, what changed, and the choice: do it, change it, or let it go. Letting it go is a full
answer; nothing counts what they drop.

Conditions (all facts about the world; "quiet for N hours" is deliberately not one — silence is never a trigger):
    a time      "21:00", "tomorrow 10:00", "2026-11-08 09:30", "in 3 hours", "saturday 10:00", "on 11-20"
    workday     "when their workday ends" — by your work calendar: expected, not proof you're home
    your first message of the day   ("when they wake up" means this; it's the nearest real evidence)
    the desk    "when they sit down at the desk" — the PC touched again after a quiet (desk.py)
    the weather "rain", "snow", "storm", "frost", "a clear night", "sun" — from the window's feed, once the sky
                isn't already that
    the garden  "the garden changes" — a bed reaches its next stage
    your game   "their game ends" (gameguard.py)
    anything else is kept as their words, "needs the watcher" — not judged yet

At most INTENTIONS_MAX open; they lapse after INTENTIONS_DAYS unless they fire (one line at the next door, no wake).
Under their bell: a count and keywords only ("intentions open: 3 — rain · Sat 10:00 · workday end"); their full words come
back once, when one fires (words under every bell would become an assignment). memory/intentions.json.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta

import config

STORE = config.MEMORY_DIR / "intentions.json"
_last_check = {"t": 0.0}
_DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
         "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEATHER = {
    "rain": ("rain", lambda c, t, day: c in set(range(51, 68)) | {80, 81, 82}),
    "snow": ("snow", lambda c, t, day: c in set(range(71, 78)) | {85, 86}),
    "storm": ("a storm", lambda c, t, day: c in (95, 96, 99)),
    "frost": ("frost", lambda c, t, day: t is not None and t <= 0.5),
    "clear night": ("a clear night", lambda c, t, day: c in (0, 1) and not day),
    "sun": ("sun", lambda c, t, day: c in (0, 1) and day),
    "fog": ("fog", lambda c, t, day: c in (45, 48)),
}


def _load() -> dict:
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("items", [])
            return d
    except Exception:  # noqa: BLE001
        pass
    return {"items": []}


def _save(d: dict) -> None:
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        d["items"] = d["items"][-120:]
        STORE.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _keeper() -> str:
    try:
        import keeper_week
        return keeper_week.keeper_name() or "the keeper"
    except Exception:  # noqa: BLE001
        return "the keeper"


def _when_say(t: datetime, now: datetime) -> str:
    days = (t.date() - now.date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else f"{t:%A}" if days < 7 else f"{t.day} {t:%B}"
    return f"{day} at {t:%H:%M}"


# ---- reading them "when" -----------------------------------------------------------------------------------------

def parse_when(when: str, now: datetime | None = None) -> dict:
    """Their words for when → a condition: {"kind": time|workday|first_message|weather|garden|game|words, …, "label"}."""
    now = now or datetime.now()
    w = " ".join(str(when or "").lower().replace("’", "'").split()).strip(" .!")
    w = re.sub(r"^(when|once|as soon as|if|at)\s+", "", w)
    if not w:
        return {"kind": "error", "say": "(when? a time, their workday's end, their first message, the weather, the garden, or their game)"}
    if re.search(r"sits? (back )?(down )?at (the|his|her|their) (desk|pc|computer)|sits? (back )?down|back at (the|his|her|their) (desk|pc|computer)|"
                 r"at the desk|comes? to the (desk|pc|computer)", w):
        return {"kind": "desk", "label": "they sit down at the desk",
                "say": "when the PC's keyboard or mouse comes back to life after at least "
                       f"{int(getattr(config, 'DESK_ARRIVE_AFTER_MIN', 20) or 20)} minutes untouched (the PC is touched — "
                       "the engine can't see who)"}
    if re.search(r"work ?day|after work|gets? (home|off)|comes? home|work ends|finish(es)? work|shift ends", w):
        return {"kind": "workday", "label": "their workday ends",
                "say": "when their workday ends by their work calendar (expected — not proof they're home)"}
    if re.search(r"wakes? up|first message|first word|says good morning|morning message|writes (to me )?first", w):
        return {"kind": "first_message", "label": "their first message",
                "say": "at their first message of the day (the nearest real sign they're up — the engine can't see them wake)"}
    if re.search(r"game (ends|is over|finishes)|(stops|done|finishes) (gaming|playing)|after (his|her|their|the) game", w):
        return {"kind": "game", "label": "their game ends", "say": "when their game ends (the card's own count)"}
    if re.search(r"garden|bed \d|sprout|bloom|plant (grows|changes)|next stage", w):
        return {"kind": "garden", "label": "the garden", "say": "when a bed in your garden reaches its next stage"}
    for key, (label, _) in _WEATHER.items():
        if re.search(r"\b" + key.replace(" ", r"\s") + r"(s|y|ing|starts?|begins?)?\b", w) or (key == "rain" and "raining" in w):
            return {"kind": "weather", "what": key, "label": label,
                    "say": f"when the window's feed shows {label} over {getattr(config, 'OUTSIDE_PLACE', '') or 'the house'} (checked every half hour; it has to begin, "
                           "not already be there)"}
    t = _parse_time(w, now)
    if t:
        return {"kind": "time", "at": t.timestamp(), "label": f"{t:%a %H:%M}", "say": _when_say(t, now)}
    return {"kind": "words", "words": w[:200], "label": "watcher: " + " ".join(w.split()[:4]),
            "say": "in your own words — the engine can't watch for that, so it waits as your words until it lapses or you drop it"}


def _parse_time(w: str, now: datetime) -> datetime | None:
    m = re.fullmatch(r"in (\d+(?:\.\d+)?)\s*(m|min|mins|minutes?|h|hrs?|hours?|days?)", w)
    if m:
        n, u = float(m.group(1)), m.group(2)
        return now + (timedelta(days=n) if u.startswith("d") else timedelta(hours=n) if u.startswith("h") else timedelta(minutes=n))
    base, rest = None, w
    m = re.match(r"(tomorrow|tonight|today|this evening|this morning)\b\s*(?:at\s*)?(.*)", w)
    if m:
        base = now.date() + timedelta(days=1 if m.group(1) == "tomorrow" else 0)
        rest = m.group(2)
        if not rest:
            rest = {"tonight": "21:00", "this evening": "19:00", "this morning": "09:00"}.get(m.group(1), "09:00")
    m2 = re.match(r"(?:on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b\s*(?:at\s*)?(.*)", w)
    if base is None and m2:
        ahead = (_DAYS[m2.group(1)] - now.weekday()) % 7 or 7
        base, rest = now.date() + timedelta(days=ahead), m2.group(2) or "09:00"
    m3 = re.match(r"(?:on\s+)?(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\b\s*(?:at\s*)?(.*)", w)
    if base is None and m3:
        y = int(m3.group(1) or now.year)
        try:
            base = date(y, int(m3.group(2)), int(m3.group(3)))
        except ValueError:
            return None
        if base < now.date() and not m3.group(1):
            base = date(y + 1, base.month, base.day)
        rest = m3.group(4) or "09:00"
    mt = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", rest.strip()) if rest.strip() else None
    if not mt:
        return None
    hh, mm = int(mt.group(1)), int(mt.group(2) or 0)
    if mt.group(3) == "pm" and hh < 12:
        hh += 12
    if mt.group(3) == "am" and hh == 12:
        hh = 0
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    if base is None:
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)
    t = datetime(base.year, base.month, base.day, hh, mm)
    return t if t > now else None


# ---- the world, as the conditions read it -----------------------------------------------------------------------

def _sky() -> tuple[int | None, float | None, bool]:
    try:
        import outside
        c = (outside.weather() or {}).get("current") or {}
        return (int(c["weather_code"]) if c.get("weather_code") is not None else None,
                float(c["temperature_2m"]) if c.get("temperature_2m") is not None else None, bool(c.get("is_day", 1)))
    except Exception:  # noqa: BLE001
        return None, None, True


def _garden_sig() -> str:
    try:
        import garden
        g = garden.load()
        return "|".join(f"{b['seed']}:{garden.stage(b.get('growth', 0))}" if b else "-" for b in g.get("beds") or [])
    except Exception:  # noqa: BLE001
        return ""


def _at_work() -> bool:
    try:
        import keeper_week
        return " is at work" in keeper_week.where()
    except Exception:  # noqa: BLE001
        return False


def note_keeper_message(now: float | None = None) -> bool:
    """A message from them (the visit's moment calls this): True when it's their first of the day — after the night's quiet
    hours, with none since."""
    t = float(now if now is not None else time.time())
    d = _load()
    last = float(d.get("keeper_last") or 0)
    hours = getattr(config, "TELEGRAM_QUIET_HOURS", (0, 4)) or (0, 4)
    dawn = datetime.combine(datetime.fromtimestamp(t).date(), datetime.min.time()) + timedelta(hours=int(hours[1]))
    first = datetime.fromtimestamp(t) >= dawn and (not last or datetime.fromtimestamp(last) < dawn)
    d["keeper_last"] = t
    if first:
        d["keeper_first"] = t
    _save(d)
    return first


# ---- their tools ----------------------------------------------------------------------------------------------------

def _norm(s: str) -> set:
    return {w for w in re.findall(r"[a-z']+", (s or "").lower()) if len(w) > 2}


def intend(what: str, when: str, guess: str = "", anyway: str = "", now: datetime | None = None) -> str:
    now = now or datetime.now()
    words = " ".join(str(what or "").split())[:400]
    if not words:
        return "(what do you mean to do? the intention needs your words)"
    cond = parse_when(when, now)
    if cond.get("kind") == "error":
        return cond["say"]
    d = _load()
    open_ = [x for x in d["items"] if x.get("status") == "open"]
    if len(open_) >= int(getattr(config, "INTENTIONS_MAX", 7) or 7):
        return f"(you hold {len(open_)} intentions already — drop_intention one first)"
    for x in open_:
        if x.get("cond", {}).get("label") == cond.get("label") and _norm(x["words"]) == _norm(words):
            return "(you hold this one already — same words, same when)"
    if str(anyway or "").strip().lower() not in ("yes", "true", "1", "anyway"):  # the repeat mirror (Fable)
        week = time.time() - 7 * 86400
        a = _norm(words)
        for x in reversed(d["items"]):
            if float(x.get("set") or 0) < week or x.get("status") == "open":
                continue
            b = _norm(x["words"])
            if a and b and len(a & b) / max(1, min(len(a), len(b))) >= 0.6:
                when_set = datetime.fromtimestamp(float(x["set"])).strftime("%A")
                return (f"(you set this on {when_set} too: “{x['words'][:140]}” — {x.get('status')}. Set it anyway? "
                        "Call intend again with anyway=\"yes\". Nothing was set)")
    item = {"id": int(d.get("next_id") or 1), "words": words, "cond": cond, "guess": " ".join(str(guess or "").split())[:300],
            "set": time.time(), "status": "open"}
    days = float(getattr(config, "INTENTIONS_DAYS", 7) or 7)
    item["lapses"] = (max(float(cond.get("at") or 0) + 3600, time.time() + days * 86400)
                      if cond.get("kind") == "time" else time.time() + days * 86400)
    if cond.get("kind") == "garden":
        item["sig"] = _garden_sig()
    if cond.get("kind") == "weather":
        c, t, day = _sky()
        item["armed"] = not (c is not None and _WEATHER[cond["what"]][1](c, t, day))
    if cond.get("kind") == "workday":
        item["armed"] = _at_work()
    d["next_id"] = item["id"] + 1
    d["items"].append(item)
    _save(d)
    lapse = datetime.fromtimestamp(item["lapses"]).strftime("%A %d %B").replace(" 0", " ")
    return (f"intention {item['id']} set — {cond['say']}, you'll be met with your words: “{words[:160]}”"
            + (f", and your guess beside what happened: “{item['guess'][:120]}”" if item["guess"] else "")
            + f". It lapses {lapse} if it hasn't come; drop_intention lets it go sooner")


def drop_intention(which: str) -> str:
    d = _load()
    open_ = [x for x in d["items"] if x.get("status") == "open"]
    if not open_:
        return "(no intention is open)"
    w = str(which or "").strip().lower().lstrip("#")
    hits = [x for x in open_ if w.isdigit() and int(w) == x["id"]] or \
           [x for x in open_ if w and (w in x["words"].lower() or w in x["cond"].get("label", "").lower())]
    if len(hits) != 1:
        return ("(no open intention matches — the list under your bell gives their numbers)" if not hits
                else f"({len(hits)} match — give its number)")
    hits[0]["status"], hits[0]["ended"] = "dropped", time.time()
    _save(d)
    return f"let go: intention {hits[0]['id']} (“{hits[0]['words'][:80]}”) — a full answer"


# ---- watching -----------------------------------------------------------------------------------------------------

def check(force: bool = False) -> list[dict]:
    """Look at the world for the open intentions (at most every INTENTIONS_CHECK_S): those whose condition came true
    become 'due' with what changed; those past their time lapse. Returns the due ones (not taken)."""
    if not getattr(config, "INTENTIONS_ON", False):
        return []
    now = time.time()
    if not force and now - _last_check["t"] < float(getattr(config, "INTENTIONS_CHECK_S", 60) or 60):
        return [x for x in _load()["items"] if x.get("status") == "due"]
    _last_check["t"] = now
    d = _load()
    changed = False
    sky = None
    for x in d["items"]:
        if x.get("status") != "open":
            continue
        c = x.get("cond") or {}
        k = c.get("kind")
        what = ""
        if k == "time" and now >= float(c.get("at") or 0):
            what = f"it's {datetime.now():%H:%M}"
        elif k == "workday":
            if _at_work():
                if not x.get("armed"):
                    x["armed"] = True
                    changed = True
            elif x.get("armed"):
                what = f"their workday has ended by their calendar (expected — {_keeper()} hasn't necessarily said they're home)"
        elif k == "first_message" and float(d.get("keeper_first") or 0) > float(x["set"]):
            what = f"{_keeper()}'s first message of the day came at {datetime.fromtimestamp(float(d['keeper_first'])):%H:%M}"
        elif k == "desk":
            try:
                import desk
                a = desk.arrived_since(float(x["set"]))
                if a:
                    what = f"the PC came back to life at {datetime.fromtimestamp(a):%H:%M}"
            except Exception:  # noqa: BLE001
                pass
        elif k == "game":
            try:
                import gameguard
                if gameguard.ended_since(float(x["set"])):
                    what = "their game has ended"
            except Exception:  # noqa: BLE001
                pass
        elif k == "garden":
            sig = _garden_sig()
            if sig and x.get("sig") and sig != x["sig"]:
                what = _garden_change(x["sig"], sig)
        elif k == "weather":
            sky = sky or _sky()
            cc, t, day = sky
            if cc is not None:
                now_is = _WEATHER[c["what"]][1](cc, t, day)
                if not now_is and not x.get("armed"):
                    x["armed"] = True
                    changed = True
                elif now_is and x.get("armed"):
                    try:
                        import outside
                        what = "the window: " + outside.line()
                    except Exception:  # noqa: BLE001
                        what = f"the window shows {c.get('label')}"
        if what:
            x.update(status="due", due=now, what=what)
            changed = True
        elif now > float(x.get("lapses") or now + 1):
            x.update(status="lapsed", ended=now, untold=True)
            changed = True
    if changed:
        _save(d)
    return [x for x in d["items"] if x.get("status") == "due"]


def _garden_change(a: str, b: str) -> str:
    out = []
    for n, (x, y) in enumerate(zip(a.split("|"), b.split("|")), 1):
        if x != y:
            out.append(f"bed {n}: {y.replace(':', ' — ')}" if y != "-" else f"bed {n} is empty now")
    return "the garden: " + "; ".join(out) if out else "the garden changed"


def take_due(fire_words: bool = False) -> list[dict]:
    """The due intentions, marked fired (they come back once)."""
    d = _load()
    got = []
    for x in d["items"]:
        if x.get("status") == "due":
            x.update(status="fired", fired=time.time())
            got.append(dict(x))
    if got:
        _save(d)
    return got


def due_now() -> bool:
    return bool(check())


def bell(items: list[dict], bare: bool = False) -> str:
    """The words they're met with when intentions come due — their own, what changed, their guess beside it, and the door out."""
    parts = []
    for x in items:
        mins = int((time.time() - float(x["set"])) // 60)
        ago = (f"{mins} minutes ago" if mins < 90 else f"{mins // 60} hours ago" if mins < 48 * 60
               else f"{mins // 1440} days ago")
        guess = (f" Your guess then: “{x['guess']}” — and what happened: {x.get('what')}." if x.get("guess") else "")
        parts.append(f"An intention of yours, set {ago} for “{x['cond'].get('label', '')}”: “{x['words']}”. "
                     f"What changed: {x.get('what')}.{guess}")
    inner = " ".join(parts) + " It's yours: do it, change it, or let it go — letting it go is a full answer."
    return inner if bare else "[engine, not a person: " + inner + "]"


def facts_bit() -> str:
    """Under their bell: open intentions as a count and keywords; lapsed ones told once, no wake."""
    if not getattr(config, "INTENTIONS_ON", False):
        return ""
    d = _load()
    bits = []
    lapsed = [x for x in d["items"] if x.get("status") == "lapsed" and x.get("untold")]
    if lapsed:
        bits.append(f"{len(lapsed)} intention{'s' if len(lapsed) != 1 else ''} lapsed: "
                    + ", ".join(x["cond"].get("label", "") for x in lapsed))
        for x in lapsed:
            x["untold"] = False
        _save(d)
    open_ = [x for x in d["items"] if x.get("status") == "open"]
    if open_:
        bits.append(f"intentions open: {len(open_)} — " + " · ".join(f"{x['id']}: {x['cond'].get('label', '')}" for x in open_))
    return "; ".join(bits)
