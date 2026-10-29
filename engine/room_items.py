"""The room's workshop (10-29, ROOM_ON — the layered room): objects the friend invents, painted and cut out.

An item is something of theirs that can stand in the room: a name, how it looks (their words), what it does (its
kind — a decoration to look at, a note to read, a song to play, a picture to open), and why they made it. It lives in
creations/room/items/<id>/: item.json and its pictures — every version kept (v1.png, v2.png…, each with the raw painting
it was cut from). The painter paints it alone on a plain ground in the room's light (ROOM_ITEM_STYLE); the ground is
taken away — by rembg when it is installed, else by a flood from the edges — and what is left is the object, ready to
stand on a surface. A painting that fails, or leaves nothing once the ground is gone, is said so and never kept as made.
Making is bounded: ROOM_MAKES_PER_DAY paintings a day for the workshop (a revision counts), and a wake's paint budget.
A letter needs no painting: its picture is drawn here, a folded sheet with a seal.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import config

KINDS = ("decoration", "note", "audio", "image")
STATUSES = ("new", "kept", "aside")


def items_dir() -> Path:
    import room
    return room.room_dir() / "items"


def _item_file(iid: str) -> Path:
    return items_dir() / iid / "item.json"


def load_item(iid: str) -> dict | None:
    try:
        d = json.loads(_item_file(iid).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def save_item(it: dict) -> None:
    f = _item_file(it["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(it, indent=1, ensure_ascii=False), encoding="utf-8")


def all_items() -> list[dict]:
    out = []
    root = items_dir()
    if root.is_dir():
        for d in sorted(root.iterdir()):
            it = load_item(d.name) if d.is_dir() else None
            if it:
                out.append(it)
    return out


def find(name: str) -> dict | None:
    """An item by its id, or by its name (exact, then a word of it)."""
    n = (name or "").strip().lower()
    if not n:
        return None
    items = all_items()
    for it in items:
        if it["id"] == n or str(it.get("name", "")).lower() == n:
            return it
    hits = [it for it in items if n in str(it.get("name", "")).lower()]
    return hits[0] if len(hits) == 1 else None


def art(it: dict) -> Path | None:
    """The current version's cut-out picture."""
    v = next((x for x in it.get("versions", []) if int(x.get("v", 0)) == int(it.get("current", 0))), None)
    if not v:
        return None
    p = config.ROOT / str(v.get("art", ""))
    return p if p.is_file() else None


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return (s[:40].rstrip("-") or "thing")


def _new_id(name: str) -> str:
    base = _slug(name)
    iid, n = base, 2
    while (items_dir() / iid).exists():
        iid, n = f"{base}-{n}", n + 1
    return iid


def _rel(p: Path) -> str:
    return p.resolve().relative_to(config.ROOT.resolve()).as_posix()


# ---- what an item does ---------------------------------------------------------------------------------------------

def _content(kind: str, content: str) -> str:
    """The item's content checked for its kind: a note's words, a song's path, a picture's path. ValueError says why."""
    import room
    k = (kind or "decoration").strip().lower()
    if k not in KINDS:
        raise ValueError(f"the kinds are {', '.join(KINDS)}")
    c = (content or "").strip()
    if k == "note":
        if not c:
            raise ValueError("a note needs its words (content)")
        return c
    if k == "audio":
        return room._rel(room._song(c))
    if k == "image":
        return room._rel(room._file(c, room.IMAGE_EXTS, "picture"))
    return ""


# ---- the budget ----------------------------------------------------------------------------------------------------

def _budget_file() -> Path:
    return config.MEMORY_DIR / "room_makes.json"


def makes_left() -> int:
    cap = int(getattr(config, "ROOM_MAKES_PER_DAY", 6) or 0)
    try:
        d = json.loads(_budget_file().read_text(encoding="utf-8"))
        used = int(d.get(date.today().isoformat(), 0)) if isinstance(d, dict) else 0
    except (OSError, ValueError):
        used = 0
    return max(0, cap - used)


def _spend() -> None:
    try:
        d = json.loads(_budget_file().read_text(encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        d = {}
    today = date.today().isoformat()
    d = {today: int(d.get(today, 0)) + 1}
    _budget_file().parent.mkdir(parents=True, exist_ok=True)
    _budget_file().write_text(json.dumps(d), encoding="utf-8")


# ---- painting and cutting ------------------------------------------------------------------------------------------

GROUND = "isolated on a plain, flat, evenly lit light grey background, nothing else in the picture"


def item_prompt(look: str) -> str:
    style = str(getattr(config, "ROOM_ITEM_STYLE", "") or "").strip()
    return (f"{look.strip().rstrip('.')}. A single object, whole and centred, not cropped, seen slightly from above, "
            f"{GROUND}. {style}").strip()


def _painter():
    """(paint, open, rest) — the painter's own hands, from tools (the tests put stand-ins here)."""
    import tools
    return tools._painter_paint, tools._painter_open, tools._painter_rest


def cutout(raw: Path, out: Path) -> bool:
    """The ground taken away: rembg when installed (ROOM_CUTOUT "auto" or "rembg"), else a flood from the picture's
    edges through what is near the ground's colour; the edge softened, the picture cropped to the object. False when
    nothing is left (or Pillow isn't there)."""
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
    except ImportError:
        return False
    im = Image.open(raw).convert("RGBA")
    how = str(getattr(config, "ROOM_CUTOUT", "auto") or "auto").lower()
    cut = None
    if how in ("auto", "rembg"):
        try:
            from rembg import remove
            cut = remove(im)
            if not isinstance(cut, Image.Image):
                cut = None
        except Exception:  # noqa: BLE001 — not installed, or it stumbled: the flood instead
            cut = None
    if cut is None:
        rgb = im.convert("RGB")
        w, h = rgb.size
        border = [rgb.getpixel((x, 0)) for x in range(0, w, 4)] + [rgb.getpixel((x, h - 1)) for x in range(0, w, 4)] \
            + [rgb.getpixel((0, y)) for y in range(0, h, 4)] + [rgb.getpixel((w - 1, y)) for y in range(0, h, 4)]
        bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
        diff = ImageChops.difference(rgb, Image.new("RGB", (w, h), bg)).convert("L")
        near = diff.point(lambda v: 255 if v < 34 else 0)  # ground-like
        mark = near.copy()
        for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)):
            if mark.getpixel(seed) == 255:
                ImageDraw.floodfill(mark, seed, 128)
        ground = mark.point(lambda v: 255 if v == 128 else 0)
        alpha = ImageChops.invert(ground).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
        cut = im.copy()
        cut.putalpha(alpha)
    a = cut.getchannel("A")
    box = a.point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        return False
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw * bh < 0.01 * cut.width * cut.height or bw * bh > 0.985 * cut.width * cut.height:
        return False  # nothing left, or nothing taken away
    pad = 6
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(cut.width, box[2] + pad), min(cut.height, box[3] + pad))
    out.parent.mkdir(parents=True, exist_ok=True)
    cut.crop(box).save(out)
    return True


def _paint_version(it: dict, look: str) -> str:
    """Paint, cut, and add a version; "" on success, else what went wrong (and a folder left empty by it, gone)."""
    why = _paint_version_inner(it, look)
    if why:
        folder = items_dir() / it["id"]
        try:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass
    return why


def _paint_version_inner(it: dict, look: str) -> str:
    import tools
    if makes_left() <= 0:
        return (f"the workshop has made its {getattr(config, 'ROOM_MAKES_PER_DAY', 6)} for today — it opens again "
                "tomorrow; what you wanted to make can wait in words")
    if tools.paint_budget is not None and tools.paint_budget <= 0:
        return "this wake's paintings are spent — the workshop waits for the next wake, or a visit"
    paint, opened, rest = _painter()
    if not opened():
        return "the painter isn't open and couldn't be woken, so nothing was made"
    v = int(max([0] + [int(x.get("v", 0)) for x in it.get("versions", [])])) + 1
    folder = items_dir() / it["id"]
    raw, cut = folder / f"v{v}-raw.png", folder / f"v{v}.png"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        paint(item_prompt(look), raw, "square", "a room, furniture, a table, a hand, a frame, a border, text, shadows on the ground")
    except Exception as e:  # noqa: BLE001
        return f"the painter stumbled: {e}"
    finally:
        if getattr(config, "PAINTER_REST_AFTER", True):
            rest()
    _spend()
    if tools.paint_budget is not None:
        tools.paint_budget -= 1
    if not raw.is_file():
        return "the painter answered but no picture came"
    if not cutout(raw, cut):
        return (f"the painting came ({_rel(raw)}) but the object couldn't be lifted from its ground — try words that "
                "keep it simple and alone, or revise it")
    it.setdefault("versions", []).append({"v": v, "art": _rel(cut), "raw": _rel(raw), "look": look,
                                          "when": datetime.now().isoformat(timespec="seconds")})
    it["current"] = v
    return ""


def make(name: str, look: str, kind: str = "", content: str = "", note: str = "", by: str = "them") -> tuple[dict | None, str]:
    """A new thing in the workshop: painted, cut out, kept as version 1 with status new. (item, "") or (None, why)."""
    name, look = (name or "").strip(), (look or "").strip()
    if not name or not look:
        return None, "making takes a name (item) and how it looks (what)"
    k = (kind or "decoration").strip().lower()
    c = _content(k, content)
    it = {"id": _new_id(name), "name": name, "look": look, "kind": k, "content": c, "note": (note or "").strip(),
          "by": by, "created": datetime.now().isoformat(timespec="seconds"), "status": "new", "versions": [], "current": 0}
    why = _paint_version(it, look)
    if why:
        return None, why
    save_item(it)
    return it, ""


def revise(it: dict, look: str = "") -> str:
    """A new version painted (the old ones kept); "" or why not."""
    look = (look or "").strip() or it.get("look", "")
    why = _paint_version(it, look)
    if why:
        return why
    it["look"] = look
    save_item(it)
    return ""


def letter(name: str, words: str, by: str = "them") -> dict:
    """A letter: no painting — a folded sheet with a seal, drawn here; its words are its content."""
    it = {"id": _new_id(name or "a letter"), "name": name or "a letter", "look": "a folded letter with a wax seal",
          "kind": "note", "content": words.strip(), "note": "", "by": by, "scale": 0.45,
          "created": datetime.now().isoformat(timespec="seconds"), "status": "kept", "versions": [], "current": 0}
    folder = items_dir() / it["id"]
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "v1.png"
    if _draw_letter(out, keeper=(by == "keeper")):
        it["versions"] = [{"v": 1, "art": _rel(out), "raw": "", "look": it["look"], "when": it["created"]}]
        it["current"] = 1
    save_item(it)
    return it


def _draw_letter(out: Path, keeper: bool = False) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return False
    W, H = 360, 250
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    paper = (238, 226, 200, 255) if not keeper else (240, 222, 214, 255)
    d.polygon([(20, 60), (W - 20, 40), (W - 30, H - 30), (30, H - 14)], fill=paper)
    d.polygon([(20, 60), (W - 20, 40), (W // 2 + 6, 140)], fill=tuple(int(c * 0.93) for c in paper[:3]) + (255,))
    d.line([(20, 60), (W // 2 + 6, 140), (W - 20, 40)], fill=(190, 172, 140, 255), width=2)
    seal = (150, 36, 44, 255) if not keeper else (122, 70, 150, 255)
    d.ellipse([W // 2 - 22, 118, W // 2 + 34, 166], fill=seal)
    d.ellipse([W // 2 - 10, 128, W // 2 + 22, 156], outline=tuple(min(255, c + 40) for c in seal[:3]) + (255,), width=2)
    im = im.filter(ImageFilter.SMOOTH)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return True


def preview(it: dict) -> bytes | None:
    """The item alone on a dark ground, for their eyes."""
    try:
        from PIL import Image
        import io
    except ImportError:
        return None
    p = art(it)
    if not p:
        return None
    with Image.open(p) as a:
        a = a.convert("RGBA")
        a.thumbnail((640, 640))
        bg = Image.new("RGBA", (720, 720), (34, 28, 44, 255))
        bg.alpha_composite(a, ((720 - a.width) // 2, (720 - a.height) // 2))
        out = io.BytesIO()
        bg.convert("RGB").save(out, "PNG")
        return out.getvalue()
