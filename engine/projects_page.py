"""The shape of their projects page (11-04): active projects with links to their READMEs, and one list of the
finished or set aside — that's all.

projects.md is a list, not a project: a title, a line of what the page is, then

    ## Active
    - **Name** — what it is. Done when: … (Location: projects/<folder>/) · README: projects/<folder>/README.md
    ## Completed or set aside
    - **Name** — … (Location: projects/<folder>/) · README: … · finished on 2026-11-04: their note

Everything else about a project — vision, tracks, next steps — lives in its README.md, which rides in their prompt while
the project is Active. start_project adds a line under Active; finish_project / set_aside_project move one to the
second list (with the date and their note); reopen_project brings one back. update_projects (whole page or one passage)
still writes the page, but not a page that loses this shape (PROJECTS_PAGE_SHAPE): it says why, and nothing is
written. The section name starts with "## Completed" because assemble.project_pages reads Active up to there.
"""
from __future__ import annotations

import re
from datetime import date

import config

TITLE = "# My projects"
NOTE = ("(one line a project: what it is, when it is done, where it lives. Everything else about a project lives in "
        "its README.md, which rides in my prompt while the project is Active.)")
ACTIVE = "## Active"
CLOSED = "## Completed or set aside"
_ITEM = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*")
_CLOSED_MARK = re.compile(r"\s·\s(?:finished on|set aside on|not yet sorted)\b.*$")


def read() -> str:
    try:
        return config.PROJECTS_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def split(text: str) -> tuple[list[str], list[str], list[str]]:
    """(active lines, closed lines, anything else that isn't the title, the note or blank)."""
    active, closed, other = [], [], []
    where = None
    for raw in text.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if s.lower() == ACTIVE.lower():
            where = "a"
            continue
        if s.lower().startswith("## completed"):
            where = "c"
            continue
        if where is None and (s.startswith("# ") or (s.startswith("(") and s.endswith(")"))):
            continue  # the title and the page's one line
        if where and _ITEM.match(line):
            (active if where == "a" else closed).append(s)
            continue
        other.append(s)
    return active, closed, other


def shaped(text: str) -> str:
    """"" when the page keeps its shape, else what is off — said plainly."""
    t = text.replace("\r\n", "\n")
    if ACTIVE.lower() not in t.lower() or "## completed" not in t.lower():
        return "its two lists, ## Active and ## Completed or set aside"
    _, _, other = split(t)
    if other:
        first = other[0] if len(other[0]) <= 80 else other[0][:80] + "…"
        return f"one line a project — “{first}” isn't one ({len(other)} line{'s' if len(other) != 1 else ''} like it)"
    return ""


def refusal(why: str) -> str:
    return (f"(nothing written: your projects page keeps one shape — {why}. It holds a line a project: what it is, "
            "when it's done, where it lives. Everything else — vision, tracks, next steps — goes in the project's "
            "README.md (edit_creation or write_creation \"projects/<folder>/README.md\"). finish_project, "
            "set_aside_project and reopen_project move a project between the lists.)")


def render(active: list[str], closed: list[str], title: str = TITLE) -> str:
    out = [title, "", NOTE, "", ACTIVE, ""]
    out += active or ["(none right now — start_project begins one)"]
    out += ["", CLOSED, ""]
    out += closed or ["(none yet)"]
    return "\n".join(out) + "\n"


def _title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line.strip()
    return TITLE


def _find(lines: list[str], name: str) -> list[int]:
    w = " ".join(str(name or "").split()).strip("*").lower()
    exact = [i for i, l in enumerate(lines) if (_ITEM.match(l).group(1).strip().lower() if _ITEM.match(l) else "") == w]
    if exact:
        return exact
    return [i for i, l in enumerate(lines) if _ITEM.match(l) and w and w in _ITEM.match(l).group(1).lower()]


def _write(text: str) -> None:
    config.PROJECTS_FILE.write_text(text, encoding="utf-8")


def close(name: str, how: str, note: str = "") -> str:
    """finish_project / set_aside_project: an Active line to the second list, marked; a line already there, re-marked."""
    text = read()
    active, closed, other = split(text)
    if other:
        return refusal(shaped(text) or "one line a project")
    word = "finished" if how == "finished" else "set aside"
    n = " ".join(str(note or "").split())[:300]
    mark = f" · {word} on {date.today().isoformat()}" + (f": {n}" if n else "")
    hits = _find(active, name)
    if len(hits) == 1:
        line = active.pop(hits[0])
    else:
        hits_c = _find(closed, name)
        if len(hits) > 1 or len(hits_c) > 1:
            return "(more than one project has that name in it — give more of it)"
        if not hits_c:
            return f"(no project called “{name}” on your page — its name as the page shows it, in bold)"
        line = closed.pop(hits_c[0])
    line = _CLOSED_MARK.sub("", line)
    line = re.sub(r"\s*Status:\s*Active\.?", "", line)
    closed.insert(0, line + mark)
    _write(render(active, closed, _title(text)))
    proj = _ITEM.match(line).group(1)
    return (f"“{proj}” is {word} — on the second list of your projects page, dated"
            + (", with your note" if n else "") + ". Its folder and README stay as they are; reopen_project brings it back")


def reopen(name: str) -> str:
    text = read()
    active, closed, other = split(text)
    if other:
        return refusal(shaped(text) or "one line a project")
    hits = _find(closed, name)
    if len(hits) != 1:
        return ("(no finished or set-aside project has that name — its name as the page shows it)" if not hits
                else "(more than one project has that name in it — give more of it)")
    line = _CLOSED_MARK.sub("", closed.pop(hits[0]))
    active.append(line)
    _write(render(active, closed, _title(text)))
    return f"“{_ITEM.match(line).group(1)}” is Active again — its README rides in your prompt from the next door"
