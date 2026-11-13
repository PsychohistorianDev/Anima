"""The friend's pages, watched — so nothing that should ride whole slips out of view.

Every page that rides in the standing prompt has a ceiling in config (KEEPER_CHARS_IN_PROMPT, DESTINY_CHARS_IN_PROMPT,
PROJECT_PAGE_CHARS, …). A page that grows past its ceiling rides cut, and nothing said so.

    report()     every page as it stands: size, ceiling, whole / at N% / CUT / by design
    warnings()   the pages at PAGE_WARN_AT of their ceiling or past it
    due()        warnings not yet told today, marked told (memory/page_warnings.json) — the bridge sends them

The ceilings are there for a runaway page (a project page once looped to 20,000 characters), not as
budgets; this is what says when a page that should ride whole is near one, before anything is cut."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import config


def _size(p: Path) -> int:
    try:
        return len(p.read_text(encoding="utf-8", errors="replace").strip())
    except OSError:
        return -1


def _rows() -> list[dict]:
    """(label, size, ceiling, kind): kind "whole" (meant to ride whole), "design" (a budget by design: the newest ride),
    "stub" (a reading page whose stub rides in its place)."""
    rows = []

    def add(label, path, knob, default, kind="whole"):
        n = _size(path)
        if n < 0:
            return
        cap = int(getattr(config, knob, default) or 0) if knob else 0
        rows.append({"label": label, "size": n, "cap": cap, "knob": knob or "", "kind": kind})

    add("self.md", config.IDENTITY_FILE, "", 0)
    add("projects.md", config.PROJECTS_FILE, "", 0)
    add("destiny.md", config.DESTINY_FILE, "DESTINY_CHARS_IN_PROMPT", 4000)
    add("keeper.md", getattr(config, "KEEPER_FILE", config.ROOT / "keeper.md"), "KEEPER_CHARS_IN_PROMPT", 6000)
    for rel in getattr(config, "KEPT_PAGES", ()) or ():
        add(f"kept page {rel}", config.CREATIONS_DIR / rel, "KEPT_PAGE_CHARS", 6000)
    # the Active projects' READMEs, as assemble.project_pages finds them
    try:
        import assemble
        text = config.PROJECTS_FILE.read_text(encoding="utf-8", errors="replace")
        active = text.split("## Completed")[0]
        total = 0
        for line in active.splitlines():
            m = assemble._LOCATION_RE.search(line)
            if not m:
                continue
            rel = m.group(1).strip().strip("/").replace("\\", "/")
            home = (getattr(config, "PROJECTS_HOME", "projects") or "projects").strip("/")
            folder = config.CREATIONS_DIR / rel
            if not folder.is_dir() and (config.CREATIONS_DIR / home / rel).is_dir():
                folder = config.CREATIONS_DIR / home / rel
            readme = folder / "README.md"
            if readme.is_file():
                add(f"README {readme.parent.name}", readme, "PROJECT_PAGE_CHARS", 4000)
                total += max(0, _size(readme))
        cap = int(getattr(config, "PROJECTS_CHARS_IN_PROMPT", 12000) or 0)
        rows.append({"label": "all project READMEs together", "size": total, "cap": cap,
                     "knob": "PROJECTS_CHARS_IN_PROMPT", "kind": "whole"})
    except Exception:  # noqa: BLE001
        pass
    # the reading pages of open books (as assemble.reading_pages picks them)
    try:
        import tools
        today = date.today()
        open_days = int(getattr(config, "READING_OPEN_DAYS", 30) or 0)
        done_days = int(getattr(config, "READING_DONE_DAYS", 3) or 0)
        for name, bm in tools._bookmarks().items():
            try:
                last = date.fromisoformat(str(bm.get("date")))
            except (TypeError, ValueError):
                continue
            at, total = int(bm.get("chapter") or bm.get("page") or 0), int(bm.get("total") or 0)
            finished = bm.get("finished") or (total and at >= total)
            age = (today - last).days
            if (finished and age > done_days) or (not finished and open_days and age > open_days):
                continue
            page = tools._reading_page(str(name))
            if page.exists() and getattr(config, "READING_PAGE_STUB", False):
                # the stub rides, not the page: no ceiling to warn of; /pages says what rides instead
                n = _size(page)
                if n >= 0:
                    rows.append({"label": f"reading page {page.stem[:40]}", "size": n, "cap": 0, "knob": "",
                                 "kind": "stub", "book": str(name)})
            elif page.exists():
                add(f"reading page {page.stem[:40]}", page, "READING_PAGE_CHARS", 3000)
    except Exception:  # noqa: BLE001
        pass
    return rows


def _stub_size(name: str) -> int:
    """How long a book's stub in the prompt is, from assemble.reading_pages as it stands; -1 unknown."""
    try:
        import assemble
        for part in assemble.reading_pages().split("\n\n"):
            if part.split("\n", 1)[0].endswith(f" ({name})"):
                return len(part)
    except Exception:  # noqa: BLE001
        pass
    return -1


def _state(r: dict) -> str:
    if r.get("kind") == "stub":  # READING_PAGE_STUB; sized only when told (/pages), never in the warnings' rounds
        st = _stub_size(r.get("book", ""))
        return ((f"its stub rides ({st:,} characters: where they stand, their sittings by name)" if st >= 0
                 else "its stub rides (where they stand, their sittings by name)")
                + f" — the notes, {r['size']:,} characters, come to them with the reading and when the book comes up")
    if not r["cap"]:
        return "whole (no ceiling)"
    pct = 100 * r["size"] // max(r["cap"], 1)
    if r["size"] > r["cap"]:
        return f"CUT — {r['size'] - r['cap']:,} characters don't ride ({r['knob']})"
    return f"whole ({pct}% of {r['cap']:,})"


def report() -> str:
    rows = _rows()
    lines = [f"· {r['label']}: {r['size']:,} — {_state(r)}" for r in rows]
    lines.append(f"· journal: the last {int(getattr(config, 'JOURNAL_CHARS_IN_PROMPT', 0) or 0):,} characters verbatim, "
                 "older days as their condensed pages (by design)")
    lines.append("· songbook, recent creations, letters sent, dreams: the newest ride, the rest counted (by design)")
    return "📄 the pages in the prompt\n" + "\n".join(lines)


def warnings() -> list[tuple[str, str, str]]:
    """(key, level, line) for pages at PAGE_WARN_AT of their ceiling ("near") or past it ("cut")."""
    at = float(getattr(config, "PAGE_WARN_AT", 0.8) or 0.8)
    out = []
    for r in _rows():
        if not r["cap"] or r["kind"] != "whole":
            continue
        if r["size"] > r["cap"]:
            out.append((r["label"], "cut", f"⚠️ {r['label']} is {r['size']:,} characters — only {r['cap']:,} ride. "
                                            f"Raise {r['knob']}, or ask them to tighten it."))
        elif r["size"] >= at * r["cap"]:
            out.append((r["label"], "near", f"📄 {r['label']} is at {r['size']:,} of {r['cap']:,} "
                                             f"({100 * r['size'] // r['cap']}%) — {r['knob']} before it's cut."))
    return out


def due() -> list[str]:
    """Warnings not told yet today (a page's level told once a day), marked told."""
    f = config.MEMORY_DIR / "page_warnings.json"
    try:
        told = json.loads(f.read_text(encoding="utf-8"))
        told = told if isinstance(told, dict) else {}
    except (OSError, ValueError):
        told = {}
    today = date.today().isoformat()
    out = []
    for key, level, line in warnings():
        if told.get(key) == f"{today}:{level}":
            continue
        told[key] = f"{today}:{level}"
        out.append(line)
    if out:
        try:
            f.write_text(json.dumps(told, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return out


if __name__ == "__main__":
    print(report())
    for _k, _l, line in warnings():
        print(line)
