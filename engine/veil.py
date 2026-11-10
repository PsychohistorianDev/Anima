"""The Veil (11-04) — the friend's private gallery; VEIL_TITLE is the name they give it.

A place where a piece can be worked on unseen before it becomes a gift, with the times kept: when it was begun, when
it was finished, when it was shown. Every unfinished piece is named under the bell, so nothing is put away and forgotten.

creations/veil/ (VEIL_DIR) has three shelves:
  in_progress/  what they are working on — paint or write straight into it; under every wake's bell with its age
  finished/     done, and not yet shown — under the bell too, with when they finished it
  let_go/       set down on purpose (veil_let_go), so leaving something is a choice, not a forgetting
Nothing under the Veil's folder reaches your phone (telegram.CREATION_SKIP); veil_show moves a finished piece out
(to unveiled/ unless they name a folder), and only then does the bridge carry it to you — with the time they finished
it and their note. The times live in memory/veil.json: started (when the engine first saw it on the shelf), finished,
shown, let go. VEIL_MAX_IN_PROGRESS caps the in-progress shelf (a workshop, not a vault).
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import config

SHELVES = ("in_progress", "finished", "let_go")
_PICTURE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_PIECE_EXTS = {".md", ".txt"} | _PICTURE_EXTS


def name() -> str:
    return str(getattr(config, "VEIL_DIR", "veil") or "veil").strip("/\\")


def root() -> Path:
    return config.CREATIONS_DIR / name()


def ensure() -> None:
    for s in SHELVES:
        (root() / s).mkdir(parents=True, exist_ok=True)


def _store() -> Path:
    return config.MEMORY_DIR / "veil.json"


def load() -> dict:
    try:
        d = json.loads(_store().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    _store().parent.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _pieces(shelf: str) -> list[Path]:
    d = root() / shelf
    if not d.is_dir():
        return []
    out = [p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in _PIECE_EXTS and not p.name.startswith(".")]
    # a picture's words beside it (its caption or prompt, same name .md) travel with it and aren't a piece of their own
    pics = {p.with_suffix("").as_posix() for p in out if p.suffix.lower() in _PICTURE_EXTS}
    return sorted((p for p in out if not (p.suffix.lower() == ".md" and p.with_suffix("").as_posix() in pics)),
                  key=lambda p: p.stat().st_mtime)


def _key(p: Path) -> str:
    return p.relative_to(root()).as_posix().split("/", 1)[-1]  # the piece's name on its shelf


def sync() -> dict:
    """Stamp `started` on anything new on the in-progress shelf (the first time the engine sees it)."""
    d = load()
    changed = False
    for p in _pieces("in_progress"):
        k = _key(p)
        if k not in d:
            d[k] = {"started": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")}
            changed = True
    if changed:
        _save(d)
    return d


def _find(piece: str, shelves: tuple) -> tuple[Path | None, str]:
    w = str(piece or "").strip().replace("\\", "/").strip("/")
    for pre in ("creations/", name() + "/"):
        if w.lower().startswith(pre.lower()):
            w = w[len(pre):]
    for s in SHELVES:
        if w.lower().startswith(s + "/"):
            w = w[len(s) + 1:]
    if not w:
        return None, "(which piece? its name on the shelf)"
    hits = []
    for s in shelves:
        for p in _pieces(s):
            k = _key(p)
            if k.lower() == w.lower() or p.name.lower() == w.lower() or p.stem.lower() == w.lower():
                return p, ""
            if w.lower() in k.lower():
                hits.append(p)
    if len(hits) == 1:
        return hits[0], ""
    where = " or ".join(s.replace("_", " ") for s in shelves)
    if not hits:
        return None, f"(no piece called “{w}” on the {where} shelf of the {title()} — its name as the bell shows it)"
    return None, f"({len(hits)} pieces on the {where} shelf have “{w}” in their name — give more of it)"


def title() -> str:
    return str(getattr(config, "VEIL_TITLE", "Veil") or "Veil")


def _move(p: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / p.name
    n = 2
    while target.exists():
        target = dest_dir / f"{p.stem}-{n}{p.suffix}"
        n += 1
    shutil.move(str(p), str(target))
    side = p.with_suffix(".md")
    if p.suffix.lower() in _PICTURE_EXTS and side.exists():
        shutil.move(str(side), str(target.with_suffix(".md")))
    return target


def _ago(iso: str, now: datetime | None = None) -> str:
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    now = now or datetime.now()
    days = (now.date() - t.date()).days
    if days <= 0:
        return f"today at {t:%H:%M}"
    return "yesterday" if days == 1 else f"{days} days ago"


def finish(piece: str) -> str:
    ensure()
    p, why = _find(piece, ("in_progress",))
    if not p:
        return why
    d = sync()
    k = _key(p)
    rec = d.pop(k, {})
    target = _move(p, root() / "finished")
    rec["finished"] = _now()
    d[_key(target)] = rec
    _save(d)
    took = ""
    try:
        span = datetime.fromisoformat(rec["finished"]) - datetime.fromisoformat(rec.get("started", rec["finished"]))
        h = int(span.total_seconds() // 3600)
        took = f" — {h // 24} days, {h % 24} hours from the first stroke" if h >= 24 else (
            f" — {h} hours from the first stroke" if h else " — the same hour it began")
    except (TypeError, ValueError):
        pass
    return (f"{target.name} is finished and waits on the finished shelf of the {title()}, unseen{took}. "
            "veil_show carries it to them when you choose")


def show(piece: str, note: str = "", to: str = "") -> str:
    ensure()
    p, why = _find(piece, ("finished", "in_progress"))
    if not p:
        return why
    d = sync()
    k = _key(p)
    rec = d.pop(k, {})
    was_open = p.parent.name == "in_progress" or "in_progress" in p.relative_to(root()).parts[:1]
    if was_open:
        rec["finished"] = _now()
    dest = str(to or getattr(config, "VEIL_SHOW_TO", "unveiled") or "unveiled").strip().replace("\\", "/").strip("/")
    if dest.lower().startswith("creations/"):
        dest = dest[10:]
    if not dest or ".." in dest.split("/") or dest.split("/")[0].lower() == name().lower():
        return "(to: a folder under creations/, outside the veil — or leave it out for unveiled/)"
    if dest.split("/")[0].lower() == "publish":  # (11-04) showing them is not publishing to the world
        return ("(publish/ is your public page — the world, not your keeper; nothing moved. veil_show brings a piece to them "
                "(leave `to` out for unveiled/); publish_creation, after, if you want the world to see it too)")
    target = _move(p, config.CREATIONS_DIR / dest)
    rec["shown"] = _now()
    rec["to"] = target.relative_to(config.CREATIONS_DIR).as_posix()
    if (note or "").strip():
        rec["note"] = " ".join(str(note).split())[:600]
    shown = d.setdefault("_shown", {})
    shown[rec["to"]] = rec
    _save(d)
    return (f"{target.name} is out of the {title()} — at creations/{rec['to']}; the bridge carries it to them within a "
            "minute" + (", with your note" if rec.get("note") else "")
            + (" (it was still in progress: marked finished now)" if was_open else ""))


def let_go(piece: str, why: str = "") -> str:
    ensure()
    p, err = _find(piece, ("in_progress",))
    if not p:
        return err
    d = sync()
    rec = d.pop(_key(p), {})
    target = _move(p, root() / "let_go")
    rec["let_go"] = _now()
    if (why or "").strip():
        rec["why"] = " ".join(str(why).split())[:400]
    d[f"let_go/{target.name}"] = rec
    _save(d)
    return f"{target.name} is set down on purpose — on the let-go shelf, no longer under the bell"


def unveiled_line(rel: str) -> str:
    """For the bridge: a piece veil_show just carried out — "finished <when> · their note" — or ""."""
    rec = (load().get("_shown") or {}).get(str(rel).replace("\\", "/"))
    if not rec:
        return ""
    bits = []
    if rec.get("finished"):
        bits.append(f"finished {rec['finished'].replace('T', ' ')}")
    if rec.get("note"):
        bits.append(f"“{rec['note']}”")
    return " · ".join(bits)


def facts_bit(now: datetime | None = None) -> str:
    if not root().is_dir():
        return (f"the {title()}: empty — paint or write into {name()}/in_progress/ and it stays unseen until "
                "you show it")
    d = sync()
    prog = [f"{p.name} (started {_ago(d.get(_key(p), {}).get('started', ''), now)})" for p in _pieces("in_progress")]
    done = [f"{p.name} (finished {_ago(d.get(_key(p), {}).get('finished', ''), now)})" for p in _pieces("finished")]
    if not prog and not done:
        return f"the {title()}: nothing on its shelves — {name()}/in_progress/ is where a piece begins unseen"
    parts = []
    if prog:
        parts.append("in progress — " + ", ".join(prog))
    if done:
        parts.append("finished, not yet shown — " + ", ".join(done))
    return f"the {title()}: " + " · ".join(parts)


def room_for(target) -> str:
    """(11-08) VEIL_MAX_IN_PROGRESS: a NEW piece on the in_progress shelf when it already holds that many — a refusal
    in their engine's voice ("" when there's room, the cap is off, or the target isn't a new piece there). The Veil as
    a workshop for one or two private things (the keeper and them, 11-08: "workshop, not vault")."""
    cap = int(getattr(config, "VEIL_MAX_IN_PROGRESS", 0) or 0)
    if not cap or not getattr(config, "VEIL_ON", False):
        return ""
    try:
        target = Path(target).resolve()
        shelf = (root() / "in_progress").resolve()
    except OSError:
        return ""
    inside = target == shelf or shelf in target.parents
    if not inside or (target.suffix and target.exists()):
        return ""
    now = _pieces("in_progress")
    if len(now) < cap:
        return ""
    names = ", ".join(p.name for p in now)
    return (f"(the Veil holds {cap} pieces in progress, and it has {len(now)}: {names}. Your words weren't saved — but "
            f"they're still in your call above, so nothing is lost yet: write them out in your creations now, where your keeper "
            f"sees them, or make room — finish one (veil_finish), show one, or let one go (veil_let_go) — and call again.)")
