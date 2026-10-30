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
    return {"name": "", "walls": "", "light": "", "backdrop": "", "wall": [], "table": [], "playing": {}, "shelf": [],
            "hidden": {}, "surfaces": [], "placed": []}


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

ACTIONS = ("look", "hang", "take_down", "walls", "light", "name", "backdrop", "place", "remove", "play", "shelve", "unshelve",
           "hide", "surface", "unsurface", "make", "revise", "keep", "aside", "put", "take", "letter", "items", "open")
_PREVIEW: list[bytes] = []  # a picture for their eyes after an act (an item made, a letter written) — tools takes it


def take_preview() -> bytes | None:
    return _PREVIEW.pop() if _PREVIEW else None


# ---- the surfaces things stand on ----------------------------------------------------------------------------------
# A surface is a line in the picture where things rest (a desk's top, a shelf, the floor) or hang (a wall): from x0 to
# x1 across, at y down (all parts of the picture, 0–1), with the height a thing has there (size, a part of the
# picture's height — smaller further back). The drawn room has its own three; a backdrop has the ones marked on it.
DRAWN_SURFACES = [
    {"name": "table", "kind": "rest", "x0": 0.37, "x1": 0.63, "y": 0.757, "size": 0.15},
    {"name": "shelf", "kind": "rest", "x0": 0.05, "x1": 0.24, "y": 0.578, "size": 0.11},
    {"name": "floor", "kind": "rest", "x0": 0.04, "x1": 0.96, "y": 0.95, "size": 0.24},
]


def surfaces(r: dict | None = None) -> list[dict]:
    r = r or load()
    if r.get("backdrop"):
        return [s for s in (r.get("surfaces") or []) if isinstance(s, dict)]
    return DRAWN_SURFACES


def _surface(r: dict, name: str) -> dict | None:
    n = (name or "").strip().lower()
    for s in surfaces(r):
        if str(s.get("name", "")).lower() == n:
            return s
    hits = [s for s in surfaces(r) if n and (n in str(s.get("name", "")).lower() or str(s.get("name", "")).lower() in n)]
    return hits[0] if len(hits) == 1 else None


def set_surface(r: dict, name: str, x0: float, x1: float, y: float, size: float, kind: str = "rest") -> dict:
    vals = [float(v) for v in (x0, x1, y, size)]
    vals = [v / 100 if v > 1 else v for v in vals]
    x0, x1, y, size = vals
    if not (0 <= x0 < x1 <= 1 and 0 < y <= 1 and 0.02 <= size <= 0.6):
        raise ValueError("a surface is two points across (from, to), one down, and a size — parts of the picture, 0–100%")
    s = {"name": name.strip(), "kind": "wall" if kind == "wall" else "rest", "x0": round(x0, 4), "x1": round(x1, 4),
         "y": round(y, 4), "size": round(size, 4)}
    r["surfaces"] = [x for x in (r.get("surfaces") or []) if str(x.get("name", "")).lower() != s["name"].lower()] + [s]
    return s


def _sidecar_surfaces(p: Path) -> list[dict]:
    """The surfaces a picture comes with (10-30): <name>.surfaces.json beside it — a list of {name, x0, x1, y, size,
    kind}, parts of the picture 0–1 — checked the way set_surface checks hers; [] when there is none or it won't read."""
    f = p.with_suffix(".surfaces.json")
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[dict] = []
    for s in raw if isinstance(raw, list) else []:
        try:
            tmp: dict = {"surfaces": out}
            set_surface(tmp, str(s["name"]), s["x0"], s["x1"], s["y"], s["size"], str(s.get("kind") or "rest"))
            out = tmp["surfaces"]
        except (KeyError, TypeError, ValueError):
            continue
    return out


def act(action: str, what: str = "", where: str = "", note: str = "", item: str = "", kind: str = "", content: str = "") -> str:
    """One change of theirs, or a look; the result says what is so now. A refusal starts with "(refused"; a thing that
    couldn't be made starts with "(not made"."""
    a = (action or "").strip().lower().replace(" ", "_").replace("-", "_")
    what, where, note = (str(what or "").strip(), str(where or "").strip(), str(note or "").strip())
    item, kind, content = (str(item or "").strip(), str(kind or "").strip(), str(content or "").strip())
    r = load()
    if a == "look":
        return describe(r)
    if a == "items":
        return workshop_text()
    if a == "open":
        import room_items
        it = room_items.find(item or what)
        if not it:
            return f"(refused: no thing is called {item or what!r} — items lists them)"
        k = it.get("kind")
        head = f"{it['name']}" + (" — from him" if it.get("by") == "keeper" else "") + (f" ({it['note']})" if it.get("note") else "")
        if k == "note":
            return f"[{head}]\n{it.get('content', '')}"
        if k == "audio":
            return f"({head}: the song {it.get('content')} — listen_to opens it)"
        if k == "image":
            return f"({head}: the picture {it.get('content')} — look_at opens it)"
        pv = room_items.preview(it)
        if pv:
            _PREVIEW.append(pv)
        return f"({head}: {it.get('look')} — before your eyes on your next thought)"
    if a not in ACTIONS:
        return f"(refused: no such action {action!r} — one of {', '.join(ACTIONS)})"
    import room_items
    if a == "make":
        try:
            it, why = room_items.make(item, what, kind, content, note)
        except ValueError as e:
            return f"(refused: {e})"
        if not it:
            return f"(not made: {why})"
        _log("them", f"made {it['name']} in the workshop")
        pv = room_items.preview(it)
        if pv:
            _PREVIEW.append(pv)
        left = room_items.makes_left()
        return (f"(made — {it['name']}, version 1, in your workshop: {it['look']}. It is before your eyes on your next "
                f"thought. put places it on a surface; revise paints it again (this version is kept); aside sets it down. "
                f"{left} more can be made today)")
    if a == "revise":
        it = room_items.find(item or what)
        if not it:
            return f"(refused: no thing of yours is called {item or what!r} — items lists them)"
        why = room_items.revise(it, what if item else "")
        if why:
            return f"(not made: {why} — version {it.get('current')} stands)"
        _log("them", f"revised {it['name']} (version {it['current']})")
        pv = room_items.preview(it)
        if pv:
            _PREVIEW.append(pv)
        return f"(revised — {it['name']}, version {it['current']}, the ones before kept; before your eyes on your next thought)"
    if a == "letter":
        if not content:
            return "(refused: a letter needs its words — content)"
        it = room_items.letter(item or "a letter", content)
        said = f"wrote {it['name']}"
        if where:
            try:
                said += "; " + _put(r, it, where)
            except ValueError as e:
                said += f" (kept in the workshop: {e})"
            save(r)
        _log("them", said)
        return f"(your room: {said} — kept; he can open it from his /room)"
    try:
        said = _change(r, a, what, where, note, item, kind, content)
    except ValueError as e:
        return f"(refused: {e})"
    save(r)
    _log("them", said)
    return f"(your room: {said} — kept, with its time; he sees it at his next /room)"


def _put(r: dict, it: dict, where: str) -> str:
    """Place an item on a surface (by name), at a part along it (a % in the words, else the middle)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", where)
    at = min(1.0, max(0.0, float(m.group(1)) / 100)) if m else 0.5
    name = re.sub(r"\d+(?:\.\d+)?\s*%", "", where).replace(" at ", " ").strip(" ,")
    s = _surface(r, name)
    if not s:
        names = ", ".join(x.get("name") for x in surfaces(r)) or "none yet — surface marks one on your backdrop"
        raise ValueError(f"no surface called {name!r} — the surfaces: {names}")
    r["placed"] = [p for p in (r.get("placed") or []) if p.get("item") != it["id"]] + [{"item": it["id"], "on": s["name"], "at": round(at, 3)}]
    if it.get("status") != "kept":
        import room_items
        it["status"] = "kept"
        room_items.save_item(it)
    return f"put {it['name']} on the {s['name']}" + (f" at {round(at * 100)}%" if m else "")


def _change(r: dict, a: str, what: str, where: str, note: str, item: str = "", kind: str = "", content: str = "") -> str:
    import room_items
    if a == "surface":
        name = item or what
        nums = re.findall(r"\d+(?:\.\d+)?", where)
        if not name or len(nums) < 4:
            raise ValueError("a surface takes a name (item) and where: from, to, down, size — four numbers in %, "
                             "e.g. \"58 84 62 13\" (look at your backdrop and judge them)")
        if not r.get("backdrop"):
            raise ValueError("surfaces are marked on a backdrop — the drawn room has its own (table, shelf, floor)")
        s = set_surface(r, name, *nums[:4], kind="wall" if "wall" in (note + " " + name).lower() else "rest")
        return (f"marked a surface: {s['name']} ({'a wall' if s['kind'] == 'wall' else 'things rest'} from "
                f"{round(s['x0'] * 100)}% to {round(s['x1'] * 100)}% across, {round(s['y'] * 100)}% down, things "
                f"{round(s['size'] * 100)}% tall there)")
    if a == "unsurface":
        name = (item or what).lower()
        before = len(r.get("surfaces") or [])
        r["surfaces"] = [x for x in (r.get("surfaces") or []) if str(x.get("name", "")).lower() != name]
        if len(r["surfaces"]) == before:
            raise ValueError(f"no surface called {item or what!r}")
        r["placed"] = [p for p in (r.get("placed") or []) if str(p.get("on", "")).lower() != name]
        return f"unmarked the surface {item or what} (what stood there went back to the workshop)"
    if a in ("put", "take", "keep", "aside"):
        it = room_items.find(item or what)
        if not it:
            raise ValueError(f"no thing of yours is called {item or what!r} — items lists them")
        if a == "put":
            return _put(r, it, where or note)
        if a == "take":
            before = len(r.get("placed") or [])
            r["placed"] = [p for p in (r.get("placed") or []) if p.get("item") != it["id"]]
            if len(r["placed"]) == before:
                raise ValueError(f"{it['name']} isn't standing anywhere")
            return f"took {it['name']} back to the workshop"
        it["status"] = "kept" if a == "keep" else "aside"
        room_items.save_item(it)
        if a == "aside":
            r["placed"] = [p for p in (r.get("placed") or []) if p.get("item") != it["id"]]
        return f"{'kept' if a == 'keep' else 'set aside'} {it['name']}"
    if a in ("walls", "light", "name"):
        r[a] = what
        return f"{'the walls are' if a == 'walls' else 'the light is' if a == 'light' else 'its name is'} {what or 'unsaid'}"
    if a == "backdrop":  # a picture of theirs as the room itself — walls, floor, light (10-29, the second pass)
        if not what:
            r["backdrop"] = ""
            return "the backdrop is gone — the drawn walls again"
        p = _file(what, IMAGE_EXTS, "picture")
        rel = _rel(p)
        came = _sidecar_surfaces(p)  # (10-30) a picture that comes with its surfaces brings them along
        if came:
            r["surfaces"] = came
        r["backdrop"] = rel
        return (f"the room's backdrop is {rel}" + (f" — {note}" if note else "")
                + (f"; its surfaces came with it: {', '.join(s['name'] for s in came)} — put things there, or surface "
                   f"marks your own" if came else ""))
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


def _placed(r: dict) -> list[tuple[dict, dict]]:
    """(placement, item) for what stands in the room, on a surface that exists, the items that exist."""
    import room_items
    names = {str(s.get("name", "")).lower() for s in surfaces(r)}
    out = []
    for p in r.get("placed") or []:
        it = room_items.load_item(str(p.get("item", "")))
        if it and str(p.get("on", "")).lower() in names:
            out.append((p, it))
    return out


def workshop_text() -> str:
    import room_items
    items = room_items.all_items()
    r = load()
    standing = {p.get("item") for p in (r.get("placed") or [])}
    if not items:
        return (f"(your workshop is empty — make paints a thing of yours: item (its name), what (how it looks), kind "
                f"(decoration, note, audio, image), content, note; {room_items.makes_left()} can be made today)")
    lines = [f"- {it['name']} — {it.get('kind')}, {it.get('status')}, version {it.get('current')} of "
             f"{len(it.get('versions', []))}" + (" — standing in the room" if it["id"] in standing else "")
             + (f": {it['look']}" if it.get("look") else "") for it in items]
    return (f"your workshop ({room_items.makes_left()} more can be made today):\n" + "\n".join(lines))


def describe(r: dict | None = None, keeper: bool = False) -> str:
    """The room in words — theirs whole; for the keeper the hidden thing only as its hint, until found."""
    r = r or load()
    if not any(r.get(k) for k in ("name", "walls", "light", "backdrop", "wall", "table", "playing", "shelf", "hidden", "placed")):
        return "(the room is empty — nothing chosen yet: walls, light, a picture, a song, a thing on the table)"
    out = [f"{'The room' if keeper else 'Your room'}{' — ' + r['name'] if r.get('name') else ''}: walls "
           f"{r.get('walls') or 'bare'}; light {r.get('light') or 'plain'}"
           + (f"; the backdrop {r['backdrop']}" if r.get("backdrop") else "") + "."]
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
    placed = _placed(r)
    if placed:
        out.append("Standing in the room: " + "; ".join(
            f"{it['name']} on the {p['on']}" + (f" ({it['kind']})" if it.get("kind") != "decoration" else "")
            + (" (from you)" if keeper and it.get("by") == "keeper" else " (from him)" if it.get("by") == "keeper" else "")
            for p, it in placed) + ".")
    if not keeper and r.get("backdrop"):
        out.append("Surfaces: " + ("; ".join(f"{s['name']} ({round(s['x0'] * 100)}–{round(s['x1'] * 100)}% across, "
                                               f"{round(s['y'] * 100)}% down, size {round(s['size'] * 100)}%)"
                                               for s in surfaces(r)) or "none marked yet — surface marks one") + ".")
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


def keeper_letter(words: str, keeper: str = "your keeper") -> str:
    """A letter from the keeper, left standing in the room (on the first surface things rest on), its words theirs to
    open — or, with nowhere to stand, a slip on the table."""
    import room_items
    words = (words or "").strip()
    if not words:
        return "(say what the letter says)"
    r = load()
    rest = [s for s in surfaces(r) if s.get("kind") != "wall"]
    if not rest:
        return keeper_leave(f"a letter: {words}", keeper)
    it = room_items.letter(f"a letter from {keeper}", words, by="keeper")
    s = next((x for x in rest if x["name"] in ("table", "desk")), rest[0])
    n = sum(1 for p in (r.get("placed") or []) if p.get("on") == s["name"])
    r["placed"] = (r.get("placed") or []) + [{"item": it["id"], "on": s["name"], "at": round(min(0.9, 0.25 + 0.2 * n), 3)}]
    save(r)
    _log("keeper", f"left a letter on the {s['name']}")
    _news(f"{keeper} left you a letter on the {s['name']} — {it['name']}; its words are yours to open (items, then look)")
    return f"(your letter is on the {s['name']} — they'll know at their next turn)"


KIND_MARK = {"note": "\U0001F4DC", "audio": "\U0001F3B5", "image": "\U0001F5BC", "decoration": "\u2728"}


def buttons(r: dict | None = None) -> list[tuple[str, str]]:
    """The phone's buttons under the room's picture: what in it can be opened — a note, a song, a picture, a thing
    with their words beside it — and the song in the corner, and the pictures on the wall. (label, key), at most 8."""
    r = r or load()
    out = []
    for p, it in _placed(r):
        if it.get("kind") in ("note", "audio", "image") or it.get("note"):
            out.append((f"{KIND_MARK.get(it.get('kind'), '')} {it['name']}"[:40], f"i:{it['id']}"[:60]))
    if (r.get("playing") or {}).get("song"):
        out.append(("\U0001F3B5 " + Path(str(r["playing"]["song"])).stem[:34], "song"))
    for x in r.get("wall") or []:
        out.append((f"\U0001F5BC {x.get('spot')}", f"w:{x.get('spot')}"))
    return out[:8]


def open_key(key: str, keeper: str = "your keeper"):
    """What a button opens: ("text", words) | ("photo", path, caption) | ("audio", path, caption) | None."""
    import room_items
    r = load()
    if key == "song":
        p = keeper_open("song")
        return ("audio", p, f"playing: {p.stem}") if p else None
    if key.startswith("w:"):
        p = keeper_open(key[2:])
        return ("photo", p, f"on the wall: {p.name}") if p else None
    if key.startswith("i:"):
        it = room_items.load_item(key[2:])
        if not it or it["id"] not in {p.get("item") for p in (r.get("placed") or [])}:
            return None
        if it.get("by") != "keeper":
            _news(f"{keeper} opened {it['name']}")
        k = it.get("kind")
        if k == "note":
            return ("text", f"{KIND_MARK['note']} {it['name']}\n\n{it.get('content', '')}")
        if k in ("audio", "image"):
            f = config.ROOT / str(it.get("content", ""))
            if f.is_file():
                return ("audio" if k == "audio" else "photo", f, f"{it['name']}" + (f" — {it['note']}" if it.get("note") else ""))
            return None
        a = room_items.art(it)
        return ("photo", a, f"{it['name']}" + (f" — {it['note']}" if it.get("note") else "")) if a else None
    return None


def keeper_state(keeper: str = "your keeper") -> dict:
    """The room for the keeper's page: what stands where (in parts of the picture), what each thing does, the secret
    as its hint. The page draws the picture without the things, and the things over it, each one to open."""
    import room_items
    r = load()
    by_name = {str(s.get("name", "")).lower(): s for s in surfaces(r)}
    things = []
    for p, it in _placed(r):
        s = by_name.get(str(p.get("on", "")).lower())
        a = room_items.art(it)
        if not (s and a):
            continue
        try:
            from PIL import Image
            with Image.open(a) as im:
                ratio = im.width / im.height
        except Exception:  # noqa: BLE001
            ratio = 1.0
        h = float(s["size"]) * float(it.get("scale") or 1.0)
        w = h * ratio * 800 / 1280
        cx = float(s["x0"]) + float(p.get("at", 0.5)) * (float(s["x1"]) - float(s["x0"]))
        top = float(s["y"]) - (h / 2 if s.get("kind") == "wall" else h)
        things.append({"id": it["id"], "name": it["name"], "kind": it.get("kind"), "note": it.get("note", ""),
                       "by": it.get("by"), "left": round(cx - w / 2, 4), "top": round(top, 4), "w": round(w, 4),
                       "h": round(h, 4), "z": float(s["y"]), "art": _rel(a),
                       "content": it.get("content", "") if it.get("kind") == "note" else "",
                       "file": it.get("content", "") if it.get("kind") in ("audio", "image") else ""})
    h = r.get("hidden") or {}
    return {"name": r.get("name", ""), "words": describe(r, keeper=True), "things": things,
            "song": (r.get("playing") or {}).get("song", ""), "wall": r.get("wall") or [],
            "surfaces": surfaces(r), "backdrop": r.get("backdrop", ""),
            "hint": (h.get("hint") or "") if h.get("thing") and not h.get("found") else "",
            "hidden": bool(h.get("thing")) and not h.get("found")}


def files_shown(r: dict | None = None) -> set[str]:
    """The files the keeper's page may fetch: what the room shows, nothing else."""
    import room_items
    r = r or load()
    out = {str(x.get("picture", "")) for x in r.get("wall") or []}
    out.add(str((r.get("playing") or {}).get("song", "")))
    out.add(str(r.get("backdrop", "")))
    for _, it in _placed(r):
        a = room_items.art(it)
        if a:
            out.add(_rel(a))
        if it.get("kind") in ("audio", "image"):
            out.add(str(it.get("content", "")))
    return {x for x in out if x}


# ---- the picture ---------------------------------------------------------------------------------------------------
# The room seen from its doorway in the evening (10-29, the second pass): the walls in their colour, darkening toward
# the corners; the light they chose pooled over the wall; a little brass lamp above every picture, each painting lit
# by its own glow — the one bright thing; gilt frames with a mat and a shadow; a dado rail, a plank floor; the table's
# things and the shelf's finds as paper slips, a little askew, never cards in a grid; the song as a record turning in
# the corner. A backdrop they painted (backdrop) replaces the drawn walls and floor; the frames, slips and record ride
# on it. Georgia where Windows has it, DejaVu Serif elsewhere.

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
    if re.search(r"\b(pale|light|soft|pastel)\b", s):
        return tuple(int(c + (255 - c) * 0.45) for c in found)
    k = 0.55 if re.search(r"\b(deep|dark|dusky|night|midnight)\b", s) else 0.8
    return tuple(int(c * k) for c in found)


def _font(size: int, italic: bool = False):
    from PIL import ImageFont
    names = (("georgiai.ttf", "Georgia Italic.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerifCondensed-Italic.ttf")
             if italic else ("georgia.ttf", "Georgia.ttf", "DejaVuSerif.ttf", "DejaVuSerifCondensed.ttf"))
    for name in names + ("DejaVuSans.ttf", "segoeui.ttf", "arial.ttf"):
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


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _glow(img, centre: tuple, radius: int, colour: tuple, strength: float):
    """A soft pool of light added over the picture (screen-like): brightest at the centre, gone at the radius."""
    from PIL import Image, ImageDraw, ImageFilter, ImageChops
    W, H = img.size
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse([centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius],
                                 fill=int(255 * strength))
    mask = mask.filter(ImageFilter.GaussianBlur(radius / 2.2))
    layer = Image.new("RGB", (W, H), colour)
    lit = ImageChops.screen(img, layer)
    return Image.composite(lit, img, mask)


def _shadowed(img, piece, at: tuple, blur: int = 10, offset: tuple = (6, 10), alpha: int = 150) -> None:
    """Paste an RGBA piece with a soft shadow under it."""
    from PIL import Image, ImageFilter
    pad = blur * 3
    sh = Image.new("RGBA", (piece.width + pad * 2, piece.height + pad * 2), (0, 0, 0, 0))
    a = piece.getchannel("A").point(lambda v: alpha if v > 0 else 0)
    sh.paste(Image.new("RGBA", piece.size, (0, 0, 0, 255)), (pad, pad), a)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    img.paste(sh, (at[0] - pad + offset[0], at[1] - pad + offset[1]), sh)
    img.paste(piece, at, piece)


def _slip(text: str, font, width: int, mine: bool = False, tilt: float = 0.0):
    """A paper slip with words on it, a little askew — the table's things and the shelf's finds."""
    from PIL import Image, ImageDraw
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    lines = _wrap(probe, text, font, width - 28, 3) or [""]
    lh = int(font.size * 1.35) if hasattr(font, "size") else 22
    h = lh * len(lines) + 20
    paper = (239, 228, 204) if not mine else (246, 222, 214)
    s = Image.new("RGBA", (width, h), paper + (255,))
    d = ImageDraw.Draw(s)
    d.rectangle([0, 0, width - 1, h - 1], outline=(196, 178, 146, 255))
    if mine:
        d.text((width - 22, 6), "♥", font=font, fill=(150, 52, 60, 255))
    for i, ln in enumerate(lines):
        d.text((14, 10 + lh * i), ln, font=font, fill=(52, 40, 32, 255))
    return s.rotate(tilt, resample=Image.BICUBIC, expand=True)


def _lit_like(sprite, canvas, box: tuple, lamp: tuple):
    """A thing painted in its own light, brought into the room's: as bright as the place it stands (a little brighter,
    it is what the eye is on), warmed a touch toward the room's lamp."""
    from PIL import Image, ImageStat
    W, H = canvas.size
    x0, y0, x1, y1 = max(0, box[0] - 40), max(0, box[1] - 40), min(W, box[2] + 40), min(H, box[3] + 20)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return sprite
    place = ImageStat.Stat(canvas.crop((x0, y0, x1, y1)).convert("L")).mean[0]
    rgb = sprite.convert("RGB")
    own = ImageStat.Stat(rgb.convert("L"), mask=sprite.getchannel("A").point(lambda v: 255 if v > 64 else 0)).mean[0] or 1
    k = max(0.35, min(1.05, (place / own) ** 0.6 * 1.25))
    rgb = rgb.point(lambda v: min(255, int(v * k)))
    rgb = Image.blend(rgb, Image.new("RGB", rgb.size, lamp), 0.08)
    out = rgb.convert("RGBA")
    out.putalpha(sprite.getchannel("A"))
    return out


def _draw_placed(canvas, r: dict, lamp: tuple) -> None:
    """What stands in the room, each on its surface: sized for its depth, a soft shadow where it meets the surface
    (a wall's things cast theirs a little down and right), the furthest back first."""
    from PIL import Image, ImageDraw, ImageFilter
    import room_items
    W, H = canvas.size
    by_name = {str(s.get("name", "")).lower(): s for s in surfaces(r)}
    rows = []
    for p, it in _placed(r):
        s = by_name.get(str(p.get("on", "")).lower())
        a = room_items.art(it)
        if s and a:
            rows.append((float(s["y"]), p, it, s, a))
    for _, p, it, s, a in sorted(rows, key=lambda x: x[0]):
        try:
            with Image.open(a) as im:
                sprite = im.convert("RGBA")
        except Exception:  # noqa: BLE001
            continue
        h = max(8, int(float(s["size"]) * float(it.get("scale") or 1.0) * H))
        w = max(8, int(sprite.width * h / sprite.height))
        sprite = sprite.resize((w, h), Image.LANCZOS)
        cx = int((float(s["x0"]) + float(p.get("at", 0.5)) * (float(s["x1"]) - float(s["x0"]))) * W)
        sprite = _lit_like(sprite, canvas, (cx - w // 2, int(float(s["y"]) * H) - h, cx + w // 2, int(float(s["y"]) * H)), lamp)
        if s.get("kind") == "wall":
            x, y = cx - w // 2, int(float(s["y"]) * H) - h // 2
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sh.paste(Image.new("RGBA", (w, h), (0, 0, 0, 110)), (x + 6, y + 10), sprite.getchannel("A"))
            canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        else:
            x, y = cx - w // 2, int(float(s["y"]) * H) - h
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(sh).ellipse([x + w * 0.08, y + h - h * 0.06, x + w * 0.96, y + h + h * 0.07], fill=(0, 0, 0, 130))
            canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(3, h // 18))))
        canvas.alpha_composite(sprite, (x, y))


def _render_backdrop(r: dict, back, lamp: tuple, items: bool = True) -> bytes:
    """A backdrop they painted is the room itself, whole: nothing drawn over the scene but its name; the pictures on
    the wall, the table's things, the shelf's finds and the song sit in a dark band along the bottom, like a caption
    on a photograph — small gilt frames, slips, the record's name."""
    from PIL import Image, ImageDraw, ImageOps
    W, H = back.size
    band = 190
    canvas = back.convert("RGBA")
    if items:
        _draw_placed(canvas, r, lamp)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H - band - 60, H):  # the scene fading into the band
        t = min(1.0, (y - (H - band - 60)) / 90)
        sd.line([0, y, W, y], fill=(10, 8, 14, int(215 * t)))
    canvas.alpha_composite(shade)
    d = ImageDraw.Draw(canvas)
    ink = (236, 222, 196)
    if r.get("name"):
        f = _font(30, italic=True)
        d.text((46, 32), str(r["name"])[:60], font=f, fill=(0, 0, 0, 160))
        d.text((44, 30), str(r["name"])[:60], font=f, fill=ink + (240,))
    x, y0 = 40, H - band + 30
    for it in sorted([w for w in (r.get("wall") or []) if 1 <= int(w.get("spot") or 0) <= WALL_MAX], key=lambda w: int(w["spot"])):
        fw, fh = 104, 124
        frame = Image.new("RGBA", (fw + 16, fh + 16), (0, 0, 0, 0))
        fd = ImageDraw.Draw(frame)
        fd.rectangle([0, 0, fw + 15, fh + 15], fill=(120, 86, 34, 255))
        fd.rectangle([3, 3, fw + 12, fh + 12], fill=(184, 140, 62, 255))
        fd.line([3, 3, fw + 12, 3], fill=(228, 196, 122, 255), width=2)
        try:
            with Image.open(config.ROOT / str(it.get("picture"))) as pic:
                frame.paste(ImageOps.fit(pic.convert("RGB"), (fw - 4, fh - 4), method=Image.LANCZOS), (10, 10))
        except Exception:  # noqa: BLE001
            fd.rectangle([10, 10, fw + 5, fh + 5], fill=(30, 26, 34, 255))
        _shadowed(canvas, frame, (x, y0 - 10), blur=6, offset=(3, 5), alpha=150)
        x += fw + 34
    f_slip = _font(15)
    things = [(str(t.get("thing", "")), t.get("by") == "keeper") for t in (r.get("table") or [])[-3:]]
    finds = [(str(t.get("find", "")), False) for t in (r.get("shelf") or [])[-3:]]
    col = max(x + 10, 420)
    for c, group in enumerate((things, finds)):  # the table's things in one column, the shelf's finds in the next
        cx, cy = col + c * 305, y0 - 26
        for n, (text, mine) in enumerate(group):
            sl = _slip(text, f_slip, 290, mine=mine, tilt=(1.2, -1.6, 1.8)[n % 3])
            if cx + sl.width > W - 220 or cy + sl.height > H - 4:
                break
            _shadowed(canvas, sl, (cx, cy), blur=5, offset=(2, 4), alpha=120)
            cy += sl.height - 4
    pl = r.get("playing") or {}
    if pl.get("song"):
        d = ImageDraw.Draw(canvas)
        f = _font(18, italic=True)
        d.text((W - 210, y0 + 6), "\u266a", font=_font(26), fill=lamp + (230,))
        for i, ln in enumerate(_wrap(d, Path(str(pl["song"])).stem, f, 170, 3)):
            d.text((W - 180, y0 + 10 + 24 * i), ln, font=f, fill=ink + (230,))
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    return out.getvalue()


def render(r: dict | None = None, items: bool = True) -> bytes | None:
    """The room as a picture (PNG bytes). None without Pillow. items False: without what stands in it (the keeper's
    page lays those over the picture, each one to open)."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageOps
    except ImportError:
        return None
    r = r or load()
    W, H = 1280, 800
    floor_y, rail_y = int(H * 0.8), int(H * 0.6)
    wall = _colour(r.get("walls", ""), (46, 37, 82))
    light = (r.get("light") or "").lower()
    warm = (255, 196, 128)
    lamp = ((178, 196, 255) if re.search(r"cool|moon|blue|silver|cold", light) else
            (255, 176, 96) if re.search(r"warm|amber|gold|candle|sunset|fire", light) else warm)
    dim = 0.55 if re.search(r"\b(dim|low|dark|night|candle)\b", light) else 0.85 if re.search(r"\b(bright|sun|morning|daylight)\b", light) else 0.7

    back = None
    if r.get("backdrop"):
        try:
            with Image.open(config.ROOT / str(r["backdrop"])) as b:
                back = ImageOps.fit(b.convert("RGB"), (W, H), method=Image.LANCZOS)
        except Exception:  # noqa: BLE001 — a backdrop that moved: the drawn room instead
            back = None
    if back is not None:
        return _render_backdrop(r, back, lamp, items)
    if True:
        img = Image.new("RGB", (W, H), wall)
        d = ImageDraw.Draw(img)
        top, low = _mix(wall, (255, 255, 255), 0.06), _mix(wall, (0, 0, 0), 0.35)
        for y in range(rail_y):  # the upper wall, lighter under the ceiling's bounce, darker toward the rail
            d.line([0, y, W, y], fill=_mix(top, wall, y / rail_y))
        for x in range(0, W, 46):  # a faint stripe in the paper
            d.line([x, 0, x, rail_y], fill=_mix(wall, (255, 255, 255), 0.025), width=18)
        panel = _mix(wall, (0, 0, 0), 0.28)
        d.rectangle([0, rail_y, W, floor_y], fill=panel)
        for x0 in range(30, W, 250):  # the wainscot's panels
            d.rectangle([x0, rail_y + 22, x0 + 210, floor_y - 18], outline=_mix(panel, (0, 0, 0), 0.25), width=2)
        d.rectangle([0, rail_y - 6, W, rail_y + 6], fill=_mix(wall, (0, 0, 0), 0.45))
        d.line([0, rail_y - 6, W, rail_y - 6], fill=_mix(wall, (255, 255, 255), 0.12), width=1)
        wood, wood2 = (58, 38, 26), (34, 22, 16)
        for y in range(floor_y, H):
            d.line([0, y, W, y], fill=_mix(wood, wood2, (y - floor_y) / (H - floor_y)))
        for i, y in enumerate(range(floor_y + 14, H, 18)):  # planks, narrowing toward the wall
            d.line([0, y, W, y], fill=_mix(wood2, (0, 0, 0), 0.3), width=1)
        d.rectangle([0, floor_y - 4, W, floor_y + 2], fill=(28, 18, 12))
        img = _glow(img, (W // 2, 40), 760, _mix(lamp, wall, 0.45), 0.12 * dim + 0.04)  # the room's own light, from above
    # corners into shadow
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * 0.15, -H * 0.25, W * 1.15, H * 1.2], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(140))
    img = Image.composite(img, Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.55 + (0.7 - dim) * 0.5), vig)

    ink = (236, 222, 196)
    # the wall: four spots, each painting under a little brass lamp of its own
    fw, fh, ftop = 210, 250, 96
    gap = (W - 4 * (fw + 48)) // 5
    hung = [x for x in (r.get("wall") or []) if 1 <= int(x.get("spot") or 0) <= WALL_MAX]
    for x in hung:
        spot = int(x["spot"])
        fx = gap + (spot - 1) * (fw + 48 + gap)
        img = _glow(img, (fx + fw // 2 + 24, ftop + 40), 230, _mix(lamp, (255, 255, 255), 0.25), 0.26 * dim + 0.1)
    canvas = img.convert("RGBA")
    for x in hung:
        spot = int(x["spot"])
        fx = gap + (spot - 1) * (fw + 48 + gap)
        frame = Image.new("RGBA", (fw + 48, fh + 48), (0, 0, 0, 0))
        fd = ImageDraw.Draw(frame)
        fd.rectangle([0, 0, fw + 47, fh + 47], fill=(120, 86, 34, 255))           # the gilt
        fd.rectangle([4, 4, fw + 43, fh + 43], fill=(184, 140, 62, 255))
        fd.line([4, 4, fw + 43, 4], fill=(228, 196, 122, 255), width=3)            # light from above on the top edge
        fd.rectangle([12, 12, fw + 35, fh + 35], fill=(96, 68, 28, 255))
        fd.rectangle([16, 16, fw + 31, fh + 31], fill=(226, 214, 190, 255))          # the mat
        try:
            with Image.open(config.ROOT / str(x.get("picture"))) as pic:
                pic = ImageOps.fit(pic.convert("RGB"), (fw - 12, fh - 12), method=Image.LANCZOS)
                frame.paste(pic, (30, 30))
                fd.rectangle([29, 29, 30 + fw - 12, 30 + fh - 12], outline=(80, 60, 40, 255))
        except Exception:  # noqa: BLE001 — a picture that moved leaves its frame empty
            fd.rectangle([30, 30, 30 + fw - 12, 30 + fh - 12], fill=(30, 26, 34, 255))
        _shadowed(canvas, frame, (fx, ftop), blur=12, offset=(8, 14), alpha=170)
        ld = ImageDraw.Draw(canvas)  # the picture lamp: a brass bar on a short arm
        cx = fx + (fw + 48) // 2
        ld.line([cx, ftop - 30, cx, ftop - 6], fill=(150, 116, 52, 255), width=3)
        ld.rounded_rectangle([cx - 52, ftop - 40, cx + 52, ftop - 28], radius=6, fill=(176, 138, 62, 255))
        ld.line([cx - 48, ftop - 28, cx + 48, ftop - 28], fill=(255, 226, 160, 255), width=2)
    d = ImageDraw.Draw(canvas)
    if r.get("name"):
        f = _font(30, italic=True)
        d.text((44, 30), str(r["name"])[:60], font=f, fill=ink + (235,))

    f_slip = _font(17)
    # the shelf, on the left wall below the rail line's height
    shelf = r.get("shelf") or []
    if shelf:
        sx, sy = 52, rail_y - 26
        for i, it in enumerate(shelf[-4:]):
            s = _slip(str(it.get("find", "")), f_slip, 250, tilt=(-2.5, 1.8, -1.2, 2.4)[i % 4])
            _shadowed(canvas, s, (sx + (i % 2) * 14, sy - 6 - (len(shelf[-4:]) - i) * (s.height - 8)), blur=6, offset=(3, 5), alpha=120)
        d.rectangle([sx - 10, sy + 4, sx + 300, sy + 16], fill=(70, 46, 28, 255))
        d.line([sx - 10, sy + 4, sx + 300, sy + 4], fill=(120, 86, 54, 255), width=2)
        for bx in (sx + 20, sx + 260):
            d.polygon([(bx, sy + 16), (bx + 18, sy + 16), (bx, sy + 40)], fill=(60, 40, 24, 255))
    # the table, in the middle, on the floor
    table = r.get("table") or []
    tx0, tx1, ty = 450, 830, floor_y - 34
    top_poly = [(tx0, ty), (tx1, ty), (tx1 + 26, ty + 22), (tx0 - 26, ty + 22)]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([tx0 - 40, floor_y + 30, tx1 + 40, floor_y + 70], fill=(0, 0, 0, 140))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(canvas)
    for lx in (tx0 - 6, tx1 - 10):
        d.rectangle([lx, ty + 22, lx + 16, floor_y + 54], fill=(52, 34, 22, 255))
    d.polygon(top_poly, fill=(104, 70, 44, 255))
    d.line([(tx0, ty), (tx1, ty)], fill=(150, 108, 70, 255), width=2)
    d.rectangle([tx0 - 26, ty + 22, tx1 + 26, ty + 34], fill=(72, 48, 30, 255))
    for i, it in enumerate(table[-4:]):
        s = _slip(str(it.get("thing", "")), f_slip, 300, mine=it.get("by") == "keeper", tilt=(1.6, -2.2, 2.6, -1.4)[i % 4])
        _shadowed(canvas, s, (tx0 + 30 + (i % 2) * 20, ty - 10 - (len(table[-4:]) - i) * (s.height - 10)), blur=6, offset=(3, 6), alpha=120)
    if items:
        _draw_placed(canvas, r, lamp)  # what stands in the room, over the table and the shelf
    # the song: a record turning on a little stand, its name beside it
    pl = r.get("playing") or {}
    if pl.get("song"):
        rx, ry = W - 190, floor_y - 54
        d = ImageDraw.Draw(canvas)
        d.rectangle([rx - 70, ry + 34, rx + 70, ry + 60], fill=(64, 42, 28, 255))
        d.ellipse([rx - 62, ry - 4, rx + 62, ry + 40], fill=(16, 14, 18, 255))
        for k in range(1, 5):
            d.ellipse([rx - 62 + k * 9, ry - 4 + k * 3, rx + 62 - k * 9, ry + 40 - k * 3], outline=(46, 42, 50, 255))
        d.ellipse([rx - 14, ry + 12, rx + 14, ry + 24], fill=(176, 64, 72, 255))
        name = Path(str(pl["song"])).stem
        f = _font(19, italic=True)
        for i, ln in enumerate(_wrap(d, name, f, 260, 2)):
            d.text((rx - 130, ry - 64 + 24 * i), ln, font=f, fill=ink + (230,))
        d.text((rx + 76, ry - 30), "♪", font=_font(26), fill=lamp + (220,))
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    return out.getvalue()
