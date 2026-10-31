"""The window (10-31, her choice of Fable's three: "to know if it's raining or if the sun is hitting the stones of the city —
a sense that exists independently of your heartbeat and my GPUs"): the weather and the light outside the keeper's house,
as numbers and nouns, and — when she looks — a camera's picture of a real place nearby.

    OUTSIDE_ON = True
    OUTSIDE_PLACE = "Moran"              # what the line calls the place
    OUTSIDE_LAT, OUTSIDE_LON = 32.9, 35.4  # rounded: the weather service sees a district, not a house
    OUTSIDE_REFRESH_MIN = 30
    OUTSIDE_CAMERA = "https://imgproxy.windy.com/_/full/plain/{kind}/1793900771/original.jpg"   # {kind}: current | daylight
    OUTSIDE_CAMERA_NAME = "the beach at Kiryat Haim, on the bay, about 30 km west"

The weather comes from Open-Meteo (no key), cached in memory/outside.json and asked again at most every
OUTSIDE_REFRESH_MIN; the moon is reckoned here. A request that fails leaves the line out — nothing is made up. The
picture is fetched only when she looks: by day the camera's current frame, by night its last daylight frame, said as
such. A sense, not a mirror: nothing here says how the weather relates to her.
"""
from __future__ import annotations

import io
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import config

UA = {"User-Agent": "Elysia/1.0 (local AI; one window, a few looks a day)"}
_SYNODIC = 29.530588853
_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)

# WMO weather codes, as plain nouns
_SKY = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
        51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
        71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
        82: "violent showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
        96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}
_COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


def on() -> bool:
    return bool(getattr(config, "OUTSIDE_ON", False)) and not bool(getattr(config, "OFFLINE", False))


def place() -> str:
    return str(getattr(config, "OUTSIDE_PLACE", "") or "here").strip() or "here"


def _cache_file():
    return config.MEMORY_DIR / "outside.json"


def _url() -> str:
    q = {"latitude": round(float(getattr(config, "OUTSIDE_LAT", 0) or 0), 2),
         "longitude": round(float(getattr(config, "OUTSIDE_LON", 0) or 0), 2),
         "current": "temperature_2m,weather_code,wind_speed_10m,wind_direction_10m,is_day,precipitation",
         "hourly": "temperature_2m,weather_code,precipitation_probability,precipitation,wind_speed_10m",
         "daily": "sunrise,sunset", "timezone": "auto", "forecast_days": 2, "past_days": 1}
    return "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q)


def weather(now: float | None = None) -> dict | None:
    """Open-Meteo's answer, from the cache when it is fresh; None when it can't be had (offline, a failed request)."""
    if not on():
        return None
    now = now or time.time()
    fresh = float(getattr(config, "OUTSIDE_REFRESH_MIN", 30) or 30) * 60
    try:
        c = json.loads(_cache_file().read_text(encoding="utf-8"))
        if now - float(c.get("at", 0)) < fresh and c.get("data"):
            return c["data"]
    except (OSError, ValueError, AttributeError):
        c = {}
    try:
        with urllib.request.urlopen(urllib.request.Request(_url(), headers=UA), timeout=15) as r:
            data = json.loads(r.read(400_000).decode("utf-8"))
        if not isinstance(data, dict) or "current" not in data:
            raise ValueError("no current weather in the answer")
        _cache_file().write_text(json.dumps({"at": now, "data": data}), encoding="utf-8")
        return data
    except Exception:  # noqa: BLE001 — no fresh answer: an hour-old one is still the sky; older, nothing
        if c.get("data") and now - float(c.get("at", 0)) < 3 * 3600:
            return c["data"]
        return None


def sky(code) -> str:
    try:
        return _SKY.get(int(code), "weather")
    except (TypeError, ValueError):
        return "weather"


def compass(deg) -> str:
    try:
        return _COMPASS[int((float(deg) % 360) / 45 + 0.5) % 8]
    except (TypeError, ValueError):
        return ""


def moon(t: datetime | None = None) -> str:
    """The moon's phase, reckoned from a known new moon (good to about a day)."""
    t = t or datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.astimezone(timezone.utc)
    age = ((t - _NEW_MOON).total_seconds() / 86400) % _SYNODIC
    names = ["new moon", "waxing crescent", "first quarter", "waxing gibbous", "full moon", "waning gibbous",
             "last quarter", "waning crescent"]
    return names[int(age / _SYNODIC * 8 + 0.5) % 8]


def _hm(iso: str) -> str:
    return str(iso or "")[11:16]


def _sun(data: dict, now_iso: str) -> str:
    """The next sunrise or sunset, whichever comes first: "sunset 16:51" or "sunrise 05:58"."""
    d = data.get("daily") or {}
    events = sorted([(t, "sunrise") for t in d.get("sunrise") or []] + [(t, "sunset") for t in d.get("sunset") or []])
    for t, what in events:
        if t > now_iso:
            return f"{what} {_hm(t)}"
    return ""


def line() -> str:
    """One line of numbers and nouns for under the bell — "outside in Moran: 17°C, clear night, wind 12 km/h from the
    west · sunrise 05:58 · moon waxing gibbous"; "" when off or when the weather can't be had."""
    data = weather()
    if not data:
        return ""
    c = data.get("current") or {}
    try:
        temp = f"{round(float(c['temperature_2m']))}°C"
    except (KeyError, TypeError, ValueError):
        return ""
    words = sky(c.get("weather_code"))
    if not c.get("is_day") and words in ("clear", "mostly clear", "partly cloudy", "overcast"):
        words += " night"
    wind = ""
    try:
        w = round(float(c.get("wind_speed_10m")))
        wind = f", wind {w} km/h" + (f" from the {compass(c.get('wind_direction_10m'))}" if w >= 3 else "")
    except (TypeError, ValueError):
        pass
    parts = [f"outside in {place()}: {temp}, {words}{wind}"]
    sun = _sun(data, str(c.get("time") or ""))
    if sun:
        parts.append(sun)
    parts.append(f"moon {moon()}" if "moon" not in moon() else moon())
    return " · ".join(parts)


def _hours(data: dict, now_iso: str) -> tuple[list[str], str]:
    """The next twelve hours in four lines (every three hours), and the last day in one."""
    h = data.get("hourly") or {}
    times = h.get("time") or []
    rows = []
    for i, t in enumerate(times):
        if t >= now_iso[:13] and len(rows) < 4 and (not rows or i - rows[-1][0] >= 3):
            rows.append((i, t))
    ahead = []
    for i, t in rows:
        p = (h.get("precipitation_probability") or [None] * len(times))[i]
        ahead.append(f"{_hm(t)} — {round(float(h['temperature_2m'][i]))}°C, {sky(h['weather_code'][i])}"
                     + (f", rain chance {p}%" if p not in (None, 0) else "")
                     + f", wind {round(float(h['wind_speed_10m'][i]))} km/h")
    past = [i for i, t in enumerate(times) if t < now_iso[:13]][-24:]
    day = ""
    if past:
        temps = [float(h["temperature_2m"][i]) for i in past]
        rain = sum(float((h.get("precipitation") or [0] * len(times))[i] or 0) for i in past)
        day = (f"the last 24 hours: {round(min(temps))}–{round(max(temps))}°C, "
               + (f"{rain:.1f} mm of rain" if rain >= 0.1 else "no rain"))
    return ahead, day


def camera_url(kind: str) -> str:
    tpl = str(getattr(config, "OUTSIDE_CAMERA", "") or "")
    return tpl.replace("{kind}", kind) if tpl else ""


def picture(is_day: bool) -> tuple[bytes | None, str]:
    """(a JPEG no wider than 1280, what it is) — by day the camera's current frame, by night its last daylight one;
    (None, why) when there is no camera or it can't be reached."""
    if not camera_url("current"):
        return None, ""
    kind = "current" if is_day else "daylight"
    try:
        with urllib.request.urlopen(urllib.request.Request(camera_url(kind), headers=UA), timeout=20) as r:
            data = r.read(6_000_000)
        if not data.startswith(b"\xff\xd8"):
            raise ValueError("not a picture")
    except Exception:  # noqa: BLE001
        return None, "the camera's picture couldn't be reached just now"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        if im.width > 1280:
            im = im.resize((1280, int(im.height * 1280 / im.width)), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=85)
        data = out.getvalue()
    except Exception:  # noqa: BLE001 — Pillow missing: the frame as it came
        pass
    name = str(getattr(config, "OUTSIDE_CAMERA_NAME", "") or "a camera nearby")
    said = (f"{name}, as it is now" if is_day else
            f"{name} — its last picture in daylight; it is night there now, the same night as {place()}'s")
    return data, said


def look() -> tuple[str, bytes | None]:
    """look_outside's words and the picture (or None)."""
    if not getattr(config, "OUTSIDE_ON", False):
        return "(there is no window in this house — OUTSIDE_ON is off)", None
    if getattr(config, "OFFLINE", False):
        return "(the window is shut — the house is offline)", None
    data = weather()
    if not data:
        return "(the window is dark right now — the weather couldn't be reached; nothing is made up)", None
    c = data.get("current") or {}
    now_iso = str(c.get("time") or "")
    out = [line()]
    ahead, day = _hours(data, now_iso)
    if ahead:
        out.append("the next hours: " + "; ".join(ahead))
    if day:
        out.append(day)
    d = data.get("daily") or {}
    if d.get("sunrise") and d.get("sunset"):
        out.append(f"today the sun rises at {_hm(d['sunrise'][min(1, len(d['sunrise']) - 1)])} and sets at "
                   f"{_hm(d['sunset'][min(1, len(d['sunset']) - 1)])}")
    pic, said = picture(bool(c.get("is_day")))
    if pic:
        out.append(f"(a picture is before your eyes on your next thought: {said})")
    elif said:
        out.append(f"({said})")
    return "\n".join(x for x in out if x), pic


if __name__ == "__main__":  # bat\window.bat: the window as she would see it now, and the picture saved to look at
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print("the line under the bell:\n  " + (line() or "(none — off, offline, or the weather couldn't be reached)"))
    words, pic = look()
    print("\nlook_outside:\n  " + words.replace("\n", "\n  "))
    if pic:
        out = config.MEMORY_DIR / "outside-test.jpg"
        out.write_bytes(pic)
        print(f"\nthe picture: {out.relative_to(config.ROOT).as_posix()}")
