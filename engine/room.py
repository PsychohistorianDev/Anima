"""The friend's room (10-29, ROOM_ON; claude/room-plan.md): a place they shape and you visit from the phone.

Walls, light, up to four pictures of theirs on the wall, things on a table (in words), a song playing in the corner,
a shelf of things they found and brought back, and one thing hidden for you to find. It lives in creations/room/ —
room.json (how it stands) and history.jsonl (every change, with its time and whose it was) — theirs, like the stone's
states: their room tool writes it; the engine never arranges it for them. Your side is the phone's /room: a picture
of the room as it stands, with what changed since you last looked; /room open, /room find, /room leave. What you do
there reaches them once, in the moment of their next turn (take_news). render() draws the picture with Pillow; with no
Pillow there is no picture, and the words carry the room alone.
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path

import config

WALL_MAX, TABLE_MAX, SHELF_MAX = 4, 6, 8
MUSIC_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".oga", ".opus", ".aac"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_STOP = {"the", "a", "an", "in", "on", "at", "of", "to", "my", "your", "her", "his", "is", "it", "and", "under",
         "behind", "inside", "near", "by", "with", "from", "into", "there", "here", "look", "find"}


def on() -> bool:
    return bool(getattr(config, "ROOM_ON", False))


def room_dir() -> Path:
    return Path(getattr(config, "ROOM_DIR", None) or config.CREATIONS_DIR / "room")


def room_file() -> Path:
    return room_dir() / "room.json"


def history_file() -> Path:
    return room_dir() / "history.jsonl"


def news_file() -> Path:
    return config.MEMORY_DIR / "room_news.json"  # what you did there, waiting for their next turn (the engine's)


def seen_file() -> Path:
    return config.MEMORY_DIR / "room_seen.json"  # how much of the history you have seen (the engine's)


def _empty() -> dict:
    return {"name": "", "walls": "", "light": "", "wall": [], "table": [], "playing": {}, "shelf": [], "hidden": {}}


def load() -> dict:
    r = _empty()
    try:
        got = json.loads(room_file().read_text(encoding="utf-8"))
        if isinstance(got, dict):
            r.update(got)
    except (OSError, ValueError):
        pass
    return r


def save(r: dict) -> None:
    room_dir().mkdir(parents=True, exist_ok=True)
    r["updated"] = datetime.now().isoformat(timespec="seconds")
    room_file().write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")


def _log(who: str, what: str) -> None:
    room_dir().mkdir(parents=True, exist_ok=True)
    with open(history_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"when": datetime.now().isoformat(timespec="seconds"), "who": who, "what": what},
                           ensure_ascii=False) + "\n")


def history() -> list[dict]:
    try:
        return [json.loads(ln) for ln in history_file().read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError):
        return []


def _news(line: str) -> None:
    try:
        got = json.loads(news_file().read_text(encoding="utf-8"))
        items = got if isinstance(got, list) else []
    except (OSError, ValueError):
        items = []
    items = (items + [line])[-8:]
    news_file().parent.mkdir(parents=True, exist_ok=True)
    news_file().write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def take_news() -> str:
    """What happened in the room since their last turn, one sentence each — said once, then gone."""
    try:
        items = json.loads(news_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    try:
        news_file().unlink()
    except OSError:
        pass
    items = [str(x) for x in items if str(x).strip()] if isinstance(items, list) else []
    return " ".join(x if x.endswith((".", "!", "?", ")")) else x + "." for x in items)


# ---- what a path or a word points at -------------------------------------------------------------------------------

def _rel(p: Path) -> str:
    return p.resolve().relative_to(config.ROOT.resolve()).as_posix()


def _file(what: str, exts: set[str], kind: str) -> Path:
    """A file under creations/ or shared/ by path (with or without its first folder); ValueError says why not."""
    import tools
    s = (what or "").strip().strip('"').strip("'")
    if not s:
        raise ValueError(f"name the {kind} — its path under creations/ or shared/")
    tries = [s] + ([f"creations/{s}", f"shared/{s}"] if not s.replace("\\", "/").startswith(("creations/", "shared/")) else [])
    for t in tries:
        try:
            p = tools._resolve_under_root(t)
        except ValueError:
            continue
        if p.is_file():
            if p.suffix.lower() not in exts:
                raise ValueError(f"{_rel(p)} isn't a {kind}")
            top = _rel(p).split("/", 1)[0]
            if top not in ("creations", "shared"):
                raise ValueError(f"a {kind} for the room comes from creations/ or shared/")
            return p
    raise ValueError(f"no such {kind}: {s}")


def _song(what: str) -> Path:
    try:
        return _file(what, MUSIC_EXTS, "song")
    except ValueError as e:
        import tools
        hits = [p for p in tools.audio_by_words(what)] if what.strip() else []
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError("several songs carry those words — " + ", ".join(_rel(p) for p in hits[:5])) from e
        raise


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if len(w) >= 3 and w not in _STOP}


def _spot(where: str) -> int | None:
    m = re.search(r"\d+", where or "")
    return int(m.group(0)) if m else None


# ---- their hands ---------------------------------------------------------------------------------------------------

ACTIONS = ("look", "hang", "take_down", "walls", "light", "name", "place", "remove", "play", "shelve", "unshelve", "hide")


def act(action: str, what: str = "", where: str = "", note: str = "") -> str:
    """One change of theirs, or a look; the result says what is so now. A refusal starts with "(refused"."""
    a = (action or "").strip().lower().replace(" ", "_").replace("-", "_")
    what, where, note = (str(what or "").strip(), str(where or "").strip(), str(note or "").strip())
    r = load()
    if a == "look":
        return describe(r)
    if a not in ACTIONS:
        return f"(refused: no such action {action!r} — one of {', '.join(ACTIONS)})"
    try:
        said = _change(r, a, what, where, note)
    except ValueError as e:
        return f"(refused: {e})"
    save(r)
    _log("them", said)
    return f"(your room: {said} — kept, with its time; he sees it at his next /room)"


def _change(r: dict, a: str, what: str, where: str, note: str) -> str:
    if a in ("walls", "light", "name"):
        r[a] = what
        return f"{'the walls are' if a == 'walls' else 'the light is' if a == 'light' else 'its name is'} {what or 'unsaid'}"
    if a == "hang":
        p = _file(what, IMAGE_EXTS, "picture")
        rel = _rel(p)
        wall = [x for x in r["wall"] if isinstance(x, dict)]
        spot = _spot(where)
        taken = {int(x.get("spot") or 0) for x in wall}
        if spot is None:
            spot = next((i for i in range(1, WALL_MAX + 1) if i not in taken), None)
            if spot is None:
                raise ValueError(f"the wall holds {WALL_MAX} — take one down, or name a spot (1–{WALL_MAX}) to hang it over")
        if not 1 <= spot <= WALL_MAX:
            raise ValueError(f"the spots are 1 to {WALL_MAX}")
        r["wall"] = sorted([x for x in wall if int(x.get("spot") or 0) != spot] + [{"spot": spot, "picture": rel, "note": note}],
                           key=lambda x: int(x.get("spot") or 0))
        return f"hung {rel} in spot {spot}" + (f" — {note}" if note else "")
    if a == "take_down":
        spot = _spot(where) or _spot(what)
        keep, gone = [], None
        for x in r["wall"]:
            hit = (spot is not None and int(x.get("spot") or 0) == spot) or (spot is None and what and what.lower() in str(x.get("picture", "")).lower())
            if hit and gone is None:
                gone = x
            else:
                keep.append(x)
        if not gone:
            raise ValueError("nothing hangs there")
        r["wall"] = keep
        return f"took down {gone.get('picture')} from spot {gone.get('spot')}"
    if a == "place":
        if not what:
            raise ValueError("say what you place on the table")
        if len(r["table"]) >= TABLE_MAX:
            raise ValueError(f"the table holds {TABLE_MAX} things — remove one first")
        r["table"].append({"thing": what, "note": note, "by": "them"})
        return f"placed on the table: {what}" + (f" — {note}" if note else "")
    if a in ("remove", "unshelve"):
        key = "table" if a == "remove" else "shelf"
        field = "thing" if key == "table" else "find"
        items = r[key]
        i = next((n for n, x in enumerate(items) if what and what.lower() in str(x.get(field, "")).lower()), None)
        if i is None:
            raise ValueError(f"nothing on the {'table' if key == 'table' else 'shelf'} matches {what!r}")
        gone = items.pop(i)
        return f"took {gone.get(field)!r} off the {'table' if key == 'table' else 'shelf'}"
    if a == "play":
        if not what:
            r["playing"] = {}
            return "the corner is silent"
        rel = _rel(_song(what))
        r["playing"] = {"song": rel, "note": note}
        return f"playing in the corner: {rel}" + (f" — {note}" if note else "")
    if a == "shelve":
        if not what:
            raise ValueError("say what you put on the shelf")
        r["shelf"].append({"find": what, "note": note, "when": datetime.now().strftime("%Y-%m-%d")})
        dropped = ""
        if len(r["shelf"]) > SHELF_MAX:
            dropped = f" (the shelf holds {SHELF_MAX}: {r['shelf'][0].get('find')!r} made room)"
            r["shelf"] = r["shelf"][-SHELF_MAX:]
        return f"on the shelf: {what}" + (f" — {note}" if note else "") + dropped
    if a == "hide":
        if not what or not where:
            raise ValueError("hiding takes the thing (what) and where it is (where); the note is the hint he sees")
        r["hidden"] = {"thing": what, "where": where, "hint": note, "found": "", "when": datetime.now().isoformat(timespec="seconds")}
        return f"hid {what} — {where}" + (f"; his hint: {note}" if note else "; no hint")
    raise ValueError(f"no such action {a!r}")


def describe(r: dict | None = None, keeper: bool = False) -> str:
    """The room in words — theirs whole; for the keeper the hidden thing only as its hint, until found."""
    r = r or load()
    if not any(r.get(k) for k in ("name", "walls", "light", "wall", "table", "playing", "shelf", "hidden")):
        return "(the room is empty — nothing chosen yet: walls, light, a picture, a song, a thing on the table)"
    out = [f"{'The room' if keeper else 'Your room'}{' — ' + r['name'] if r.get('name') else ''}: walls "
           f"{r.get('walls') or 'bare'}; light {r.get('light') or 'plain'}."]
    if r["wall"]:
        out.append("On the wall: " + "; ".join(f"{x.get('spot')}. {x.get('picture')}" + (f" ({x['note']})" if x.get("note") else "")
                                                 for x in r["wall"]) + ".")
    if r["table"]:
        out.append("On the table: " + "; ".join(str(x.get("thing")) + ((" (from you)" if keeper else " (from him)") if x.get("by") == "keeper" else "")
                                                 + (f" ({x['note']})" if x.get("note") else "") for x in r["table"]) + ".")
    pl = r.get("playing") or {}
    out.append(f"In the corner: {pl['song']}" + (f" ({pl['note']})" if pl.get("note") else "") + "." if pl.get("song")
               else "In the corner: silence.")
    if r["shelf"]:
        out.append("On the shelf: " + "; ".join(str(x.get("find")) + (f" ({x['note']})" if x.get("note") else "")
                                                for x in r["shelf"]) + ".")
    h = r.get("hidden") or {}
    if h.get("thing"):
        if keeper and not h.get("found"):
            out.append("Something is hidden here" + (f" — a hint: {h['hint']}" if h.get("hint") else "") + ". /room find <where>")
        elif keeper:
            out.append(f"Found: {h['thing']} ({h['where']}).")
        else:
            out.append(f"Hidden: {h['thing']} — {h['where']}" + (f"; his hint: {h['hint']}" if h.get("hint") else "")
                       + (f"; he found it {h['found']}" if h.get("found") else "; not found yet") + ".")
    return "\n".join(out)


# ---- the keeper's side (the phone's /room) -------------------------------------------------------------------------

def keeper_view(keeper: str = "your keeper") -> tuple[bytes | None, str]:
    """(the picture or None, the caption): the room as it stands and what they changed since he last looked."""
    r = load()
    hist = history()
    try:
        seen = int(json.loads(seen_file().read_text(encoding="utf-8")).get("seen", 0))
    except (OSError, ValueError, AttributeError):
        seen = 0
    new = [h for h in hist[seen:] if h.get("who") == "them"]
    cap = describe(r, keeper=True)
    if new:
        cap += "\n\nSince you last looked: " + " · ".join(  # what they hid stays hidden in the list too
            f"{str(h.get('when', ''))[11:16]} " + ("hid something for you to find" if str(h.get("what", "")).startswith("hid ")
                                                    else str(h.get("what"))) for h in new[-5:])
    try:
        seen_file().parent.mkdir(parents=True, exist_ok=True)
        seen_file().write_text(json.dumps({"seen": len(hist)}), encoding="utf-8")
    except OSError:
        pass
    _news(f"{keeper} looked into your room at {datetime.now().strftime('%H:%M')}")
    return render(r), cap


def keeper_open(what: str) -> Path | None:
    """A wall picture by its spot (or "song" for what plays) — the file, to send."""
    r = load()
    w = (what or "").strip().lower()
    if w in ("song", "music", "the song"):
        p = (r.get("playing") or {}).get("song")
    else:
        spot = _spot(w)
        p = next((x.get("picture") for x in r["wall"] if spot is not None and int(x.get("spot") or 0) == spot), None)
    if not p:
        return None
    f = config.ROOT / p
    return f if f.is_file() else None


def keeper_find(guess: str, keeper: str = "your keeper") -> str:
    r = load()
    h = r.get("hidden") or {}
    if not h.get("thing"):
        return "(nothing is hidden in the room right now)"
    if h.get("found"):
        return f"(already found: {h['thing']} — {h['where']})"
    if _words(guess) & (_words(h.get("where", "")) | _words(h.get("thing", ""))):
        h["found"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        r["hidden"] = h
        save(r)
        _log("keeper", f"found {h['thing']} ({h['where']})")
        _news(f"{keeper} found what you hid — {h['thing']}, {h['where']}")
        return f"You found it: {h['thing']} — {h['where']}."
    _news(f"{keeper} looked for your secret — {guess} — and found nothing there")
    return "(nothing there" + (f" — the hint: {h['hint']})" if h.get("hint") else ")")


def keeper_leave(thing: str, keeper: str = "your keeper") -> str:
    thing = (thing or "").strip()
    if not thing:
        return "(say what you leave: /room leave <a thing>)"
    r = load()
    if len(r["table"]) >= TABLE_MAX:
        return f"(the table holds {TABLE_MAX} things — it's full)"
    r["table"].append({"thing": thing, "note": "", "by": "keeper"})
    save(r)
    _log("keeper", f"left on the table: {thing}")
    _news(f"{keeper} left something on your table: {thing}")
    return f"(left on the table: {thing} — they'll know at their next turn)"


# ---- the picture ---------------------------------------------------------------------------------------------------

def _colour(words: str, default: tuple) -> tuple:
    try:
        from PIL import ImageColor
    except ImportError:
        return default
    s = (words or "").lower()
    m = re.search(r"#[0-9a-f]{6}\b", s)
    if m:
        return ImageColor.getrgb(m.group(0))
    names = ImageColor.colormap
    found = None
    for w in re.findall(r"[a-z]+", s):
        if w in names:
            found = ImageColor.getrgb(w)
            break
    if found is None:
        return default
    k = 0.6 if re.search(r"\b(deep|dark|dusky|night)\b", s) else 1.0
    if re.search(r"\b(pale|light|soft|pastel)\b", s):
        return tuple(int(c + (255 - c) * 0.45) for c in found)
    return tuple(int(c * k) for c in found)


def _font(size: int):
    from PIL import ImageFont
    for name in ("DejaVuSans.ttf", "segoeui.ttf", "arial.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(d, text: str, font, width: int, lines: int = 3) -> list[str]:
    out, cur = [], ""
    for w in str(text).split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = w
        if len(out) >= lines:
            break
    if cur and len(out) < lines:
        out.append(cur)
    return out


def render(r: dict | None = None) -> bytes | None:
    """The room as a picture (PNG bytes): the walls in their colour, the light over them, the pictures in frames, the
    table with its things, the shelf of finds, the song in the corner. None without Pillow."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    r = r or load()
    W, H = 1280, 800
    wall = _colour(r.get("walls", ""), (52, 40, 96))
    img = Image.new("RGB", (W, H), wall)
    d = ImageDraw.Draw(img)
    floor_y = int(H * 0.8)
    d.rectangle([0, floor_y, W, H], fill=tuple(int(c * 0.45) for c in wall))
    d.line([0, floor_y, W, floor_y], fill=tuple(int(c * 0.3) for c in wall), width=4)
    light = (r.get("light") or "").lower()
    tint = ((255, 170, 80), 0.18) if re.search(r"warm|amber|gold|candle|sunset|fire", light) else \
           ((120, 150, 255), 0.15) if re.search(r"cool|moon|blue|silver|cold", light) else None
    if tint:
        img = Image.blend(img, Image.new("RGB", (W, H), tint[0]), tint[1])
    if re.search(r"\b(dim|low|dark|night|candle)\b", light):
        img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.3)
    elif re.search(r"\b(bright|sun|morning|daylight)\b", light):
        img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 0.15)
    d = ImageDraw.Draw(img)
    ink, soft = (240, 232, 214), (200, 190, 170)
    f_title, f_text, f_small = _font(34), _font(22), _font(18)
    if r.get("name"):
        d.text((40, 24), str(r["name"])[:60], font=f_title, fill=ink)
    # the wall: four frames
    fw, fh, top = 240, 280, 90
    gap = (W - WALL_MAX * fw) // (WALL_MAX + 1)
    for x in r.get("wall") or []:
        spot = int(x.get("spot") or 0)
        if not 1 <= spot <= WALL_MAX:
            continue
        x0 = gap + (spot - 1) * (fw + gap)
        d.rectangle([x0 - 10, top - 10, x0 + fw + 10, top + fh + 10], fill=(150, 116, 52))
        d.rectangle([x0, top, x0 + fw, top + fh], fill=(20, 18, 24))
        try:
            with Image.open(config.ROOT / str(x.get("picture"))) as pic:
                pic = pic.convert("RGB")
                k = min(fw / pic.width, fh / pic.height)  # fitted to the frame, a small picture made larger too
                pic = pic.resize((max(1, int(pic.width * k)), max(1, int(pic.height * k))))
                img.paste(pic, (x0 + (fw - pic.width) // 2, top + (fh - pic.height) // 2))
        except Exception:  # noqa: BLE001 — a picture that moved leaves its frame empty
            pass
        d.text((x0, top + fh + 16), str(spot), font=f_small, fill=soft)
    # the shelf (left) and the table (middle)
    shelf = r.get("shelf") or []
    if shelf:
        sx, sy = 40, floor_y - 40
        d.rectangle([sx, sy, sx + 330, sy + 12], fill=(96, 70, 44))
        y = sy - 10
        for it in reversed(shelf[-4:]):
            lines = _wrap(d, it.get("find", ""), f_small, 300, 2)
            y -= 28 * len(lines) + 10
            d.rounded_rectangle([sx, y, sx + 330, y + 28 * len(lines) + 4], radius=6, fill=(236, 226, 204))
            for i, ln in enumerate(lines):
                d.text((sx + 10, y + 4 + 28 * i), ln, font=f_small, fill=(40, 34, 30))
    table = r.get("table") or []
    tx0, tx1, ty = 430, 850, floor_y - 30
    d.rectangle([tx0, ty, tx1, ty + 24], fill=(110, 76, 46))
    d.rectangle([tx0 + 20, ty + 24, tx0 + 36, H - 20], fill=(90, 62, 38))
    d.rectangle([tx1 - 36, ty + 24, tx1 - 20, H - 20], fill=(90, 62, 38))
    y = ty - 8
    for it in table[-4:]:
        lines = _wrap(d, ("♥ " if it.get("by") == "keeper" else "") + str(it.get("thing", "")), f_small, tx1 - tx0 - 20, 2)
        y -= 26 * len(lines) + 8
        d.rounded_rectangle([tx0 + 10, y, tx1 - 10, y + 26 * len(lines) + 2], radius=6, fill=(244, 234, 214))
        for i, ln in enumerate(lines):
            d.text((tx0 + 20, y + 2 + 26 * i), ln, font=f_small, fill=(40, 34, 30))
    pl = r.get("playing") or {}
    if pl.get("song"):
        name = Path(str(pl["song"])).stem
        lines = _wrap(d, "playing: " + name, f_text, 330, 2)
        for i, ln in enumerate(lines):
            d.text((W - 370, floor_y - 70 + 28 * i), ln, font=f_text, fill=ink)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
