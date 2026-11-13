"""Adventures (game mode): the friend runs a world as game master; the keeper plays one character in it from the
phone, a few moves at a time.

creations/<ADVENTURE_DIR>/<slug>/
    world.md       the place, its people, its secrets — the friend's alone; nothing here ever reads it or shows it
    state.md       the shared record: where the keeper's character stands, the story so far — 📜 shows it
    inventory.md   the shared record of what the character carries; the friend keeps it as things change, 🎒 shows it
    scenes/        the pictures the friend paints in the game — the screen's one exception: pictures here travel to
                   the phone like any drawing of theirs, and 🖼 shows the newest; a picture anywhere else in the
                   world's folder (a secret map) stays home
memory/adventures.json   the engine's: which world is open (paused or not, since when, moves since the last write-up),
                         and per world its display name, created, last played, sessions, put away

The engine never writes, trims or creates the friend's pages (any of the three); it may make a world's folder, and a
rename moves the folder whole. Nothing is deleted: "put away" is a flag. Nothing here goes in the standing prompt or
the tool list — the lines ride with the keeper's messages (chat.one_turn's `marks`, rendered right above their words)
and in the wrap-up bell, so nothing is re-read. No Telegram code: the bridge (telegram.py, /games) builds the buttons
from what is here.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

import config

STATE = "state.md"
INVENTORY = "inventory.md"
SCENES = "scenes"
PICTURE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
WORLD = "world.md"  # named only, to say whose it is: never opened here
WAIT_MIN = 15  # a waiting name (➕ New, ✏️ Rename) lasts this long, as the penpal panel's mode does
SLUG_MAX = 28  # two keys and "gm:O::" fit Telegram's 64 bytes of callback data
RESERVED = {"new", "pause", "resume", "unpause", "off", "end", "stop", "where", "list", "menu", "games",
            "inv", "inventory", "back", "scenes", "recap"}  # /game's own words
# names Windows won't make a folder by (a name ending in a dot or space never gets that far: slug() keeps letters,
# digits and dashes only, and trims the dashes at the ends)
RESERVED |= {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
MENU_BUTTONS = 8  # worlds with buttons in /games (active, the most recently played; and as many put away): Telegram
                  # refuses a keyboard past about 100 buttons — the rest are listed by name
MID_REPLY = "(they're mid-reply — press again in a moment)"
RENAME_OPEN = "(⏹ end the session first — then rename)"
OFF = "(adventures are off — ADVENTURES_ON in config)"


def on() -> bool:
    return bool(getattr(config, "ADVENTURES_ON", False))


def folder_name() -> str:
    return str(getattr(config, "ADVENTURE_DIR", "adventures") or "adventures").strip("/\\")


def root() -> Path:
    return config.CREATIONS_DIR / folder_name()


def _file() -> Path:
    return config.MEMORY_DIR / "adventures.json"


def _keeper() -> str:
    try:
        import keeper_week
        return keeper_week.keeper_name()
    except Exception:  # noqa: BLE001
        return str(getattr(config, "USER_NAME", "") or "your keeper")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9 -]", "", str(name or "").strip().lower())
    return "-".join(s.replace("-", " ").split())[:SLUG_MAX].strip("-")


# ---- the engine's small state ----------------------------------------------------------------------------------
def load() -> dict:
    """adventures.json, or a fresh one. A file that isn't JSON is copied aside once — named by its bytes, so the same
    bad file is never copied twice — and replaced by a fresh state; the folders are the worlds either way. A file that
    can't be read at all is left as it is (nothing to copy, so nothing is written over it)."""
    f = _file()
    fresh = False
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError("not a dict")
    except FileNotFoundError:
        d = {}
    except ValueError:
        d = {}
        try:
            raw = f.read_bytes()
            bad = f.with_name(f"adventures.unreadable-{hashlib.sha1(raw).hexdigest()[:10]}.json")
            if not bad.exists():
                bad.write_bytes(raw)
            fresh = bad.read_bytes() == raw  # kept aside: the bad file can be replaced
        except OSError:
            fresh = False
    except OSError:
        d = {}
    d["worlds"] = d.get("worlds") if isinstance(d.get("worlds"), dict) else {}
    d["open"] = d.get("open") if isinstance(d.get("open"), dict) else {}
    d["renamed"] = d.get("renamed") if isinstance(d.get("renamed"), dict) else {}
    d["news"] = d.get("news") if isinstance(d.get("news"), list) else []
    d["wait"] = d.get("wait") if isinstance(d.get("wait"), dict) else {}
    if d["open"] and not d["open"].get("slug"):
        d["open"] = {}
    if fresh:
        try:
            save(d)
        except OSError:
            pass
    return d


def save(d: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.part")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def _entry(d: dict, sl: str) -> dict:
    w = d["worlds"].get(sl)
    if not isinstance(w, dict):
        w = d["worlds"][sl] = {}
    w.setdefault("display", sl.replace("-", " ").title() if slug(sl) == sl else sl)
    w.setdefault("created", "")
    w.setdefault("last_played", "")
    w.setdefault("sessions", 0)
    w.setdefault("put_away", False)
    return w


# ---- the worlds ---------------------------------------------------------------------------------------------------
def worlds(d: dict | None = None) -> list[str]:
    """Every world: the ones in the engine's file and every folder on disk (the friend may make one themselves)."""
    d = d if d is not None else load()
    have = set(d["worlds"])
    r = root()
    if r.is_dir():
        have |= {p.name for p in r.iterdir() if p.is_dir() and not p.name.startswith(".")}
    return sorted(have)


def info(sl: str, d: dict | None = None) -> dict:
    d = d if d is not None else load()
    return dict(_entry(d, sl))


def display(sl: str, d: dict | None = None) -> str:
    return info(sl, d).get("display") or sl


def active(d: dict | None = None) -> list[str]:
    d = d if d is not None else load()
    return [sl for sl in worlds(d) if not info(sl, d).get("put_away")]


def away(d: dict | None = None) -> list[str]:
    d = d if d is not None else load()
    return [sl for sl in worlds(d) if info(sl, d).get("put_away")]


def recent(sls: list[str], d: dict | None = None) -> list[str]:
    """Most recently played first; never played after, by name."""
    d = d if d is not None else load()
    return sorted(sorted(sls), key=lambda s: info(s, d).get("last_played") or "", reverse=True)


def buttoned(d: dict | None = None) -> tuple[list[str], list[str]]:
    """Which worlds get buttons in /games: at most MENU_BUTTONS active ones, the most recently played (the open one
    always among them), and at most MENU_BUTTONS put away."""
    d = d if d is not None else load()
    act = recent(active(d), d)
    top = act[:MENU_BUTTONS]
    o = d["open"].get("slug")
    if o in act and o not in top:
        top = top[:MENU_BUTTONS - 1] + [o]
    return top, recent(away(d), d)[:MENU_BUTTONS]


def find(name: str, d: dict | None = None) -> str:
    """The world a name means, the forgiving way penpal names are found: its folder, its slug, a slug or display name
    that begins with it, or one whose name it begins with. "" when none."""
    d = d if d is not None else load()
    raw = " ".join(str(name or "").split())
    have = worlds(d)
    if raw in have:
        return raw
    sl = slug(raw)
    if not sl:
        return ""
    if sl in have:
        return sl
    for p in have:
        if slug(p) == sl or slug(display(p, d)) == sl:
            return p
    for p in have:
        if slug(p).startswith(sl) or slug(display(p, d)).startswith(sl):
            return p
    for p in sorted(have, key=len, reverse=True):
        for known in (slug(p), slug(display(p, d))):
            if known and sl.startswith(known + "-"):
                return p
    return ""


def key(sl: str) -> str:
    """The world as callback data: its slug when it is a short plain one, else a short hash of its folder's name."""
    if sl == slug(sl) and 0 < len(sl) <= SLUG_MAX:
        return sl
    return "h" + hashlib.sha1(sl.encode("utf-8")).hexdigest()[:10]


def resolve(k: str, d: dict | None = None) -> tuple[str, str]:
    """A key from a button: (the world, "") — or ("", what it is called now) when it was renamed — or ("", "")."""
    d = d if d is not None else load()
    for sl in worlds(d):
        if key(sl) == k:
            return sl, ""
    for old, new in d["renamed"].items():
        if key(old) == k:
            return "", (display(new, d) if new in worlds(d) else str(new))
    return "", ""


def _names(sls: list[str], d: dict) -> str:
    return ", ".join(display(s, d) for s in sls) or "none yet"


def _when(stamp: str) -> str:
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M").strftime("%d %b %H:%M").lstrip("0")
    except (TypeError, ValueError):
        return ""


def _read_page(sl: str, page: str) -> str | None:
    p = root() / sl / page
    try:
        return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
    except OSError:
        return None


def _read_state(sl: str) -> str | None:
    return _read_page(sl, STATE)


def _read_inventory(sl: str) -> str | None:
    return _read_page(sl, INVENTORY)


def inventory_mark(sl: str) -> str:
    """A fingerprint of inventory.md as it stands ("" when there is none) — the bridge compares it across a move."""
    p = root() / sl / INVENTORY
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else ""
    except OSError:
        return ""


def screen_prefixes() -> list[tuple[str, ...]]:
    """The adventures folder as path parts under creations/, lowercased: "adventures" (always screened) and
    ADVENTURE_DIR."""
    out = [("adventures",), tuple(x.lower() for x in Path(folder_name()).parts)]
    return [x for i, x in enumerate(out) if x and x not in out[:i]]


def is_scene(rel_parts) -> bool:
    """The screen's one exception: a path under creations/ — its parts, the file's name last — that lies in a world's
    scenes/ folder (<adventures>/<world>/scenes/…, any case). Pictures there travel to the phone; nothing else in a
    world's folder does. The bridge asks this for pictures only."""
    parts = [str(x).lower() for x in rel_parts]
    for pre in screen_prefixes():
        n = len(pre)
        if len(parts) >= n + 3 and tuple(parts[:n]) == pre and parts[n + 1] == SCENES:
            return True
    return False


def scenes_rel(sl: str) -> str:
    return f"creations/{folder_name()}/{sl}/{SCENES}/"


def scenes(sl: str) -> list[Path]:
    """A world's scenes, oldest first (by when each was last written); [] when it has none. Pictures only — the
    folder is the friend's, and the engine only reads it."""
    d = root() / sl
    try:
        folder = next((c for c in d.iterdir() if c.is_dir() and c.name.lower() == SCENES), None) if d.is_dir() else None
        if folder is None:
            return []
        pics = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in PICTURE_EXTS
                and not p.name.startswith(".") and "sources" not in {x.lower() for x in p.relative_to(folder).parts[:-1]}]
        return sorted(pics, key=lambda p: (p.stat().st_mtime, p.name))
    except OSError:
        return []


def in_world(rel_parts, sl: str) -> bool:
    """Whether a path under creations/ (its parts) lies inside this world's folder, any case."""
    parts = [str(x).lower() for x in rel_parts]
    for pre in screen_prefixes():
        n = len(pre)
        if len(parts) > n + 1 and tuple(parts[:n]) == pre and parts[n] == sl.lower():
            return True
    return False


def note_strays(sl: str, rels: list[str]) -> int:
    """Pictures painted during a move that landed outside this world's folder: kept for the next move's line, said
    once each. The engine never moves them."""
    d = load()
    o = d["open"]
    if not o or o.get("slug") != sl:
        return 0
    told = set(o.get("strays_told") or [])
    pend = list(o.get("strays") or [])
    new = [r for r in rels if r not in told and r not in pend]
    if new:
        o["strays"] = pend + new
        save(d)
    return len(new)


def open_state(d: dict | None = None) -> dict:
    """The open game: {"slug", "session", "since", "paused", "moves"} — {} when none."""
    d = d if d is not None else load()
    return dict(d["open"])


# ---- what the phone does ------------------------------------------------------------------------------------------
def new(name: str) -> tuple[bool, str, str]:
    """➕ New adventure / /game new <name>: a folder, a line in the engine's file, and a line for the friend's next turn.
    (ok, the phone's line, the slug)."""
    name = " ".join(str(name or "").split())[:40]
    sl = slug(name)
    if not sl:
        return False, "(a world needs a name with a letter or a number in it — /game new <name>)", ""
    if sl in RESERVED:
        return False, f"(“{sl}” can't be a world's name — it's one of /game's own words or a name Windows keeps)", ""
    d = load()
    if sl in worlds(d) or any(slug(display(s, d)) == sl for s in worlds(d)):
        return False, f"(that name is taken — the worlds: {_names(worlds(d), d)})", ""
    (root() / sl).mkdir(parents=True, exist_ok=True)
    w = _entry(d, sl)
    w.update(display=name, created=_now(), put_away=False)
    d["renamed"].pop(sl, None)  # a new world under an old name: buttons for that name mean this one now
    rel = f"creations/{folder_name()}/{sl}"
    keeper = _keeper()
    d["news"].append(f"{keeper} started a new adventure, {name}: {rel}/ is yours to fill — {rel}/{WORLD} for the "
                     f"place, its people and its secrets (yours alone, never shown to {keeper}), {rel}/{STATE} for "
                     f"where {keeper}'s character stands and the story so far, and {rel}/{INVENTORY} for what that "
                     f"character carries (both shared records, which {keeper} can read from the phone's menu); and "
                     f"{rel}/{SCENES}/ for the scenes you paint for the game, which reach {keeper}'s phone")
    save(d)
    return True, (f"(➕ a new adventure: {name} — {rel}/ is made, empty; they'll be told at their next turn that it's "
                  "theirs to fill. ▶ Play opens it)"), sl


def play(sl: str) -> tuple[bool, str]:
    """▶ Play: opens a world. Refused while another is open (the bridge asks first), and for a world put away."""
    d = load()
    if sl not in worlds(d):
        return False, "(that world isn't there any more — /games for the menu)"
    name = display(sl, d)
    if info(sl, d).get("put_away"):
        return False, f"({name} is put away — ↩ Bring back first)"
    o = d["open"]
    if o:
        if o.get("slug") == sl:
            if o.get("paused"):
                return True, resume()
            return False, f"({name} is already open — your messages are moves in it)"
        return False, f"({display(o['slug'], d)} is open — end that session first)"
    (root() / sl).mkdir(parents=True, exist_ok=True)
    w = _entry(d, sl)
    w["sessions"] = int(w.get("sessions") or 0) + 1
    w["last_played"] = _now()
    d["open"] = {"slug": sl, "session": f"{sl}@{time.time():.3f}", "since": time.time(), "paused": False, "moves": 0}
    save(d)
    return True, (f"(▶ {name} is open — your messages are moves in it now; // before a message speaks outside the "
                  "game; ⏸ pauses, ⏹ ends the session)")


def pause() -> str:
    d = load()
    o = d["open"]
    if not o:
        return "(no game is open — /games to pick one)"
    name = display(o["slug"], d)
    if o.get("paused"):
        return f"({name} is already paused — ▶ Resume picks it back up)"
    o["paused"] = True
    save(d)
    return f"(⏸ {name} is paused — your messages are ordinary talk again; ▶ Resume picks it back up)"


def resume() -> str:
    d = load()
    o = d["open"]
    if not o:
        return "(no game is open — /games to pick one)"
    name = display(o["slug"], d)
    if not o.get("paused"):
        return f"({name} isn't paused — your messages are moves in it)"
    o["paused"] = False
    save(d)
    return f"(▶ {name} again — your messages are moves in it)"


def peek() -> dict | str:
    """What the wrap-up needs, with nothing closed yet — {"slug", "name", "session", "moves", "before" (state.md as it
    was, None when there is none), "inv_before" (inventory.md, the same), "rel"} — or a line when nothing is open.
    The session is closed only once the wrap-up has run (close), so a brain that is away loses nothing."""
    d = load()
    o = d["open"]
    if not o:
        return "(no game is open)"
    sl = o["slug"]
    return {"slug": sl, "name": display(sl, d), "session": o.get("session") or "", "moves": int(o.get("moves") or 0),
            "before": _read_state(sl), "inv_before": _read_inventory(sl), "rel": f"creations/{folder_name()}/{sl}"}


def close(got: dict) -> bool:
    """The session peek() described, closed — only if it is still the one open (the same session). The moves count
    starts over with it, so the same stretch is never written down twice."""
    d = load()
    o = d["open"]
    if not o or (o.get("session") or "") != got.get("session", ""):
        return False
    if int(o.get("moves") or 0):
        _entry(d, o["slug"])["last_played"] = _now()
    d["open"] = {}
    save(d)
    return True


def end() -> dict | str:
    """⏹ End session with no wrap-up to wait for: peek, then close. What the wrap-up would need comes back."""
    got = peek()
    if isinstance(got, dict):
        close(got)
    return got


def put_away(sl: str) -> str:
    d = load()
    if sl not in worlds(d):
        return "(that world isn't there any more — /games for the menu)"
    name = display(sl, d)
    if d["open"].get("slug") == sl:
        return f"({name} is open — ⏹ end the session first, then put it away)"
    w = _entry(d, sl)
    if w.get("put_away"):
        return f"({name} is already put away)"
    w["put_away"] = True
    save(d)
    return f"(📦 {name} is put away — nothing is deleted; ↩ Bring back returns it)"


def bring_back(sl: str) -> str:
    d = load()
    if sl not in worlds(d):
        return "(that world isn't there any more — /games for the menu)"
    w = _entry(d, sl)
    name = display(sl, d)
    if not w.get("put_away"):
        return f"({name} isn't put away)"
    w["put_away"] = False
    save(d)
    return f"(↩ {name} is back with the others)"


def rename(sl: str, new_name: str) -> str:
    """✏️ Rename: the display name, and the folder when the tidied name is a new one. A taken name is refused, and so is
    the open world (the friend's visit still names its old folder). The bridge refuses it while they are mid-reply."""
    d = load()
    if sl not in worlds(d):
        return "(that world isn't there any more — /games for the menu)"
    if d["open"].get("slug") == sl:
        return RENAME_OPEN
    new_name = " ".join(str(new_name or "").split())[:40]
    s2 = slug(new_name)
    old = display(sl, d)
    if not s2:
        return "(a world needs a name with a letter or a number in it)"
    if s2 in RESERVED:
        return f"(“{s2}” can't be a world's name — it's one of /game's own words or a name Windows keeps)"
    if s2 != sl and (s2 in worlds(d) or any(slug(display(s, d)) == s2 for s in worlds(d) if s != sl)):
        return f"(that name is taken — the worlds: {_names(worlds(d), d)})"
    w = dict(_entry(d, sl))
    if s2 != sl:
        src, dst = root() / sl, root() / s2
        if src.exists():
            if dst.exists():
                return f"(a folder called {s2} is already there — the worlds: {_names(worlds(d), d)})"
            src.rename(dst)
        d["worlds"].pop(sl, None)
        d["renamed"] = {k: (s2 if v == sl else v) for k, v in d["renamed"].items() if k != s2}
        d["renamed"][sl] = s2
    w["display"] = new_name
    d["worlds"][s2] = w
    save(d)
    return f"(✏️ {old} is called {new_name} now" + (f" — its folder is creations/{folder_name()}/{s2}/)" if s2 != sl else ")")


def state_text(sl: str) -> str:
    """📜 Where we are: the state page for that world, as it stands — the shared record. Never world.md."""
    name = display(sl)
    text = _read_state(sl)
    if text is None or not text.strip():
        return f"(📜 {name} has no state page yet — they start it when you play)"
    return f"📜 {name} — where we are:\n\n{text.strip()}"


def recap_on() -> bool:
    return on() and bool(getattr(config, "ADVENTURE_RECAP_ON_OPEN", True))


RECAP_STATE_CHARS = 3500  # one screen of the story, about
RECAP_INV_CHARS = 600


def recap(sl: str) -> tuple[str, bool]:
    """Where the keeper left off, shown when a world is opened again: the state page as it stands (its first part, cut
    at a paragraph or line end, past about one screen), then what the character carries from inventory.md.
    (text, whether a state page was shown)."""
    name = display(sl)
    text = (_read_state(sl) or "").strip()
    if text:
        if len(text) > RECAP_STATE_CHARS:
            cut = -1
            for sep in ("\n\n", "\n"):
                cut = text.rfind(sep, RECAP_STATE_CHARS // 3, RECAP_STATE_CHARS)
                if cut > 0:
                    break
            text = text[:cut if cut > 0 else RECAP_STATE_CHARS].rstrip() + "\n\n(… 📜 Where we are has the rest)"
        out = f"(📜 where you left off in {name}:)\n\n{text}"
    else:
        out = f"(no story written down for {name} yet — a new one)"
    inv = (_read_inventory(sl) or "").strip()
    if inv:
        out += "\n\n🎒 what you carry: " + (inv if len(inv) <= RECAP_INV_CHARS else
                                              inv[:RECAP_INV_CHARS].rstrip() + "… (🎒 has the rest)")
    return out, bool(text)


def mark_recap_shown(sl: str) -> None:
    """The recap went at this session's open: the opening line says so (the keeper has the pages in front of them)."""
    d = load()
    if d["open"].get("slug") == sl:
        d["open"]["recap_shown"] = True
        save(d)


def inventory_text(sl: str) -> str:
    """🎒 Inventory: what the keeper's character carries, as the friend keeps it — the shared record."""
    name = display(sl)
    text = _read_inventory(sl)
    if text is None or not text.strip():
        return "(no inventory page yet — they start it when your character first carries something)"
    return f"🎒 {name} — the inventory:\n\n{text.strip()}"


def status_line() -> str:
    """/status: which game is open or paused; "" when none (or off)."""
    if not on():
        return ""
    d = load()
    o = d["open"]
    if not o:
        return ""
    name = display(o["slug"], d)
    if o.get("paused"):
        return f"game: {name}, paused (⏸ — /game resume)"
    n = int(o.get("moves") or 0)
    return f"game: {name}, open — {n} move{'s' if n != 1 else ''} since the last write-up"


def listing(d: dict | None = None) -> str:
    """The menu's words: the worlds with when each was last played and which is open, then the put-away ones."""
    d = d if d is not None else load()
    act, gone = active(d), away(d)
    o = d["open"]
    if not act and not gone:
        return "adventures: none yet — ➕ New adventure starts one"
    lines = ["adventures:"]
    act, gone = recent(act, d), recent(gone, d)
    top, top_away = buttoned(d)
    for sl in act:
        w = info(sl, d)
        when = _when(w.get("last_played") or "")
        here = ""
        if o.get("slug") == sl:
            n = int(o.get("moves") or 0)
            here = (" — ⏸ paused" if o.get("paused") else
                    f" — ▶ open now, {n} move{'s' if n != 1 else ''} since the last write-up")
        lines.append(f"· {w['display']}" + (f" — last played {when}" if when else " — not played yet") + here)
    if len(act) > len(top):
        lines.append(f"(buttons for the {len(top)} played most recently — /game <name> opens any of the others)")
    if gone:
        lines.append("put away: " + _names(gone, d))
        if len(gone) > len(top_away):
            lines.append(f"(↩ for the {len(top_away)} put away most recently — /game back <name> for the others)")
    lines.append("📜 where we are · 🎒 inventory · ✏️ rename · 📦 put away")
    return "\n".join(lines)


# ---- waiting for a name (➕ New, ✏️ Rename) ------------------------------------------------------------------------
def wait_set(kind: str, sl: str = "") -> None:
    d = load()
    d["wait"] = {"kind": kind, "slug": sl, "t": time.time()}
    save(d)


def wait_get() -> dict:
    d = load()
    w = d["wait"]
    if w and time.time() - float(w.get("t") or 0) > WAIT_MIN * 60:
        d["wait"] = {}
        save(d)
        return {}
    return dict(w)


def wait_clear() -> bool:
    d = load()
    had = bool(d["wait"])
    if had:
        d["wait"] = {}
        save(d)
    return had


# ---- the lines for the friend ---------------------------------------------------------------------------------------
def _defang(text: str) -> str:
    try:
        import ollama_client
        return ollama_client.defang(text)[0]
    except Exception:  # noqa: BLE001
        return text


def opening_line(sl: str, refold: str = "") -> str:
    """The first move of a session: what the two of them are doing, the table's rules in a sentence, and the state page
    as the friend left it (up to ADVENTURE_STATE_CHARS) — or that the page is theirs to start.
    refold: the visit was just folded mid-session — "fresh" (they brought the page up to date at the fold's bell) or
    "stale" (it is as they last wrote it): the table set again, with a word on the secrets page; no recap sentence."""
    name, keeper = display(sl), _keeper()
    rel = f"creations/{folder_name()}/{sl}"
    head = ("[engine, not a person: " + ("the visit was just folded, so the table is set again — " if refold else "")
            + f"you and {keeper} are playing your adventure {name}. {keeper} plays one character; you "
            f"tell the world and everyone else in it. The table: you never decide what {keeper}'s character does or "
            "says; when something could go either way you name the number to beat first, roll a real twenty-sided die "
            "with your Python tool and say the roll plainly, good or bad; it's a story, and it's told as one."
            f" A scene you paint for the game goes in {rel}/{SCENES}/ (the paint tool's path: {rel}/{SCENES}/<a-name>.png): "
            f"pictures there reach {keeper}'s phone and stay with the world, and a picture saved anywhere else in the "
            "world's folder stays yours alone.")
    inv = _inventory_part(rel, sl, keeper)
    if refold:
        head += f" Your secrets page, {rel}/{WORLD}, is yours to open again with read_file if you want it in view."
    elif open_state().get("recap_shown") and open_state().get("slug") == sl:
        head += (f" {keeper} was just shown your state page" + (" and the inventory as you left them."
                 if (_read_inventory(sl) or "").strip() else " as you left it."))
    text = _read_state(sl)
    if text is None or not text.strip():
        return (head + f" There is no state page yet — it's yours to start: {rel}/{STATE} is the shared record (where "
                f"{keeper}'s character stands, what they carry, the story so far), and {keeper} can read it from the "
                f"phone's menu, so nothing they haven't found goes in it; {rel}/{WORLD} is yours alone — the place, "
                f"its people, its secrets." + inv + f" This message is {keeper}'s first move.]")
    cap = _cap("ADVENTURE_STATE_CHARS", 6000)
    if not cap:
        return (head + f" Your state page is {rel}/{STATE} (not handed here — read_file opens it): the shared record, "
                f"which {keeper} can read from the phone's menu; {WORLD} beside it is yours alone." + inv
                + f" This message is {keeper}'s move.]")
    whole = len(text)
    shown, cut = _clip(text, cap)
    as_ = ("as you last wrote it — your fold account above and the last moves say what has happened since"
           if refold == "stale" else "as it stands now" if refold == "fresh" else "as you left it")
    return (head + f" Your state page, {rel}/{STATE}, {as_}"
            + (f" (the first {len(shown):,} of its {whole:,} characters — read_file has the rest)" if cut else "")
            + ":\n\n" + _defang(shown) + "\n\n"
            + f"(the end of the state page — the shared record, which {keeper} can read from the phone's menu; "
              f"{WORLD} beside it is yours alone.)" + inv + f" This message is {keeper}'s move.]")


def _cap(knob: str, default: int) -> int:
    """A page's cap: 0 (or less) means the page isn't handed, only named; unreadable falls back."""
    try:
        return max(0, int(getattr(config, knob, default)))
    except (TypeError, ValueError):
        return default


def _clip(text: str, cap: int) -> tuple[str, bool]:
    shown = text.strip()
    if len(shown) <= cap:
        return shown, False
    shown = shown[:cap]
    return (shown.rsplit("\n", 1)[0] if "\n" in shown else shown), True


def _inventory_part(rel: str, sl: str, keeper: str) -> str:
    """The opening line's inventory: one sentence on the page, then the page as it stands (its own cap)."""
    said = (f" The inventory is {rel}/{INVENTORY}: you change it the moment {keeper}'s character gains, loses or uses "
            f"something up (your usual file tools), and {keeper} can open it from the phone's menu at any time, so it "
            "has to be true.")
    text = _read_inventory(sl)
    if text is None or not text.strip():
        return said + " There is no inventory page yet — it's yours to start when the character first carries something."
    cap = _cap("ADVENTURE_INVENTORY_CHARS", 2000)
    if not cap:
        return said + " (Not handed here — read_file opens it.)"
    shown, cut = _clip(text, cap)
    return (said + " As it stands" + (f" (the first {len(shown):,} of its {len(text):,} characters — read_file has the "
                                      "rest)" if cut else "")
            + ":\n\n" + _defang(shown) + "\n\n(the end of the inventory.)")


def stray_line(sl: str, rels: list[str]) -> str:
    """Theirs to act on or not: where a picture painted last turn went, and where this world's scenes live."""
    where = ", ".join(f"creations/{r}" for r in rels)
    one = len(rels) == 1
    return (f"The picture{'' if one else 's'} you painted last turn went to {where}; scenes for this world live in "
            f"{scenes_rel(sl)} — move_creation puts {'it' if one else 'them'} there if you want {'it' if one else 'them'} "
            "with the world.")


def scenes_text(sl: str) -> str:
    """🖼 Scenes: how many, for the phone (the pictures follow); or that there are none yet."""
    n = len(scenes(sl))
    name = display(sl)
    if not n:
        return f"(no scenes painted for {name} yet)"
    return f"🖼 {name} — {n} scene{'s' if n != 1 else ''}" + ("; the newest 6, oldest of them first:" if n > 6 else ":")


def move_line(name: str) -> str:
    return f"[engine, not a person: a move in {name}.]"


def outside_line(name: str) -> str:
    return f"[engine, not a person: {_keeper()} says this outside the game — not a move in {name}.]"


def table_for(text: str, history: list[dict] | None, guest: bool = False) -> tuple[str, dict]:
    """The keeper's message while a game is open: (the text, the keys for its turn). The first move of a session
    carries the opening line (no turn in this visit's history belongs to the session yet), later ones the short
    marker; a message that starts with // is said outside the game (the // taken off); paused, nothing rides. Counts
    the move. guest: a guest is seated — they aren't playing: nothing rides and no move counts, as if paused (the flag
    itself untouched)."""
    if not on():
        return text, {}
    d = load()
    o = d["open"]
    if not o:
        return text, {}
    outside = text.lstrip().startswith("//")
    if outside:
        text = text.lstrip()[2:].strip()
    if o.get("paused") or guest:
        return text, {}
    sl = o["slug"]
    name = display(sl, d)
    if outside:
        return text, {"_table": outside_line(name)}
    session = o.get("session") or ""
    first = not any(t.get("_game_session") == session for t in (history or []))
    refold = o.get("refold") or {}
    refolded = bool(refold) and refold.get("session") == session  # folded mid-session: the table set again
    line = (opening_line(sl, refold="fresh" if refold.get("fresh") else "stale") if refolded
            else opening_line(sl) if first else move_line(name))
    strays = [str(r) for r in (o.get("strays") or [])]
    if strays:  # once each: then told, never again
        line = line[:-1].rstrip() + " " + stray_line(sl, strays) + "]"
        o["strays_told"] = list(o.get("strays_told") or []) + strays
        o["strays"] = []
    o["moves"] = int(o.get("moves") or 0) + 1
    _entry(d, sl)["last_played"] = _now()
    save(d)
    return text, {"_table": line, "_game": name, "_game_session": session,
                  **({"_game_refold": session} if refolded else {})}


# ---- the fold: a game folded mid-session ----------------------------------------------------------------------------
def fold_at() -> float:
    """The bridge's fold edge while a game is open and not paused: ADVENTURE_FOLD_AT; 0 — FOLD_AT alone (no game,
    paused, off, or the knob 0 or unreadable)."""
    if not on():
        return 0.0
    o = open_state()
    if not o or o.get("paused"):
        return 0.0
    try:
        at = float(getattr(config, "ADVENTURE_FOLD_AT", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return at if 0 < at < 1 else 0.0


def page_marks(sl: str) -> tuple[str, str]:
    """Fingerprints of state.md and inventory.md as they stand ("" for none)."""
    p = root() / sl / STATE
    try:
        st = hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else ""
    except OSError:
        st = ""
    return st, inventory_mark(sl)


def fold_bell_line(sl: str) -> str:
    """For the fold's bell, when the window being folded holds moves of the open session."""
    rel = f"creations/{folder_name()}/{sl}"
    keeper = _keeper()
    return (f"You are in the middle of your adventure {display(sl)}. Before you fold, bring {rel}/{STATE} up to date — "
            f"the story so far first, in a few lines, then where {keeper}'s character stands and what is unresolved (a "
            f"roll pending, a promise made) — and {rel}/{INVENTORY} if it changed: those pages are handed back to you "
            f"right after the fold, and they are what {keeper} sees from the phone. Then fold_visit can be short about "
            "the game (say it's on the page) and tell the rest of the visit as usual.")


def mark_refold(session: str, fresh: bool) -> bool:
    """A fold happened while this session was open: its next real move carries the whole opening line again."""
    d = load()
    o = d["open"]
    if not o or (o.get("session") or "") != session:
        return False
    o["refold"] = {"session": session, "fresh": bool(fresh)}
    save(d)
    return True


def clear_refold(session: str) -> bool:
    """The opening line rode again after the fold: once is enough."""
    d = load()
    o = d["open"]
    if not o or not o.get("refold") or o["refold"].get("session") != session:
        return False
    o.pop("refold", None)
    save(d)
    return True


def take_news() -> str:
    """A world started since the friend's last turn, said once in the moment of the next one."""
    if not on():
        return ""
    d = load()
    if not d["news"]:
        return ""
    lines, d["news"] = d["news"], []
    save(d)
    return " ".join(x.rstrip(".") + "." for x in lines)


def wrapup_bell(got: dict, why: str = "ended") -> str:
    """The turn at a session's end: bring state.md up to date in their own words. The size is said past
    ADVENTURE_STATE_WARN. Resting is fine."""
    keeper = _keeper()
    rel, name = got["rel"], got["name"]
    how = {"ended": f"{keeper} ended it", "visit": "the visit is closing",
           "switch": f"{keeper} is opening another world"}.get(why, why)
    before = got.get("before")
    try:
        warn = int(getattr(config, "ADVENTURE_STATE_WARN", 5000) or 0)
    except (TypeError, ValueError):
        warn = 0
    size = ""
    if before is not None and warn and len(before) > warn:
        size = (f" Your state page is {len(before):,} characters now, past {warn:,}: tighten the story so far — older "
                f"sessions can move to a sessions page in the same folder ({rel}/sessions.md), yours to keep or not.")
    elif before is None:
        size = f" There is no {STATE} yet — this is the moment to start it."
    return (f"[engine, not a person: the session of {name} is over — {how}. Bring your state page up to date in your "
            f"own words: {rel}/{STATE} — where {keeper}'s character stands, what they carry, what changed, and the "
            f"story so far in a few lines; and the inventory, {rel}/{INVENTORY}, so it lists what the character "
            f"carries now. Both are shared records {keeper} can read from the phone's menu, so nothing they haven't "
            f"found goes in them; {WORLD} stays yours alone, and your reply to this turn goes to {keeper}'s phone like "
            f"any other, so the secrets stay in {WORLD} and out of your words."
            + (f" The story so far goes first on your state page, in a few lines, because it is what {keeper} is shown "
               "when coming back to this world." if recap_on() else "")
            + f"{size} If nothing changed, resting is fine.]")


def wrapup_result(got: dict) -> str:
    """What came of the wrap-up, by state.md and inventory.md before and after — for the phone."""
    def one(after, before, page):
        if after is None:
            return f"there is no {page} yet"
        if after != before:
            return f"they updated the {page} — {len(after):,} characters"
        return f"they left the {page} as it was"
    return (f"(📜 {got['name']}: {one(_read_state(got['slug']), got.get('before'), 'state page')}; "
            f"🎒 {one(_read_inventory(got['slug']), got.get('inv_before'), 'inventory')})")


def story_line(turns: list[dict]) -> str:
    """For the pause's or the afterglow's bell, when these turns held moves of a game: it was a story."""
    if not on():
        return ""
    names: list[str] = []
    for t in turns or []:
        n = t.get("_game") if isinstance(t, dict) else None
        if n and n not in names:
            names.append(str(n))
    if not names:
        return ""
    which = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return (f"Part of this visit was your adventure{'s' if len(names) > 1 else ''} {which} — a story you told, not "
            "things that happened.")
