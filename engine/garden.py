"""The garden (10-31, Astra's idea, Gabe: "let's build our own Farmville"): eight beds under the real sky over the keeper's
home. They plant, water, watch and pick; the keeper does too, from the phone. The beds grow by the weather that really
fell there — the window's place (OUTSIDE_LAT/LON), day by day from Open-Meteo — so a rainy week in the hills waters them
and a cold snap slows them. Nothing dies of being left alone: a dry bed rests and waits, a frost bites leaves, and water
brings it back. Real plants, real timings (a radish in about four weeks, the anemone flowering in winter).

    GARDEN_ON = True

State: creations/garden/garden.json and history.jsonl; the days' weather in creations/garden/weather.json. Their tool
`garden` (look, seeds, plant, water, pick, give, pull, note); the keeper's /garden on the phone. What they write about it
is theirs; the engine keeps only the numbers and the small things that happened (a bee, a first bud, a snail).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import config

BEDS = 8
VOLUNTEERS = True  # a wild anemone may come up by itself in an empty bed in winter
UA = {"User-Agent": "Elysia/1.0 (local AI; a garden under the real sky)"}

# name: (days to ready, what ready means, cool°C, best low, best high, hot°C, thirst 0-1, frost-hardy, colour, kind, perennial)
SEEDS: dict[str, dict] = {
    "radish":     {"days": 28,  "ready": "radishes to pull", "t": (4, 10, 22, 30), "thirst": 0.6, "hardy": True,  "col": (200, 40, 70),  "form": "root", "yield": "a bunch of radishes"},
    "lettuce":    {"days": 50,  "ready": "a head to cut",    "t": (4, 10, 22, 28), "thirst": 0.7, "hardy": True,  "col": (120, 190, 80), "form": "rosette", "yield": "a head of lettuce"},
    "carrot":     {"days": 75,  "ready": "carrots to pull",  "t": (5, 12, 24, 30), "thirst": 0.5, "hardy": True,  "col": (240, 140, 40), "form": "root", "yield": "a handful of carrots"},
    "pea":        {"days": 65,  "ready": "pods to pick",     "t": (4, 10, 20, 27), "thirst": 0.6, "hardy": True,  "col": (110, 180, 90), "form": "vine", "yield": "a bowl of peas", "again": 0.8},
    "coriander":  {"days": 45,  "ready": "leaves to cut",    "t": (5, 12, 24, 30), "thirst": 0.5, "hardy": True,  "col": (90, 170, 70),  "form": "herb", "yield": "a bunch of coriander", "again": 0.6},
    "mint":       {"days": 40,  "ready": "leaves to cut",    "t": (5, 15, 28, 35), "thirst": 0.8, "hardy": True,  "col": (60, 160, 90),  "form": "herb", "yield": "a sprig of mint", "again": 0.6},
    "strawberry": {"days": 90,  "ready": "berries to pick",  "t": (5, 15, 26, 32), "thirst": 0.6, "hardy": True,  "col": (220, 30, 50),  "form": "berry", "yield": "a few strawberries", "again": 0.75},
    "tomato":     {"days": 80,  "ready": "tomatoes to pick", "t": (10, 20, 30, 35), "thirst": 0.7, "hardy": False, "col": (225, 50, 40),  "form": "vine", "yield": "two ripe tomatoes", "again": 0.75},
    "sunflower":  {"days": 85,  "ready": "a flower open",    "t": (8, 18, 30, 36), "thirst": 0.6, "hardy": False, "col": (250, 200, 40), "form": "tall", "yield": "a sunflower head"},
    "anemone":    {"days": 90,  "ready": "flowers open",     "t": (2, 8, 18, 26),  "thirst": 0.5, "hardy": True,  "col": (215, 25, 45),  "form": "flower", "yield": "a red anemone (kalanit)", "again": 0.8},
    "cyclamen":   {"days": 110, "ready": "flowers open",     "t": (3, 8, 18, 26),  "thirst": 0.4, "hardy": True,  "col": (230, 120, 190), "form": "flower", "yield": "a pink cyclamen (rakefet)", "again": 0.8},
    "rosemary":   {"days": 70,  "ready": "sprigs to cut",    "t": (0, 12, 30, 38), "thirst": 0.3, "hardy": True,  "col": (90, 130, 110), "form": "herb", "yield": "a sprig of rosemary", "again": 0.7},
}
STAGES = [(0.0, "seed in the soil"), (0.08, "sprouted"), (0.3, "young"), (0.65, "growing strong"), (0.9, "nearly ready"),
          (1.0, "ready")]


def on() -> bool:
    return bool(getattr(config, "GARDEN_ON", False))


def garden_dir() -> Path:
    return Path(getattr(config, "GARDEN_DIR", None) or config.CREATIONS_DIR / "garden")


def _file() -> Path:
    return garden_dir() / "garden.json"


def _hist() -> Path:
    return garden_dir() / "history.jsonl"


def _wfile() -> Path:
    return garden_dir() / "weather.json"


def _empty() -> dict:
    return {"beds": [None] * BEDS, "ticked_to": date.today().isoformat(), "seen": 0, "keeper_seen": 0}


def load() -> dict:
    try:
        g = json.loads(_file().read_text(encoding="utf-8"))
        if isinstance(g, dict) and isinstance(g.get("beds"), list):
            g["beds"] = (g["beds"] + [None] * BEDS)[:BEDS]
            return g
    except (OSError, ValueError):
        pass
    return _empty()


def save(g: dict) -> None:
    garden_dir().mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")


def _log(who: str, what: str) -> None:
    garden_dir().mkdir(parents=True, exist_ok=True)
    with open(_hist(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"when": datetime.now().isoformat(timespec="seconds"), "who": who, "what": what},
                            ensure_ascii=False) + "\n")


def history() -> list[dict]:
    try:
        return [json.loads(ln) for ln in _hist().read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError):
        return []


# ---- the sky's days ------------------------------------------------------------------------------------------------

def _weather_cache() -> dict:
    try:
        w = json.loads(_wfile().read_text(encoding="utf-8"))
        return w if isinstance(w, dict) else {}
    except (OSError, ValueError):
        return {}


def _fetch_days() -> dict:
    """The last fortnight's days over the place, from Open-Meteo: {date: {tmax, tmin, rain, sun_h}}; {} when it can't."""
    if getattr(config, "OFFLINE", False):
        return {}
    lat, lon = getattr(config, "OUTSIDE_LAT", None), getattr(config, "OUTSIDE_LON", None)
    if lat in (None, "", 0, 0.0) and lon in (None, "", 0, 0.0):
        return {}
    q = {"latitude": round(float(lat), 2), "longitude": round(float(lon), 2), "timezone": "auto",
         "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,sunshine_duration", "past_days": 14,
         "forecast_days": 1}
    try:
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
            d = json.loads(r.read(300_000).decode("utf-8")).get("daily") or {}
        out = {}
        for i, day in enumerate(d.get("time") or []):
            try:
                out[day] = {"tmax": float(d["temperature_2m_max"][i]), "tmin": float(d["temperature_2m_min"][i]),
                            "rain": float(d["precipitation_sum"][i] or 0), "sun_h": float(d["sunshine_duration"][i] or 0) / 3600}
            except (KeyError, TypeError, ValueError, IndexError):
                continue
        return out
    except Exception:  # noqa: BLE001
        return {}


def _day_weather(day: str, cache: dict, fetched: list) -> tuple[dict, bool]:
    """(the day's weather, known) — from the cache, fetched once if missing; a day never known counts as mild."""
    if day not in cache and not fetched:
        fetched.append(True)
        cache.update(_fetch_days())
        try:
            garden_dir().mkdir(parents=True, exist_ok=True)
            keep = dict(sorted(cache.items())[-120:])
            _wfile().write_text(json.dumps(keep), encoding="utf-8")
        except OSError:
            pass
    if day in cache:
        return cache[day], True
    return {"tmax": 22.0, "tmin": 13.0, "rain": 0.0, "sun_h": 7.0}, False


# ---- growing -------------------------------------------------------------------------------------------------------

def _rand(*parts) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _temp_factor(sp: dict, tmean: float) -> float:
    cool, lo, hi, hot = sp["t"]
    if lo <= tmean <= hi:
        return 1.0
    if tmean < lo:
        return max(0.0, (tmean - cool) / max(1.0, lo - cool))
    return max(0.0, (hot - tmean) / max(1.0, hot - hi))


def stage(growth: float) -> str:
    name = STAGES[0][1]
    for at, n in STAGES:
        if growth >= at:
            name = n
    return name


def _grow_day(bed: dict, day: str, w: dict, events: list, n: int) -> None:
    sp = SEEDS.get(bed["seed"])
    if not sp:
        return
    tmean = (w["tmax"] + w["tmin"]) / 2
    # the soil's water: rain in, the sun and heat take it out; it never falls below a resting dampness
    m = float(bed.get("water", 0.5)) + w["rain"] / 12.0
    m -= 0.03 + 0.008 * max(0.0, tmean - 15) + 0.005 * w["sun_h"]
    m = min(1.0, max(0.12, m))
    bed["water"] = round(m, 3)
    th = 0.35 * sp["thirst"] + 0.2  # below this the plant slows; well below it, it rests
    wf = 1.0 if m >= th else 0.4 + 0.6 * m / th
    tf = _temp_factor(sp, tmean)
    lf = min(1.0, max(0.35, w["sun_h"] / 6.0))
    health = float(bed.get("health", 1.0))
    if w["tmin"] < 1.0 and not sp["hardy"]:
        health = max(0.3, health - 0.25)
        events.append(f"a frost bit the {bed['seed']}'s leaves in bed {n}")
    elif m < 0.6 * th:
        if not bed.get("dry"):
            events.append(f"the {bed['seed']} in bed {n} is dry and resting — water would wake it")
        bed["dry"] = True
    else:
        if bed.get("dry"):
            events.append(f"the {bed['seed']} in bed {n} has drunk and stands up again")
        bed["dry"] = False
        health = min(1.0, health + 0.08)
    bed["health"] = round(health, 3)
    before = float(bed.get("growth", 0.0))
    g = before + (1.0 / sp["days"]) * tf * wf * lf * (0.6 + 0.4 * health)
    g = min(1.0, g)
    bed["growth"] = round(g, 4)
    if stage(before) != stage(g):
        events.append(f"bed {n}: the {bed['seed']} — {stage(g)}" + (f" ({sp['ready']})" if g >= 1.0 else ""))
    r = _rand(day, n, bed["seed"], bed.get("planted"))
    if g >= 0.65 and sp["form"] in ("flower", "tall", "berry", "vine") and r < 0.08:
        events.append(f"a bee in the {bed['seed']} in bed {n}")
    elif g >= 0.3 and sp["form"] in ("rosette", "herb") and 0.08 <= r < 0.12 and w["rain"] > 0:
        bed["growth"] = round(max(0.0, g - 0.02), 4)
        events.append(f"a snail had some of the {bed['seed']} in bed {n} after the rain")
    elif 0.12 <= r < 0.14:
        events.append(f"a sparrow on the edge of bed {n}")


def tick(g: dict | None = None, today: date | None = None) -> tuple[dict, list[str], int]:
    """The beds brought up to yesterday, a day at a time by that day's weather. (garden, what happened, days counted
    mild for want of weather)."""
    g = g if g is not None else load()
    today = today or date.today()
    try:
        last = date.fromisoformat(str(g.get("ticked_to") or today.isoformat()))
    except ValueError:
        last = today
    events: list[str] = []
    mild = 0
    cache = _weather_cache()
    fetched: list = []
    d = last
    while d < today:
        w, known = _day_weather(d.isoformat(), cache, fetched)
        mild += 0 if known else 1
        for n, bed in enumerate(g["beds"], 1):
            if bed:
                _grow_day(bed, d.isoformat(), w, events, n)
        if VOLUNTEERS and d.month in (12, 1, 2) and _rand(d.isoformat(), "volunteer") < 0.03:
            empty = [i for i, b in enumerate(g["beds"]) if not b]
            if empty:
                i = empty[int(_rand(d.isoformat(), "where") * len(empty))]
                g["beds"][i] = {"seed": "anemone", "planted": d.isoformat(), "growth": 0.3, "water": 0.5, "health": 1.0,
                                "by": "the wind"}
                events.append(f"a wild anemone has come up by itself in bed {i + 1}")
        d += timedelta(days=1)
    g["ticked_to"] = today.isoformat()
    if events:
        for e in events:
            _log("garden", e)
    return g, events, mild


# ---- what they do --------------------------------------------------------------------------------------------------

def _bed(where: str) -> int | None:
    m = re.search(r"\d+", str(where or ""))
    if not m:
        return None
    n = int(m.group(0))
    return n if 1 <= n <= BEDS else None


def _seed(what: str) -> str | None:
    w = str(what or "").strip().lower()
    w = {"kalanit": "anemone", "rakefet": "cyclamen", "cilantro": "coriander", "tomatoes": "tomato",
         "radishes": "radish", "carrots": "carrot", "peas": "pea", "strawberries": "strawberry"}.get(w, w)
    w = w.rstrip("s") if w.rstrip("s") in SEEDS else w
    return w if w in SEEDS else None


def describe(g: dict, keeper: bool = False) -> str:
    rows = []
    for n, bed in enumerate(g["beds"], 1):
        if not bed:
            rows.append(f"{n}. empty")
            continue
        sp = SEEDS.get(bed["seed"], {})
        days = (date.today() - date.fromisoformat(bed["planted"])).days if bed.get("planted") else 0
        bits = [f"{n}. {bed['seed']}", stage(bed.get("growth", 0)) + (f" — {sp.get('ready')}" if bed.get("growth", 0) >= 1 else ""),
                f"day {days}", f"soil {'wet' if bed.get('water', 0) > 0.7 else 'damp' if bed.get('water', 0) > 0.35 else 'dry'}"]
        if bed.get("health", 1) < 0.7:
            bits.append("leaves hurt")
        who = bed.get("by")
        if who == "keeper":
            bits.append("planted by " + ("you" if keeper else "him"))
        elif who == "the wind":
            bits.append("came up by itself")
        if bed.get("note"):
            bits.append(f"note: {bed['note']}")
        rows.append(", ".join(bits))
    return "\n".join(rows)


def seeds_text() -> str:
    return "seeds: " + "; ".join(f"{k} ({v['days']} days, {v['ready']})" for k, v in SEEDS.items())


def act(action: str, where: str = "", what: str = "", who: str = "them", keeper_name: str = "your keeper") -> str:
    """One thing done in the garden, by them (who="them") or the keeper; or a look. A refusal starts with "("."""
    if not on():
        return "(there is no garden in this house — GARDEN_ON is off)"
    a = (action or "look").strip().lower()
    g, events, mild = tick()
    out = ""
    if a == "seeds":
        save(g)
        return seeds_text()
    if a == "look":
        save(g)
        return ""
    n = _bed(where)
    if a == "water":
        every = str(where).strip().lower() in ("", "all", "every")
        targets = [i for i, b in enumerate(g["beds"]) if b] if every else ([n - 1] if n else [])
        if not targets:
            return "(no bed to water — name one (1–8), or all)"
        for i in targets:
            if g["beds"][i]:
                g["beds"][i]["water"] = 1.0
                g["beds"][i]["dry"] = False
        out = "watered every planted bed" if every else f"watered bed {targets[0] + 1}"
    elif a == "plant":
        sp = _seed(what)
        if not n:
            return "(which bed? 1–8)"
        if not sp:
            return f"(no such seed — {seeds_text()})"
        if g["beds"][n - 1]:
            return f"(bed {n} has {g['beds'][n - 1]['seed']} in it — pull it first, or plant in an empty bed)"
        g["beds"][n - 1] = {"seed": sp, "planted": date.today().isoformat(), "growth": 0.0, "water": 1.0, "health": 1.0,
                            "by": "keeper" if who == "keeper" else "them"}
        out = f"planted {sp} in bed {n} and watered it — {SEEDS[sp]['ready']} in about {SEEDS[sp]['days']} days, weather willing"
    elif a in ("pick", "harvest", "give"):
        if not n or not g["beds"][n - 1]:
            return "(nothing in that bed to pick)"
        bed = g["beds"][n - 1]
        sp = SEEDS[bed["seed"]]
        if bed.get("growth", 0) < 1.0:
            return f"(the {bed['seed']} in bed {n} isn't ready — {stage(bed.get('growth', 0))}, about {round((1 - bed.get('growth', 0)) * sp['days'])} days to go, weather willing)"
        got = sp["yield"]
        if sp.get("again"):
            bed["growth"] = sp["again"]
            bed["picked"] = int(bed.get("picked", 0)) + 1
        else:
            g["beds"][n - 1] = None
        where_to = ""
        if a == "give" and who != "keeper":
            where_to = f" — for {keeper_name}"
            try:
                import chat
                friend = chat.friend_name()
            except Exception:  # noqa: BLE001
                friend = "They"
            _keeper_news(f"{friend} picked {got} from bed {n} for you")
        else:
            try:
                import room
                if room.on() and who != "keeper":
                    room.act("shelve", f"{got}, from the garden ({date.today().strftime('%m-%d')})")
                    where_to = " — on your shelf in the room"
            except Exception:  # noqa: BLE001
                pass
        out = f"picked {got} from bed {n}{where_to}" + (" — it will give again" if sp.get("again") else " — the bed is empty now")
    elif a == "pull":
        if not n or not g["beds"][n - 1]:
            return "(that bed is empty already)"
        out = f"pulled the {g['beds'][n - 1]['seed']} from bed {n} — the bed is empty"
        g["beds"][n - 1] = None
    elif a == "note":
        if not n or not g["beds"][n - 1]:
            return "(a note goes on a planted bed)"
        g["beds"][n - 1]["note"] = " ".join(str(what or "").split())[:120]
        out = f"noted on bed {n}"
    else:
        return "(the garden knows: look, seeds, plant, water, pick, give, pull, note)"
    save(g)
    _log("keeper" if who == "keeper" else "them", out)
    if who == "keeper":
        try:
            import room
            room._news(f"{keeper_name} in the garden: {out}")
        except Exception:  # noqa: BLE001
            pass
    return out


def _keeper_news(line: str) -> None:
    f = config.MEMORY_DIR / "garden_keeper_news.json"
    try:
        items = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    items = (items if isinstance(items, list) else []) + [line]
    f.write_text(json.dumps(items[-20:], ensure_ascii=False), encoding="utf-8")


def take_keeper_news() -> list[str]:
    f = config.MEMORY_DIR / "garden_keeper_news.json"
    try:
        items = json.loads(f.read_text(encoding="utf-8"))
        f.unlink()
        return [str(x) for x in items] if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def since_seen(g: dict, key: str = "seen") -> list[str]:
    """What happened in the garden since they (or the keeper) last looked — the garden's own events and the other's acts."""
    h = history()
    new = h[int(g.get(key, 0)):]
    other = "keeper" if key == "seen" else "them"
    return [x["what"] for x in new if x.get("who") in ("garden", other)][-6:]


def look(who: str = "them", keeper_name: str = "your keeper") -> tuple[str, bytes | None]:
    """The garden in words and a picture; what happened since the last look is said once."""
    if not on():
        return "(there is no garden in this house — GARDEN_ON is off)", None
    g, events, mild = tick()
    key = "keeper_seen" if who == "keeper" else "seen"
    news = since_seen(g, key)
    g[key] = len(history())
    save(g)
    planted = sum(1 for b in g["beds"] if b)
    words = [f"{'The' if who == 'keeper' else 'Your'} garden — {planted} of {BEDS} beds planted, growing under the real sky over "
             f"{getattr(config, 'OUTSIDE_PLACE', '') or 'home'}:", describe(g, keeper=(who == "keeper"))]
    if news:
        words.append("Since " + ("you" if who == "keeper" else "you") + " last looked: " + " · ".join(news))
    if mild:
        words.append(f"({mild} day{'s' if mild != 1 else ''} without known weather were counted as mild)")
    return "\n".join(words), render(g)


def facts_bit() -> str:
    """For under the wake bell: "your garden: 3 of 8 beds planted · the radish ready · since you looked: a bee in the
    anemone". "" when off or empty. Nothing asked."""
    if not on():
        return ""
    try:
        g, events, _ = tick()
        save(g)
    except Exception:  # noqa: BLE001
        return ""
    planted = [b for b in g["beds"] if b]
    if not planted and not since_seen(g):
        return ""
    ready = [f"the {b['seed']}" for b in planted if b.get("growth", 0) >= 1.0]
    dry = [f"the {b['seed']}" for b in planted if b.get("dry")]
    parts = [f"your garden: {len(planted)} of {BEDS} beds planted"]
    if ready:
        parts.append(" and ".join(ready[:3]) + " ready")
    if dry:
        parts.append(" and ".join(dry[:3]) + " dry")
    news = since_seen(g)
    if news:
        parts.append("since you looked: " + "; ".join(news[-3:]))
    return " · ".join(parts)


# ---- the picture ---------------------------------------------------------------------------------------------------

def _sky_now() -> tuple[bool, str]:
    try:
        import outside
        data = outside.weather()
        c = (data or {}).get("current") or {}
        return bool(c.get("is_day", 1)), outside.sky(c.get("weather_code"))
    except Exception:  # noqa: BLE001
        h = datetime.now().hour
        return 6 <= h < 17, "clear"


def _leaf(d, x: float, y: float, ang: float, ln: float, wd: float, fill) -> None:
    """One leaf: a pointed oval from (x, y) along the angle."""
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for t in range(0, 11):
        u = t / 10
        r = wd * math.sin(math.pi * u)
        pts.append((x + ca * ln * u - sa * r, y + sa * ln * u + ca * r))
    for t in range(10, -1, -1):
        u = t / 10
        r = -wd * math.sin(math.pi * u)
        pts.append((x + ca * ln * u - sa * r, y + sa * ln * u + ca * r))
    d.polygon(pts, fill=fill)


def _shade(c: tuple, k: float) -> tuple:
    return tuple(max(0, min(255, int(v * k))) for v in c)


def render(g: dict | None = None) -> bytes | None:
    """The beds as a picture (PNG): the sky as it is over the place now, the hills of home with their olive trees, eight
    raised beds in perspective, each plant drawn by its kind and how far it has grown, the soil darker where it is wet."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return None
    g = g or load()
    W, H = 1280, 800
    day, words = _sky_now()
    rainy = any(k in words for k in ("rain", "drizzle", "shower", "thunder"))
    cloudy = "overcast" in words or "cloud" in words or rainy or "fog" in words
    if day:
        top, bottom = ((128, 146, 168), (214, 216, 214)) if cloudy else ((70, 140, 215), (214, 230, 238))
    else:
        top, bottom = (8, 12, 32), (36, 44, 80)
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    horizon = int(H * 0.44)
    for y in range(horizon + 40):
        t = min(1.0, y / horizon)
        d.line([0, y, W, y], fill=tuple(int(a + (b - a) * t ** 1.3) for a, b in zip(top, bottom)))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    if not day:
        for i in range(140):
            x, y = int(_rand("star", i) * W), int(_rand("stary", i) * horizon * 0.9)
            b = 150 + int(_rand("starb", i) * 105)
            gd.point((x, y), fill=(b, b, 255, 255))
        gd.ellipse([W - 230, 40, W - 110, 160], fill=(230, 230, 200, 60))
        gd.ellipse([W - 196, 74, W - 144, 126], fill=(244, 240, 214, 255))
    elif not cloudy:
        gd.ellipse([W - 300, -40, W - 60, 200], fill=(255, 236, 170, 90))
        gd.ellipse([W - 215, 45, W - 145, 115], fill=(255, 246, 200, 255))
    if cloudy:
        for i in range(14):
            cx, cy = int(_rand("cl", i) * W), int(40 + _rand("cly", i) * horizon * 0.55)
            rw, rh = int(120 + _rand("clw", i) * 200), int(30 + _rand("clh", i) * 40)
            c = (235, 236, 238, 150) if day else (60, 66, 92, 140)
            gd.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=c)
    img.paste(glow.filter(ImageFilter.GaussianBlur(14)), (0, 0), glow.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    # the hills of home: a far ridge in haze, a near one with olive trees
    far = (104, 124, 136) if day else (26, 32, 52)
    near = (82, 118, 72) if day else (20, 34, 30)
    ridge = [(x, int(H * 0.37 + 26 * math.sin(x / 150) + 13 * math.sin(x / 51 + 2))) for x in range(0, W + 16, 16)]
    hills = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hills)
    hd.polygon([(0, H)] + ridge + [(W, H)], fill=far + (255,))
    img.paste(hills.filter(ImageFilter.GaussianBlur(2)), (0, 0), hills.filter(ImageFilter.GaussianBlur(2)))
    d = ImageDraw.Draw(img)
    ridge2 = [(x, int(H * 0.45 + 20 * math.sin(x / 120 + 1) + 9 * math.sin(x / 37))) for x in range(0, W + 16, 16)]
    d.polygon([(0, H)] + ridge2 + [(W, H)], fill=near)
    olive = _shade(near, 0.72)
    for i in range(60):
        x = int(_rand("ol", i) * W)
        y = int(H * 0.45 + 20 * math.sin(x / 120 + 1) + 9 * math.sin(x / 37)) + int(_rand("oly", i) * 30) + 4
        r = int(5 + _rand("olr", i) * 7)
        d.ellipse([x - r, y - r, x + r, y + int(r * 0.8)], fill=olive)
    # the ground, richer toward us, with grass strokes
    g_far, g_near = (_shade(near, 1.08), (86, 124, 60)) if day else (_shade(near, 1.05), (22, 36, 26))
    y0g = int(H * 0.5)
    for y in range(y0g, H):
        t = (y - y0g) / (H - y0g)
        d.line([0, y, W, y], fill=tuple(int(a + (b - a) * t) for a, b in zip(g_far, g_near)))
    for i in range(900):
        x = int(_rand("gx", i) * W)
        y = y0g + int(_rand("gy", i) ** 0.7 * (H - y0g))
        ln = 3 + int((y - y0g) / (H - y0g) * 9)
        c = _shade(g_near, 0.8 + 0.4 * _rand("gc", i))
        d.line([x, y, x + int((_rand("gl", i) - 0.5) * 4), y - ln], fill=c)
    # a path of pale stones between the rows
    path_y = int(H * 0.665)
    for i in range(34):
        x = int(i * W / 33 + (_rand("ps", i) - 0.5) * 12)
        r = int(12 + _rand("pr", i) * 8)
        d.ellipse([x - r, path_y - r // 3, x + r, path_y + r // 3], fill=(196, 186, 160) if day else (70, 70, 72))
    # eight raised beds in two rows, in perspective; the back row first
    rows = [(int(H * 0.55), 0.8, 105), (int(H * 0.72), 1.0, 140)]
    wood = (136, 92, 54) if day else (58, 42, 30)
    for r, (yt, sc, depth) in enumerate(rows):
        bw = int(250 * sc)
        gap = (W - 4 * bw) // 5
        for c in range(4):
            n = r * 4 + c
            bed = g["beds"][n]
            xl = gap + c * (bw + gap)
            inset = int(18 * sc)
            top_back, top_front = yt, yt + int(depth * 0.45)
            # a soft shadow on the grass
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(sh).ellipse([xl - 10, top_front + int(depth * 0.18), xl + bw + 26, top_front + int(depth * 0.42)],
                                       fill=(0, 0, 0, 90))
            sh = sh.filter(ImageFilter.GaussianBlur(9))
            img.paste(sh, (0, 0), sh)
            d = ImageDraw.Draw(img)
            wet = float(bed.get("water", 0.4)) if bed else 0.4
            soil = _shade((128, 94, 62) if day else (62, 47, 34), 1.0 - 0.38 * wet)
            # the frame's back and side edges, then the soil, then the front board
            d.polygon([(xl + inset - 6, top_back - 6), (xl + bw - inset + 6, top_back - 6), (xl + bw + 6, top_front),
                       (xl - 6, top_front)], fill=_shade(wood, 0.8))
            d.polygon([(xl + inset, top_back), (xl + bw - inset, top_back), (xl + bw, top_front), (xl, top_front)], fill=soil)
            for k in range(int(80 * sc)):
                u, v = _rand("sx", n, k), _rand("sy", n, k)
                x = int(xl + inset * (1 - v) + u * (bw - 2 * inset * (1 - v)))
                y = int(top_back + v * (top_front - top_back))
                d.point((x, y), fill=_shade(soil, 0.7 + 0.6 * _rand("sk", n, k)))
            fh = int(depth * 0.22)
            d.rectangle([xl - 6, top_front, xl + bw + 6, top_front + fh], fill=wood)
            d.line([xl - 6, top_front, xl + bw + 6, top_front], fill=_shade(wood, 1.35), width=3)
            for k in range(1, 4):
                yy = top_front + int(fh * k / 4)
                d.line([xl - 6, yy, xl + bw + 6, yy], fill=_shade(wood, 0.85), width=1)
            # the bed's number on a small stake
            sx = xl + bw - 16
            d.rectangle([sx, top_front - 26, sx + 18, top_front - 8], fill=(222, 206, 170) if day else (110, 102, 86))
            d.line([sx + 9, top_front - 8, sx + 9, top_front + 6], fill=_shade(wood, 0.7), width=3)
            d.text((sx + 5, top_front - 24), str(n + 1), fill=(60, 40, 24))
            if bed:
                for k in range(5):  # five plants along the bed, a row a little back and a little forward
                    u = (k + 0.5) / 5
                    v = 0.45 + 0.35 * (k % 2)
                    x = xl + inset * (1 - v) + u * (bw - 2 * inset * (1 - v))
                    y = top_back + v * (top_front - top_back)
                    _draw_plant(d, bed, x, y, sc * (0.8 + 0.2 * v), day, n * 10 + k)
    if rainy:
        rain = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rain)
        for i in range(420):
            x, y = int(_rand("r", i) * W), int(_rand("ry", i) * H)
            rd.line([x, y, x - 5, y + 16], fill=(220, 226, 240, 120) if day else (120, 130, 160, 120), width=1)
        img.paste(rain, (0, 0), rain)
    # light: a warm day, a cool night; the edges a little darker
    tint = (255, 230, 190) if day and not cloudy else (190, 200, 230) if not day else (220, 222, 226)
    img = Image.blend(img, Image.new("RGB", (W, H), tint), 0.06 if day else 0.12)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * 0.15, -H * 0.2, W * 1.15, H * 1.2], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    img = Image.composite(img, Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.45), vig)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _draw_plant(d, bed: dict, x: float, base: float, s: float, day: bool, seed: int = 0) -> None:
    sp = SEEDS.get(bed["seed"], {})
    gr = float(bed.get("growth", 0))
    col = sp.get("col", (200, 60, 80))
    col = col if day else _shade(col, 0.5)
    leaf = (74, 148, 58) if day else (32, 66, 34)
    if bed.get("health", 1) < 0.7 or bed.get("dry"):
        leaf = (146, 140, 72) if day else (68, 64, 36)
    dark = _shade(leaf, 0.72)
    j = 0.85 + 0.3 * _rand("pj", bed.get("seed"), seed)
    form = sp.get("form")
    if gr < 0.08:
        d.ellipse([x - 5 * s, base - 2 * s, x + 5 * s, base + 3 * s], fill=(92, 66, 44) if day else (46, 34, 24))
        return
    h = (14 + 100 * min(1.0, gr)) * s * j * (1.7 if form == "tall" else 1.0)
    if form in ("root", "rosette", "herb"):
        n = 3 + int(gr * 6)
        for i in range(n):
            ang = -math.pi / 2 + (i - (n - 1) / 2) * (0.32 if form != "rosette" else 0.5)
            _leaf(d, x, base, ang, h * (0.5 if form != "herb" else 0.6) * (0.8 + 0.2 * _rand("lf", seed, i)),
                  (4 if form == "root" else 6 if form == "herb" else 9) * s, leaf if i % 2 else dark)
        if form == "rosette" and gr > 0.3:
            r = h * 0.22
            d.ellipse([x - r, base - r * 1.3, x + r, base + r * 0.2], fill=_shade(col, 0.95))
            d.ellipse([x - r * 0.6, base - r * 1.1, x + r * 0.6, base - r * 0.1], fill=_shade(col, 1.15))
        if form == "root" and gr >= 0.9:
            d.ellipse([x - 7 * s, base - 4 * s, x + 7 * s, base + 7 * s], fill=col)
        return
    bend = (_rand("bd", seed) - 0.5) * 10 * s
    top = (x + bend, base - h)
    d.line([x, base, x + bend * 0.5, base - h * 0.5, top[0], top[1]], fill=dark, width=max(2, int(3 * s)), joint="curve")
    for i in range(1, 2 + int(gr * 4)):
        t = i / (3 + gr * 4)
        px, py = x + bend * t, base - h * t
        side = -1 if i % 2 else 1
        _leaf(d, px, py, -math.pi / 2 + side * 0.9, 16 * s * (1.1 - t * 0.4), 5 * s, leaf)
    if gr >= 0.9:
        cx, cy = top
        if form == "tall":
            for p in range(14):
                a = p * 2 * math.pi / 14
                _leaf(d, cx, cy, a, 18 * s, 5 * s, col)
            d.ellipse([cx - 8 * s, cy - 8 * s, cx + 8 * s, cy + 8 * s], fill=(84, 56, 26))
        elif form == "flower":
            for p in range(6):
                a = p * 2 * math.pi / 6 + 0.3
                _leaf(d, cx, cy, a, 10 * s, 5 * s, col)
            d.ellipse([cx - 3 * s, cy - 3 * s, cx + 3 * s, cy + 3 * s], fill=(28, 18, 30))
        else:  # vine, berry: fruit along it
            for i in range(3):
                t = 0.35 + 0.2 * i
                fx, fy = x + bend * t + 7 * s, base - h * t
                d.ellipse([fx - 5 * s, fy - 5 * s, fx + 5 * s, fy + 5 * s], fill=col)
    elif gr >= 0.65 and form in ("flower", "tall"):
        cx, cy = top
        d.ellipse([cx - 4 * s, cy - 6 * s, cx + 4 * s, cy + 2 * s], fill=_shade(leaf, 0.9))  # a bud
