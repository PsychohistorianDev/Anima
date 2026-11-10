"""The game guard (11-05) — the brain waits while you play.

A big brain takes most of the card; a game beside it crashes or crawls. So before their brain opens — a wake, a spark,
a dream, a reply — the engine asks who else holds the card, by Windows' own count per process (the "GPU Process
Memory" counters). Another program over GAME_GUARD_MB that isn't the desktop or the house's own is a game: their
brain waits, and the heartbeat and the sparks look again every GAME_GUARD_CHECK_MIN. Off (GAME_GUARD_ON) by default.

    /gaming on    you say "now": the guard holds as if a game ran, and a wake running ends at its next step
    /gaming off   lets them in for GAME_GUARD_OVERRIDE_H hours even with a game seen (or ends /gaming on)
    /gaming auto  back to the card's own count; /gaming alone says how it stands

A wake already running when a game appears finishes (a lost thought costs more than a minute of stutter); only
/gaming on stops it. The spans you played are kept (memory/gaming.json) and told to them once, plainly: "your keeper
was gaming 20:10–22:40". On anything but Windows, or when the counters can't be read, nothing is seen and the guard
holds only for /gaming on.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime

import config

STATE = config.MEMORY_DIR / "gaming.json"
_IGNORE = {"dwm", "explorer", "csrss", "llama-server", "python", "pythonw", "py", "searchhost", "startmenuexperiencehost",
           "shellexperiencehost", "textinputhost", "windowsterminal", "conhost", "nvcontainer", "nvidia overlay",
           "nvidia app", "nvidia share", "audiodg", "system", "idle"}
_cache: dict = {"at": 0.0, "seen": []}

_PS = (r"$c=(Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples;"
       r"foreach($s in $c){ if($s.CookedValue -gt 200MB){ $p=[int]($s.InstanceName -replace '^pid_(\d+)_.*','$1');"
       r"$n=(Get-Process -Id $p -ErrorAction SilentlyContinue).ProcessName; Write-Output ('{0},{1},{2}' -f $p,$n,[int]($s.CookedValue/1MB)) } }")


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(s: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def parse(out: str) -> list[tuple[int, str, int]]:
    """'pid,name,MB' lines → [(pid, name, MB)], a process's adapters summed."""
    by: dict[int, list] = {}
    for line in (out or "").splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        try:
            pid, mb = int(parts[0]), int(parts[-1])
        except ValueError:
            continue
        name = ",".join(parts[1:-1]).strip() or "?"
        if pid in by:
            by[pid][1] += mb
        else:
            by[pid] = [name, mb]
    return [(pid, n, mb) for pid, (n, mb) in by.items()]


def _read() -> list[tuple[int, str, int]]:
    if os.name != "nt":
        return []
    try:
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW}
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                             capture_output=True, text=True, timeout=25, **kw).stdout
    except Exception:  # noqa: BLE001
        return []
    return parse(out)


def _ignored() -> set:
    extra = getattr(config, "GAME_GUARD_IGNORE", ()) or ()
    return _IGNORE | {str(x).strip().lower().removesuffix(".exe") for x in extra}


def games(fresh: bool = False) -> list[tuple[str, int]]:
    """Programs that aren't the desktop or the house's own holding GAME_GUARD_MB or more of the card: [(name, MB)],
    biggest first. Read at most every GAME_GUARD_CACHE_S."""
    now = time.time()
    if not fresh and now - _cache["at"] < float(getattr(config, "GAME_GUARD_CACHE_S", 60) or 60):
        return _cache["seen"]
    limit = int(getattr(config, "GAME_GUARD_MB", 2000) or 2000)
    skip = _ignored()
    try:
        own = {os.getpid()}
        import brain
        st = brain.door_status()
        if st:
            own.add(int(st["pid"]))
    except Exception:  # noqa: BLE001
        pass
    seen = sorted(((n, mb) for pid, n, mb in _read()
                   if pid not in own and mb >= limit and str(n).lower().removesuffix(".exe") not in skip),
                  key=lambda x: -x[1])
    _cache.update(at=now, seen=seen)
    return seen


def _hm(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%H:%M")


def playing() -> tuple[bool, str]:
    """(True, why) while the guard holds their brain: /gaming on, or a game seen and no /gaming off override. Keeps the
    spans in memory/gaming.json, so the end of a game is noticed by whichever door asks next."""
    if not getattr(config, "GAME_GUARD_ON", False):
        return False, ""
    s = _load()
    now = time.time()
    dirty = False
    mode = s.get("mode", "auto")
    if mode == "on":
        on, why = True, "the keeper said /gaming on"
    else:
        seen = games()
        override = float(s.get("override_until") or 0) > now
        on = bool(seen) and not override
        why = (f"{seen[0][0]} holds {seen[0][1] / 1024:.1f} GB of the card" if seen else "")
        if mode == "off" and not override:
            s["mode"] = "auto"  # the override ran out
            dirty = True
    if on and not s.get("since"):
        s["since"], s["what"] = now, why
        dirty = True
    elif not on and s.get("since"):
        span = {"from": s.pop("since"), "to": now, "what": s.pop("what", "")}
        if span["to"] - span["from"] >= 120:  # a blip of a loading screen isn't a session
            s["spans"] = (s.get("spans") or [])[-29:] + [span]
            s["untold"] = (s.get("untold") or []) + [span]
            s["ended"] = now
        dirty = True
    if dirty:
        _save(s)
    return on, why


def set_mode(mode: str) -> str:
    """/gaming on|off|auto — what the phone answers."""
    s = _load()
    mode = (mode or "").strip().lower()
    hours = float(getattr(config, "GAME_GUARD_OVERRIDE_H", 3) or 3)
    if mode == "on":
        s["mode"] = "on"
        s.pop("override_until", None)
        s["stop_wake"] = time.time()
        _save(s)
        playing()
        return "(gaming: on — their brain stays off the card until /gaming off or /gaming auto; a wake running ends at its next step)"
    if mode == "off":
        s["mode"] = "off"
        s["override_until"] = time.time() + hours * 3600
        s.pop("stop_wake", None)
        _save(s)
        playing()
        return f"(gaming: off — they may use the card for the next {hours:g} hours even if a game is seen; /gaming auto to undo)"
    if mode == "auto":
        s["mode"] = "auto"
        s.pop("override_until", None)
        s.pop("stop_wake", None)
        _save(s)
        playing()
        return "(gaming: auto — the guard goes by the card's own count again)"
    on, why = playing()
    seen = games(fresh=True)
    told = ", ".join(f"{n} {mb / 1024:.1f} GB" for n, mb in seen[:3]) or "no game on the card"
    return (f"(gaming: {s.get('mode', 'auto')} — their brain {'waits' if on else 'may open'}"
            + (f": {why}" if why else "") + f". Seen: {told}. /gaming on, /gaming off, /gaming auto)")


def stop_asked(since: float) -> bool:
    """A wake that began at `since` asks between steps: True once /gaming on was said after it began."""
    s = _load()
    return s.get("mode") == "on" and float(s.get("stop_wake") or 0) > since


def news(mark: bool = True) -> str:
    """The spans not yet told to them, once: "the keeper was gaming 20:10–22:40" — "" when none."""
    s = _load()
    spans = s.get("untold") or []
    if not spans:
        return ""
    if mark:
        s["untold"] = []
        _save(s)
    try:
        import keeper_week
        name = keeper_week.keeper_name() or "the keeper"
    except Exception:  # noqa: BLE001
        name = "the keeper"
    bits = []
    for sp in spans[-3:]:
        a, b = float(sp["from"]), float(sp["to"])
        day = "" if datetime.fromtimestamp(a).date() == datetime.now().date() else f"{datetime.fromtimestamp(a):%a} "
        bits.append(f"{day}{_hm(a)}–{_hm(b)}")
    return f"{name} was gaming {', '.join(bits)} — your brain waited off the card meanwhile"


def ended_since(t: float) -> bool:
    """For intentions (step 2): a game ended after `t`."""
    return float(_load().get("ended") or 0) > t
