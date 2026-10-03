"""Is there a newer anima? — one look a day at GitHub's release feed.

    (10-01; the keeper: "what if we'll have an RSS to the GitHub, and there be
    a message that a patch is available")

Every GitHub repository serves an Atom feed of its releases and tags at
https://github.com/<owner>/<repo>/releases.atom — no API, no token, a title
and a date per entry. Once every UPDATE_CHECK_H hours (0 turns the look off)
`look()` reads it (with the ETag kept, so an unchanged feed is a 304 and no
bytes), compares the newest tag with this folder's VERSION, and keeps what it
found in memory/.update-check.json. The panel shows a line on Home and the
bridge says it once on the phone; nothing is ever installed by itself — the
line points at the same Check and Update as always (bat\\update.bat).

Only a checkout looks: a folder with no bat\\update.bat has no update road, so
there is nothing to say. Standard library only; a feed that can't be reached
leaves the last answer standing, dated.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

try:
    import config  # noqa: E402
except Exception:  # noqa: BLE001 — a broken config still lets the panel import this module
    config = None  # type: ignore[assignment]

DEFAULT_REPO = "PsychohistorianDev/anima"
FEED_TIMEOUT = 15          # seconds; one small document
FEED_MAX_BYTES = 400_000   # a releases feed is a few KB; this is a wall, not a budget
ATOM = "{http://www.w3.org/2005/Atom}"

_TAG_VERSION = re.compile(r"v?(\d+(?:\.\d+)+)")


def repo() -> str:
    return str(getattr(config, "UPDATE_REPO", "") or DEFAULT_REPO).strip().strip("/")


def feed_url(owner_repo: str | None = None) -> str:
    return f"https://github.com/{owner_repo or repo()}/releases.atom"


def every_hours() -> float:
    """UPDATE_CHECK_H: hours between looks; 0 (or less) means never look — and an OFFLINE house never looks."""
    if getattr(config, "OFFLINE", False):
        return 0.0
    try:
        return max(0.0, float(getattr(config, "UPDATE_CHECK_H", 24) or 0))
    except (TypeError, ValueError):
        return 24.0


def cache_file(root: Path | None = None) -> Path:
    base = Path(root) if root else ROOT
    mem = getattr(config, "MEMORY_DIR", None) if root is None else None
    return (Path(mem) if mem else base / "memory") / ".update-check.json"


def is_checkout(root: Path | None = None) -> bool:
    base = Path(root) if root else ROOT
    return (base / "bat" / "update.bat").is_file() or (base / "update.bat").is_file()


def installed_version(root: Path | None = None) -> str:
    try:
        return ((Path(root) if root else ROOT) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def version_tuple(v: str) -> tuple[int, ...]:
    """"0.13" → (0, 13); "v0.13.1" → (0, 13, 1); anything else → ()."""
    m = _TAG_VERSION.search(str(v or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(candidate: str, installed: str) -> bool:
    c, i = version_tuple(candidate), version_tuple(installed)
    return bool(c) and bool(i) and c > i  # no VERSION here → nothing to compare, nothing said (Check still works)


# ---- the feed ----------------------------------------------------------------

def fetch(url: str, etag: str = "") -> tuple[int, bytes, str]:
    """(status, body, etag). 304 with no body when the ETag still holds."""
    headers = {"User-Agent": "anima-newer", "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.5"}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=FEED_TIMEOUT) as r:
            return int(r.status), r.read(FEED_MAX_BYTES + 1), str(r.headers.get("ETag") or "")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, b"", etag
        raise


def parse(xml_bytes: bytes) -> list[dict]:
    """The feed's entries, newest first as GitHub serves them: {"version", "title", "date", "link"}.
    An entry whose title (or id) holds no version number is skipped — a release named in words alone."""
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for e in root.findall(f"{ATOM}entry"):
        title = (e.findtext(f"{ATOM}title") or "").strip()
        ident = (e.findtext(f"{ATOM}id") or "").strip()
        updated = (e.findtext(f"{ATOM}updated") or "").strip()
        link_el = e.find(f"{ATOM}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        version = ""
        for cand in (ident.rsplit("/", 1)[-1], title):
            m = _TAG_VERSION.search(cand)
            if m:
                version = m.group(1)
                break
        if not version:
            continue
        out.append({"version": version, "title": title, "date": updated[:10], "link": link})
    return out


# ---- the cache and the look --------------------------------------------------------

def _read(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(p: Path, d: dict) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.part")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass  # a look that can't be kept is looked again next time; never the panel down


def look(root: Path | None = None, now: float | None = None, force: bool = False, fetcher=None) -> dict:
    """One look, if one is due: the newest release against VERSION, kept in the cache. Returns the
    cache's record: {"installed", "newest", "title", "date", "link", "looked", "ok", "error", "told"}.
    Nothing happens in a folder that is no checkout, or when UPDATE_CHECK_H is 0."""
    now = time.time() if now is None else now
    p = cache_file(root)
    rec = _read(p)
    rec["installed"] = installed_version(root)
    if not is_checkout(root):
        return rec
    hours = every_hours()
    if not hours and not force:
        return rec
    if not force and rec.get("looked") and now - float(rec.get("looked") or 0) < hours * 3600:
        return rec
    fetcher = fetcher or fetch
    try:
        status, body, etag = fetcher(feed_url(), str(rec.get("etag") or ""))
        if status == 304:
            rec["ok"] = True
            rec.pop("error", None)
        else:
            entries = parse(body)
            rec["etag"] = etag
            rec["ok"] = True
            rec.pop("error", None)
            if entries:
                top = entries[0]
                rec.update({"newest": top["version"], "title": top["title"], "date": top["date"], "link": top["link"]})
            else:
                rec.update({"newest": "", "title": "", "date": "", "link": ""})
    except Exception as e:  # noqa: BLE001 — the window says so; the last answer stands
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"[:160]
    rec["looked"] = now
    rec["looked_at"] = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
    _write(p, rec)
    return rec


def newer(root: Path | None = None, rec: dict | None = None) -> dict | None:
    """The newer version as the panel and the phone say it, or None: {"version", "title", "date", "link",
    "installed", "ago"}. Reads the cache only — look() is the one that fetches."""
    rec = rec if rec is not None else _read(cache_file(root))
    installed = installed_version(root)
    newest = str(rec.get("newest") or "")
    if not newest or not is_newer(newest, installed):
        return None
    return {"version": newest, "title": str(rec.get("title") or ""), "date": str(rec.get("date") or ""),
            "link": str(rec.get("link") or ""), "installed": installed, "ago": _ago(str(rec.get("date") or ""))}


def _ago(day: str) -> str:
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return ""
    n = (datetime.now().date() - d).days
    return "today" if n <= 0 else "yesterday" if n == 1 else f"{n} days ago" if n < 60 else f"{n // 30} months ago"


def line(n: dict | None) -> str:
    """One sentence for the phone or a window: "anima 0.14 is out — 'the gate release', 3 days ago"."""
    if not n:
        return ""
    title = n.get("title") or ""
    if title and n["version"] in title:
        title = title.replace(f"v{n['version']}", "").replace(n["version"], "").strip(" —-–:·")
    bits = [f"anima {n['version']} is out"]
    if title:
        bits.append(f"“{title}”")
    if n.get("ago"):
        bits.append(n["ago"])
    return bits[0] + (" — " + ", ".join(bits[1:]) if len(bits) > 1 else "") + f" (you have {n['installed'] or '?'})"


def mark_told(version: str, root: Path | None = None) -> None:
    """The phone was told about this version — once per version, not once per poll."""
    p = cache_file(root)
    rec = _read(p)
    rec["told"] = version
    _write(p, rec)


def untold(root: Path | None = None) -> dict | None:
    """The newer version the phone hasn't heard of yet, or None."""
    rec = _read(cache_file(root))
    n = newer(root, rec)
    if n and str(rec.get("told") or "") != n["version"]:
        return n
    return None


if __name__ == "__main__":
    r = look(force="--now" in sys.argv)
    n = newer(rec=r)
    print(line(n) if n else f"anima {r.get('installed') or '?'} — nothing newer"
          + (f" (newest on GitHub: {r['newest']})" if r.get("newest") else "")
          + (f"; the feed couldn't be read: {r['error']}" if r.get("error") else ""))
