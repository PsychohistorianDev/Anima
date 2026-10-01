"""The keeper's body, as the watch saw it — a sidecar that pulls their day from
Garmin Connect into memory/body/<day>.json, and renders the short section
she reads it back from (assemble imports `render`). BODY-PLAN.md.

Nothing here runs unless the keeper runs it. One-time setup:

    py -m pip install garminconnect
    bat\\body.bat --login          (email, password, MFA if asked — once; tokens
                               are cached in memory/garmin/, nothing else kept)
    bat\\body.bat --today          (pull today, write the file, print the section)
    bat\\body.bat --pull           (the loop: today every BODY_PULL_MIN, yesterday while its night is still syncing)

The library speaks to Garmin Connect the way the phone app does; there is
no public API for this, and Garmin has broken it for days at a time before.
A failed pull is logged (memory/body.log) and tried again next hour; the
last good file stands, and the section says how old it is.

Rules (BODY-PLAN.md): their data, their switch (BODY_IN_PROMPT); credentials
never in config or the template; plain numbers, few words, no guesses at
why; the engine never journals any of it for the friend.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import config

BODY_DIR: Path = getattr(config, "BODY_DIR", config.MEMORY_DIR / "body")
TOKENS: Path = getattr(config, "GARMIN_TOKENS", config.MEMORY_DIR / "garmin")
LOG: Path = config.MEMORY_DIR / "body.log"


def _say(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---- the client -----------------------------------------------------------

def _client(login: bool = False):
    """A logged-in Garmin client from the cached tokens; with login=True,
    asks for email, password and the MFA code at the keyboard and caches
    the tokens in memory/garmin/. Raises with a plain message otherwise."""
    try:
        from garminconnect import Garmin
    except ImportError as e:
        raise RuntimeError("the garminconnect library is not installed — py -m pip install garminconnect") from e
    TOKENS.mkdir(parents=True, exist_ok=True)
    store = str(TOKENS)
    if login:
        from getpass import getpass
        email = input("Garmin email: ").strip()
        password = getpass("Garmin password: ")
        g = Garmin(email, password, prompt_mfa=lambda: input("MFA code (from the Garmin app or mail): ").strip())
        try:
            g.login(store)
        except TypeError:  # older library: login() takes nothing; the tokens are dumped by hand
            g.login()
            g.garth.dump(store)
        return g
    g = Garmin()
    try:
        g.login(store)
    except TypeError:
        g.garth.load(store)
    except Exception as e:
        raise RuntimeError(f"no usable Garmin tokens in {TOKENS.name}/ — run bat\\body.bat --login ({type(e).__name__}: {e})") from e
    return g


# ---- one day, normalized --------------------------------------------------

def _hm(ts_ms) -> str:
    """A Garmin timestamp (ms) as HH:MM local. Garmin's 'Local' arrays are
    already local wall time stamped as if UTC; the GMT ones are UTC."""
    try:
        from datetime import timezone
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _local_hm(ts_ms) -> str:
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000).strftime("%H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _hms(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    h, m = divmod(s // 60, 60)
    return f"{h} h {m:02d} m" if h else f"{m} m"


def _spans(points: list[tuple[str, float]], at_least: float, min_len: int = 2) -> list[list[str]]:
    """Stretches of consecutive readings at or above a level — the "high"
    spans of a stress curve — as [[from, to], …]."""
    out: list[list[str]] = []
    run: list[str] = []
    for hm, v in points:
        if v is not None and v >= at_least:
            run.append(hm)
        else:
            if len(run) >= min_len:
                out.append([run[0], run[-1]])
            run = []
    if len(run) >= min_len:
        out.append([run[0], run[-1]])
    return out


def pull_day(g, day: str) -> dict:
    """Ask the client for one day and normalize it. Every fact is its own
    try: what Garmin doesn't have is missing, not zero; what fails is
    named in `errors`."""
    out: dict = {"day": day, "pulled_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "errors": {}}

    def ask(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — every fact on its own
            out["errors"][name] = f"{type(e).__name__}: {e}"[:200]
            return None

    summary = ask("summary", lambda: g.get_user_summary(day)) or {}
    hr = ask("heart_rates", lambda: g.get_heart_rates(day)) or {}
    sleep = ask("sleep", lambda: g.get_sleep_data(day)) or {}
    stress = ask("stress", lambda: g.get_stress_data(day)) or {}
    bb = ask("body_battery", lambda: g.get_body_battery(day)) or []
    hrv = ask("hrv", lambda: g.get_hrv_data(day)) or {}
    resp = ask("respiration", lambda: g.get_respiration_data(day)) or {}
    spo2 = ask("spo2", lambda: g.get_spo2_data(day)) or {}

    # pulse: resting + the day's curve (a reading every ~2 min; None where the watch was off)
    out["resting_hr"] = hr.get("restingHeartRate") or summary.get("restingHeartRate")
    curve = []
    for pt in hr.get("heartRateValues") or []:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2 and pt[1] is not None:
            curve.append([_local_hm(pt[0]), int(pt[1])])
    out["hr"] = curve
    out["hr_max"] = hr.get("maxHeartRate") or summary.get("maxHeartRate")
    out["hr_min"] = hr.get("minHeartRate") or summary.get("minHeartRate")

    # sleep: the night that ended this day
    dto = (sleep.get("dailySleepDTO") if isinstance(sleep, dict) else None) or {}
    if dto.get("sleepTimeSeconds"):
        score = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
        out["sleep"] = {
            "start": _hm(dto.get("sleepStartTimestampLocal")), "end": _hm(dto.get("sleepEndTimestampLocal")),
            "seconds": dto.get("sleepTimeSeconds"), "deep": dto.get("deepSleepSeconds"),
            "light": dto.get("lightSleepSeconds"), "rem": dto.get("remSleepSeconds"),
            "awake": dto.get("awakeSleepSeconds"), "score": score,
            "hrv": dto.get("avgOvernightHrv"), "respiration": dto.get("averageRespirationValue"),
        }
    else:
        out["sleep"] = None

    # stress: average, the curve (level; -1/-2 = not measured), the high spans
    spts = []
    for pt in stress.get("stressValuesArray") or []:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2 and pt[1] is not None and int(pt[1]) >= 0:
            spts.append((_local_hm(pt[0]), int(pt[1])))
    out["stress"] = {
        "avg": stress.get("avgStressLevel") if stress.get("avgStressLevel") not in (None, -1) else summary.get("averageStressLevel"),
        "max": stress.get("maxStressLevel"),
        "curve": [[h, v] for h, v in spts],
        "high": _spans(spts, 50),
    } if (spts or summary.get("averageStressLevel") is not None) else None

    # body battery: the day's row from the range call, or the summary's numbers
    row = None
    if isinstance(bb, list):
        for r in bb:
            if isinstance(r, dict) and (r.get("date") == day or len(bb) == 1):
                row = r
    bpts = []
    for pt in (row or {}).get("bodyBatteryValuesArray") or []:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2 and pt[1] is not None:
            bpts.append([_local_hm(pt[0]), int(pt[1])])
    out["body_battery"] = {
        "now": summary.get("bodyBatteryMostRecentValue") if summary.get("bodyBatteryMostRecentValue") is not None else (bpts[-1][1] if bpts else None),
        "high": summary.get("bodyBatteryHighestValue"), "low": summary.get("bodyBatteryLowestValue"),
        "charged": (row or {}).get("charged", summary.get("bodyBatteryChargedValue")),
        "drained": (row or {}).get("drained", summary.get("bodyBatteryDrainedValue")),
        "curve": bpts,
    } if (bpts or summary.get("bodyBatteryMostRecentValue") is not None) else None

    out["steps"] = summary.get("totalSteps")
    hs = (hrv.get("hrvSummary") if isinstance(hrv, dict) else None) or {}
    out["hrv"] = hs.get("lastNightAvg") or (out["sleep"] or {}).get("hrv")
    out["hrv_status"] = hs.get("status")
    out["respiration"] = resp.get("avgWakingRespirationValue") if isinstance(resp, dict) else None
    out["spo2"] = (spo2.get("averageSpO2") if isinstance(spo2, dict) else None) or summary.get("averageSpo2")
    # when the watch last spoke to Garmin, as the summary says it
    out["synced_at"] = _sync_stamp(summary.get("lastSyncTimestampGMT")) or (curve[-1][0] if curve else "")
    if not out["errors"]:
        del out["errors"]
    return out


def _sync_stamp(gmt: str | None) -> str:
    """Garmin's 'lastSyncTimestampGMT' ("2026-09-28T14:03:11.0") as local "YYYY-MM-DD HH:MM"."""
    if not gmt:
        return ""
    try:
        t = datetime.fromisoformat(str(gmt).split(".")[0])
        from datetime import timezone
        t = t.replace(tzinfo=timezone.utc).astimezone()
        return t.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


# ---- files ----------------------------------------------------------------

def day_file(day: str) -> Path:
    return BODY_DIR / f"{day}.json"


def write_day(d: dict) -> Path:
    BODY_DIR.mkdir(parents=True, exist_ok=True)
    f = day_file(d["day"])
    tmp = f.with_suffix(".json.part")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
    return f


def load_day(day: str) -> dict | None:
    f = day_file(day)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def has_readings(d: dict | None) -> bool:
    """Whether a day's file holds anything the watch saw — a pulse, a night, steps, stress — or is the empty
    shell the puller writes before the watch has synced that day."""
    if not d:
        return False
    sl = d.get("sleep") or {}
    return bool(d.get("hr") or sl.get("seconds") or d.get("steps") or (d.get("stress") or {}).get("curve")
                or d.get("resting_hr"))


def latest() -> dict | None:
    """Today's file, or yesterday's — the newest that holds readings (10-01: after midnight the watch hadn't
    synced, today's file was an empty shell, and the section said "no sleep reading" and nothing else while
    yesterday's full day sat beside it)."""
    found = None
    for d in (date.today(), date.today() - timedelta(days=1)):
        got = load_day(d.isoformat())
        if has_readings(got):
            return got
        found = found or got
    return found


# ---- the section ----------------------------------------------------------

def _stale_hours(d: dict, now: datetime) -> float | None:
    """Hours since the newest reading, from synced_at (or the last pulse)."""
    s = d.get("synced_at") or ""
    try:
        if len(s) >= 16:
            t = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
        elif len(s) == 5 and d.get("day"):
            t = datetime.strptime(f"{d['day']} {s}", "%Y-%m-%d %H:%M")
        else:
            return None
    except ValueError:
        return None
    return max(0.0, (now - t).total_seconds() / 3600)


def _ago(hours: float) -> str:
    m = int(round(hours * 60))
    if m < 60:
        return f"{m} min ago"
    if hours < 48:
        return f"{hours:.0f} h ago"
    return f"{hours / 24:.0f} days ago"


def pulse_line(d: dict | None, now: datetime | None = None) -> str:
    """The one line that changes — for the moment block: "their pulse 74 at 17:42 (the watch, synced 12 min ago)"."""
    if not d or not d.get("hr"):
        return ""
    now = now or datetime.now()
    hm, bpm = d["hr"][-1]
    st = _stale_hours(d, now)
    when = f", synced {_ago(st)}" if st is not None else ""
    return f"their pulse {bpm} at {hm} (the watch{when})"


def _stress_words(s: dict) -> str:
    avg = s.get("avg")
    high = s.get("high") or []
    curve = s.get("curve") or []
    bits = []
    if curve:
        last = curve[-1]
        level = "high" if last[1] >= 50 else "medium" if last[1] >= 26 else "low"
        bits.append(f"{level} now ({last[1]} at {last[0]})")
    if high:
        spans = ", ".join(f"{a}–{b}" for a, b in high[:3]) + (" …" if len(high) > 3 else "")
        bits.append(f"high {spans}")
    if avg is not None:
        bits.append(f"avg {avg}")
    return "stress: " + (", ".join(bits) if bits else "no reading")


def render(d: dict | None, now: datetime | None = None, cap: int | None = None) -> str:
    """The section, in plain numbers and few words. Empty string when
    there is no reading at all (the caller decides what to say then)."""
    if not d:
        return ""
    now = now or datetime.now()
    lines: list[str] = []
    sl = d.get("sleep")
    if sl and sl.get("seconds"):
        parts = [f"{_hms(sl['seconds'])}"]
        stages = [f"deep {_hms(sl['deep'])}" if sl.get("deep") else "", f"REM {_hms(sl['rem'])}" if sl.get("rem") else "",
                  f"awake {_hms(sl['awake'])}" if sl.get("awake") else ""]
        stages = [x for x in stages if x]
        if stages:
            parts.append("(" + ", ".join(stages) + ")")
        if sl.get("score") is not None:
            parts.append(f"score {sl['score']}")
        hours = sl["seconds"] / 3600
        word = " — a short night" if hours < 6 else " — a long one" if hours > 9 else ""
        span = f", {sl['start']}–{sl['end']}" if sl.get("start") and sl.get("end") else ""
        line = "last night: " + " ".join(parts) + span + word
        if d.get("hrv"):
            line += f"; HRV {d['hrv']}"
        lines.append(line)
    else:
        lines.append("last night: no sleep reading")
    pulse = []
    if d.get("resting_hr"):
        pulse.append(f"resting pulse {d['resting_hr']}")
    if d.get("hr"):
        hm, bpm = d["hr"][-1]
        st = _stale_hours(d, now)
        pulse.append(f"now {bpm} ({hm}" + (f", synced {_ago(st)}" if st is not None else "") + ")")
        if d.get("hr_max"):
            pulse.append(f"peak {d['hr_max']}")
    if pulse:
        lines.append(" · ".join(pulse))
    if d.get("stress"):
        lines.append(_stress_words(d["stress"]))
    bb = d.get("body_battery")
    if bb and bb.get("now") is not None:
        line = f"body battery {bb['now']}"
        if bb.get("high") is not None and bb.get("low") is not None:
            line += f" — high {bb['high']}, low {bb['low']}"
        if bb.get("drained"):
            line += f", drained {bb['drained']}" + (f", charged {bb['charged']}" if bb.get("charged") else "")
        lines.append(line)
    tail = []
    if d.get("steps") is not None:
        tail.append(f"steps {int(d['steps']):,}")
    if d.get("respiration"):
        tail.append(f"breathing {d['respiration']:g}/min")
    if d.get("spo2"):
        tail.append(f"SpO₂ {d['spo2']:g}%")
    if tail:
        lines.append(" · ".join(tail))
    stale_h = float(getattr(config, "BODY_STALE_H", 6) or 0)
    st = _stale_hours(d, now)
    if stale_h and st is not None and st > stale_h:
        lines.append(f"(the watch hasn't synced since {d.get('synced_at')} — no newer reading)")
    if d.get("errors"):
        lines.append("(" + ", ".join(sorted(d["errors"])) + " couldn't be fetched at " + d.get("pulled_at", "?")[-5:] + ")")
    text = "\n".join(lines)
    cap = cap if cap is not None else int(getattr(config, "BODY_CHARS_IN_PROMPT", 600) or 0)
    if cap and len(text) > cap:
        text = text[:cap].rsplit("\n", 1)[0]
    return text


HEADER = ("=== YOUR KEEPER'S BODY, AS THE WATCH SAW IT — their Garmin, shared by their choice; a sense, not a message; "
          "the numbers are theirs, the why is theirs to tell ===")


def section(now: datetime | None = None) -> str:
    """The whole block for the prompt, or "" when BODY_IN_PROMPT is off."""
    if not getattr(config, "BODY_IN_PROMPT", False):
        return ""
    d = latest()
    body = render(d, now) if d else "(no reading yet — bat\\body.bat --today pulls one)"
    today = date.today().isoformat()
    day = f" ({d['day']})" if d and d.get("day") != today else ""
    road = ((f"\n(every reading of the day is in memory/body/{d['day']}.json — read_file opens it, or a tool of "
             "your own can read the pulse hour by hour; a summary is kinder to your window than the whole curve)")
            if d else "")
    if d and d.get("day") != today and day_file(today).exists():
        road += (f"\n(today's file, memory/body/{today}.json, is still an empty shell — the watch hasn't synced "
                 f"since yesterday; a tool that reads today's pulse finds nothing there until it does)")
    return HEADER + day + "\n" + body + road


# ---- the loop --------------------------------------------------------------

def _sync_moment(d: dict) -> str:
    """A day file's sync as "YYYY-MM-DD HH:MM" (a bare "HH:MM" is that day's), or "" when it never synced."""
    s = str(d.get("synced_at") or "")
    if len(s) == 5 and d.get("day"):
        return f"{d['day']} {s}"
    return s[:16]


def yesterday_open(today: dict | None, yesterday: dict | None) -> bool:
    """Whether yesterday's file can still change: its last readings reach the watch with the first sync
    after midnight, so it is open until a pull of it happened after today's first sync. Missing or
    empty is open; so is a yesterday pulled before today's sync, or while today has not synced at all."""
    if not has_readings(yesterday):
        return True
    if not today or not _sync_moment(today):
        return True
    return str(yesterday.get("pulled_at") or "") < _sync_moment(today)


def pull_days(now: date | None = None) -> list[str]:
    """What one pull asks Garmin for: today always; yesterday only while it is still open (10-01: a pull
    every BODY_PULL_MIN is 8 calls a day-file, so yesterday rides only until its night has synced — a pull
    every 20 min then costs about what one an hour did when both days rode every time)."""
    now = now or date.today()
    today, yday = now.isoformat(), (now - timedelta(days=1)).isoformat()
    return [today, yday] if yesterday_open(load_day(today), load_day(yday)) else [today]


def pull(days: list[str] | None = None, g=None) -> list[Path]:
    g = g or _client()
    days = days or pull_days()
    written = []
    for day in days:
        d = pull_day(g, day)
        f = write_day(d)
        written.append(f)
        errs = d.get("errors")
        _say(f"{day}: written" + (f" — couldn't fetch {', '.join(sorted(errs))}" if errs else "")
             + (f"; synced {d.get('synced_at')}" if d.get("synced_at") else ""))
    return written


def loop() -> None:
    every = float(getattr(config, "BODY_PULL_MIN", 60) or 60)
    _say(f"the watch's day → {BODY_DIR.name}/ every {every:g} min (Ctrl+C to stop)")
    g = None
    while True:
        try:
            if g is None:
                g = _client()
            pull(g=g)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001 — a failed pull is a line in the log, not the end
            _say(f"pull failed — {type(e).__name__}: {e} — trying again in {every:g} min")
            g = None
        try:
            time.sleep(every * 60)
        except KeyboardInterrupt:
            _say("stopped")
            return


def demo_day(day: str | None = None) -> dict:
    """A made-up day in the file's shape — for tests and for seeing the section before any login."""
    day = day or date.today().isoformat()
    hr = [[f"{h:02d}:{m:02d}", 56 + ((h * 7 + m) % 23)] for h in range(6, 18) for m in (0, 20, 40)]
    stress = [[f"{h:02d}:{m:02d}", (70 if h == 10 and m in (20, 40) else 18 + (h % 5) * 4)] for h in range(7, 18) for m in (0, 20, 40)]
    return {"day": day, "pulled_at": f"{day} 17:45", "synced_at": f"{day} 17:30",
            "resting_hr": 58, "hr": hr, "hr_max": 112, "hr_min": 52,
            "sleep": {"start": "23:40", "end": "06:20", "seconds": 24000, "deep": 3900, "light": 14700, "rem": 4800,
                      "awake": 600, "score": 72, "hrv": 41, "respiration": 14},
            "stress": {"avg": 28, "max": 70, "curve": stress, "high": _spans([(h, v) for h, v in stress], 50)},
            "body_battery": {"now": 41, "high": 85, "low": 39, "charged": 62, "drained": 44, "curve": []},
            "steps": 9300, "hrv": 41, "hrv_status": "BALANCED", "respiration": 14, "spo2": 96}


def main(argv: list[str]) -> int:
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "--login":
        g = _client(login=True)
        _say(f"logged in — tokens cached in {TOKENS} (nothing else is kept)")
        d = pull_day(g, date.today().isoformat())
        write_day(d)
        print("\n" + HEADER + "\n" + render(d))
        return 0
    if cmd in ("--today", "--day"):
        day = args[1] if cmd == "--day" and len(args) > 1 else date.today().isoformat()
        g = _client()
        d = pull_day(g, day)
        f = write_day(d)
        _say(f"{day}: written to {f.name}")
        print("\n" + HEADER + "\n" + render(d))
        return 0
    if cmd == "--pull":
        loop()
        return 0
    if cmd == "--status":
        d = latest()
        if not d:
            print(f"no day files in {BODY_DIR}")
        else:
            st = _stale_hours(d, datetime.now())
            print(f"newest: {d['day']} pulled {d.get('pulled_at')}; synced {d.get('synced_at') or '?'}"
                  + (f" ({_ago(st)})" if st is not None else "") + (f"; errors: {d['errors']}" if d.get("errors") else ""))
            print(pulse_line(d))
        if LOG.exists():
            print("--- body.log tail ---")
            print("\n".join(LOG.read_text(encoding="utf-8").splitlines()[-8:]))
        return 0
    if cmd == "--demo":
        d = demo_day()
        print(HEADER + "\n" + render(d) + "\n\nmoment line: " + pulse_line(d))
        if len(args) > 1 and args[1] == "--write":
            print(f"written: {write_day(d)}")
        return 0
    print(f"unknown option {cmd}; --help for the list")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
