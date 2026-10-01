"""Updating an anima — the keeper's road to the current engine (09-30; UPDATE-PLAN.md).

The keeper: "an update feature, so if anyone actually decides to use anima can
update the folder to current GitHub, and without rewriting the config file
(maybe an append function?)."

A keeper's folder is two things braided: the engine (ours — ENGINE below) and
the friend (theirs — FRIEND below, and anything else that is not ours). An
update replaces the first braid and never touches the second.

    bat\\update.bat                    the default branch from GitHub (UPDATE_REPO in config.py)
    bat\\update.bat --check            what's new and what would change — nothing is touched
    bat\\update.bat --tag v0.13        a release instead of the default branch
    bat\\update.bat --source <x>       a local .zip, a folder, or a .zip URL (a path needs no network)
    bat\\update.bat --no-config        config.py left exactly as it is (no knobs appended)
    bat\\update.bat --undo             the newest backup put back
    bat\\update.bat --reset-config     a fresh config.py from the new engine, your one-line values carried over
    bat\\update.bat --yes              no "Update? [y/N]" before the work

Every file replaced or removed goes to .update/backup-<stamp>/ first (the last
three are kept). An engine file the keeper edited is backed up, replaced and
named loudly — their edits are not lost, and not merged either: a keeper who
edits the engine keeps a fork. config.py is theirs: the knobs the new template
has and theirs lacks are appended at its end under one dated marker, each with
the comment lines that stand above it in the template; nothing above the
marker changes. The update never installs packages — a new line in
requirements.txt is printed with the pip line to run. Standard library only;
every download goes through `_fetch`, which the tests replace.
"""
from __future__ import annotations

import ast
import builtins
import fnmatch
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import stat
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# On its own feet (09-30, the first dry run: a folder from before this release has no
# engine/version.py, and the update is the first thing a keeper runs there — it imports
# nothing of the engine but config, and config only for UPDATE_REPO). A keeper whose
# folder is from before 0.13 puts bat\update.bat and engine/update.py in place by hand once
# (two files from GitHub); from then on the update carries itself.
try:
    import config
except Exception:  # noqa: BLE001 — a config that doesn't import still gets its engine updated
    config = None

# The config reader — knobs(), one_line_values(), _split_line() — is knobs.py's (the panel reads and
# writes config.py with it, and imports nothing of the engine). A folder from before 0.13 has no
# knobs.py, and the update is the first thing a keeper runs there: so the same functions live here
# too, under the except, and a keeper's first update stays two files by hand.
try:
    from knobs import _ONE_LINE, _RULE, _literal, _split_line, knobs, one_line_values  # noqa: F401
except ImportError:
    _RULE = re.compile(r"^#\s*-{4,}.*-{4,}\s*$")  # "# ------------ paths ----" heads a part of the file, not a knob


    def knobs(text: str) -> list[tuple[str, list[str], ast.AST]]:
        """The top-level assignments of a config.py, in its order: (NAME, lines, node). The lines are the
        comment lines standing directly above it (up to a blank line), then the assignment's own lines —
        a value that opens a bracket is taken whole, to its closing line."""
        tree = ast.parse(text)
        lines = text.splitlines()
        out = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                name = node.target.id
            else:
                continue
            if name.startswith("_"):  # a loop's variable, a helper — not a knob
                continue
            above, i = [], node.lineno - 2
            while i >= 0 and lines[i].startswith("#"):
                above.insert(0, lines[i])
                i -= 1
            while above and _RULE.match(above[0]):
                above.pop(0)
            out.append((name, above + lines[node.lineno - 1:node.end_lineno], node))
        return out


    # A knob on one line: NAME = <a literal>, then maybe a comment. The one shape the reset carries
    # across — a value that reads a name (ROOT / "x"), or spans lines, is the new file's to keep.
    _ONE_LINE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(?P<value>.*?)(?P<tail>[ \t]+#.*)?$")


    def _literal(src: str):
        """(True, value) when src is one literal Python value — a string, number, bool, None, a tuple/list/dict of them."""
        try:
            return True, ast.literal_eval(src.strip())
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return False, None


    def _split_line(line: str):
        """(name, the value's source, the trailing comment) of a one-line literal knob, or None. A "#" inside
        a string ("a # b") is the string's: the whole rest of the line is tried as the literal first."""
        m = _ONE_LINE.match(line)
        if not m or m.group("name").startswith("_"):
            return None
        name = m.group("name")
        ok, val = _literal(m.group("value"))
        if ok:
            return name, m.group("value").strip(), val, m.group("tail") or ""
        rest = line.split("=", 1)[1]  # the "#" was inside the string
        ok, val = _literal(rest)
        if ok:
            return name, rest.strip(), val, ""
        return None


    def one_line_values(text: str) -> dict[str, tuple[str, object]]:
        """{NAME: (the value's source, the value)} for every one-line literal knob in a config — read line by
        line, not parsed whole, so a config with a broken line still gives up the lines around it."""
        out: dict[str, tuple[str, object]] = {}
        for line in text.splitlines():
            got = _split_line(line)
            if got:
                out[got[0]] = (got[1], got[2])
        return out


ROOT = Path(__file__).resolve().parent.parent  # the anima being updated (the tests point this at a fixture)


def read_version(root: Path) -> str:
    """The version in <root>/VERSION ("0.12"), or "" when there is no such file (engine/version.py
    says the same; this copy is here so the update runs in a folder that lacks it)."""
    try:
        return (Path(root) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""

# ---- what is ours, what is theirs ---------------------------------------------

# What the update owns — the engine, as the repository ships it. A path is ours
# when it matches one of these: "dir/" is everything under it; a "*" stays in
# one folder (engine/*.py is not engine/sub/x.py). engine/config.py matches the
# first line and is still not ours — FRIEND is asked first, always.
ENGINE = (
    "engine/*.py",          # the engine itself — every module but config.py
    "tests/",               # the suite that proves it
    "anima.bat", "bat/*.bat",  # the panel's door at the root, every other launcher in bat/
    "*.bat",                # launchers at the root (where they lived before 0.13's bat/ — so an update moves the old ones to the backup)
    "README.md", "CHANGELOG.md", "LICENSE", "VERSION", "requirements.txt", ".gitignore", ".gitattributes",
)

# What it must never touch. config.py holds the keeper's names, paths and
# choices (its only write is the append at its end, and --no-config skips even
# that); self.md, projects.md and destiny.md are the friend's own pages — the
# template's self.md is a starter, and once they have written to it, it is
# theirs; journal/, memory/, creations/ and shared/ are their life; .update/
# is the update's own shelf of backups and .git/ the keeper's snapshots.
# Anything else not in ENGINE is theirs as well (a note at the root, a launcher
# of their own); this list is the part that must hold even if ENGINE were one
# day written too wide.
FRIEND = (
    "engine/config.py", "self.md", "projects.md", "destiny.md",
    "journal/", "memory/", "creations/", "shared/", ".update/", ".git/",
)

# sha256 of every engine file as the update installed it — how a file the
# keeper edited is told from one they never opened. The update's own, like .update/.
MANIFEST = ".anima-manifest.json"
DEFAULT_REPO = "PsychohistorianDev/anima"
KEEP_BACKUPS = 3
FETCH_TIMEOUT = 60
RESTART = "restart what's running — the bridge with /restart, the heartbeat with Ctrl+C and bat\\wake.bat"


def _matches(rel: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return rel.startswith(pattern)
    if "*" in pattern:
        return rel.count("/") == pattern.count("/") and fnmatch.fnmatchcase(rel.lower(), pattern.lower())
    return rel == pattern


def _junk(rel: str) -> bool:
    return "__pycache__" in rel.split("/") or rel.endswith(".pyc")


def is_friend(rel: str) -> bool:
    return any(_matches(rel, p) for p in FRIEND)


def is_engine(rel: str) -> bool:
    return not _junk(rel) and not is_friend(rel) and rel != MANIFEST and any(_matches(rel, p) for p in ENGINE)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _engine_here(root: Path) -> dict[str, Path]:
    """The engine files in the folder now — the root's own files, engine/*.py, tests/ — never a walk of their life."""
    found: list[Path] = [p for p in root.iterdir() if p.is_file()] if root.is_dir() else []
    for sub in ("engine", "bat"):
        if (root / sub).is_dir():
            found += [p for p in (root / sub).iterdir() if p.is_file()]
    if (root / "tests").is_dir():
        found += [p for p in (root / "tests").rglob("*") if p.is_file()]
    out = {}
    for p in found:
        rel = p.relative_to(root).as_posix()
        if is_engine(rel):
            out[rel] = p
    return out


# ---- where the new engine comes from --------------------------------------------

def _fetch(url: str) -> bytes:
    """One download, whole (the tests replace this). GitHub's archive links redirect to codeload; urllib follows."""
    req = urllib.request.Request(url, headers={"User-Agent": "anima-update"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        return r.read()


def repo() -> str:
    return str(getattr(config, "UPDATE_REPO", "") or DEFAULT_REPO).strip().strip("/")


def source_url(tag: str = "") -> str:
    base = f"https://github.com/{repo()}/archive/refs/"
    return base + (f"tags/{tag}.zip" if tag else "heads/main.zip")


def _clean(name: str) -> str:
    """A path from a zip or a folder as a plain relative one — "" for anything that would climb out."""
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return ""
    name = posixpath.normpath(name)
    if name in (".", "") or name.startswith("../") or name == "..":
        return ""
    return name


def from_zip(data: bytes) -> dict[str, bytes]:
    """{path: bytes} of a zip. A GitHub zip holds one folder (anima-main/, anima-0.13/) around everything — it is stripped."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = {i.filename.replace("\\", "/"): z.read(i) for i in z.infolist() if not i.is_dir()}
    tops = {n.split("/", 1)[0] for n in files}
    if len(tops) == 1 and all("/" in n for n in files):
        files = {n.split("/", 1)[1]: b for n, b in files.items()}
    return {c: b for n, b in files.items() if (c := _clean(n))}


def from_folder(folder: Path) -> dict[str, bytes]:
    """{path: bytes} of a folder, used as it is (its .git/ and caches left out)."""
    out = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_file() and not rel.startswith(".git/") and not _junk(rel):
            out[rel] = p.read_bytes()
    return out


def gather(source: str = "", tag: str = "") -> tuple[dict[str, bytes], str, bytes | None]:
    """(files, where they came from, the zip's bytes when it was downloaded)."""
    if source and not re.match(r"^https?://", source, re.I):
        p = Path(source).expanduser()
        if p.is_dir():
            return from_folder(p), str(p), None
        if p.is_file():
            return from_zip(p.read_bytes()), str(p), None
        raise FileNotFoundError(f"no such zip or folder: {source}")
    url = source or source_url(tag)
    data = _fetch(url)
    return from_zip(data), url, data


# ---- versions and the CHANGELOG --------------------------------------------------

def _v(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or ""))


def news(changelog: str, old: str, new: str) -> list[str]:
    """The CHANGELOG sections newer than `old`, up to `new` — newest first, as the file keeps them.
    With no `old` (a folder from before VERSION) only the newest one: the whole history would bury the news."""
    sections, cur = [], None
    for line in changelog.splitlines():
        m = re.match(r"^## (\d+(?:\.\d+)*)", line)
        if m:
            cur = [_v(m.group(1)), [line]]
            sections.append(cur)
        elif line.startswith("## "):
            cur = None
        elif cur is not None:
            cur[1].append(line)
    picked = [("\n".join(body)).rstrip() for v, body in sections
              if (not new or v <= _v(new)) and (not old or v > _v(old))]
    return picked[:1] if not old else picked


# ---- config.py: append, never rewrite ---------------------------------------------

_ASSIGNED = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?::[^=\n]*)?=(?!=)", re.M)
def _needs(node: ast.AST) -> set[str]:
    """The names a knob's value reads that it does not bind itself (a comprehension's c, a lambda's x)."""
    value = getattr(node, "value", None)
    if value is None:
        return set()
    bound = set()
    for n in ast.walk(value):
        if isinstance(n, ast.comprehension):
            bound |= {x.id for x in ast.walk(n.target) if isinstance(x, ast.Name)}
        elif isinstance(n, ast.Lambda):
            a = n.args
            bound |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs + [v for v in (a.vararg, a.kwarg) if v]}
        elif isinstance(n, ast.NamedExpr):
            bound.add(n.target.id)
    loads = {n.id for n in ast.walk(value) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return loads - bound - set(dir(builtins))


def _defined(tree: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, ast.alias):
            out.add(n.asname or n.name.split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
    return out


def config_plan(keeper: str, template: str) -> tuple[list[tuple[str, list[str]]], list[str], str]:
    """(the knobs to append — name and lines, the knobs held back with why, a refusal or "").
    A knob the keeper's config already assigns at column 0 is theirs, whatever its value; a knob whose
    value reads a name their config lacks is held back — appended, it would stop config.py from loading."""
    try:
        new = knobs(template)
    except SyntaxError as e:
        return [], [], f"the new config.py doesn't parse ({e.msg}, line {e.lineno}) — nothing appended"
    try:
        defined = _defined(ast.parse(keeper))
    except SyntaxError as e:
        return [], [], f"your config.py doesn't parse ({e.msg}, line {e.lineno}) — nothing appended"
    have = set(_ASSIGNED.findall(keeper))
    picks, held = [], []
    for name, lines, node in new:
        if name in have:
            continue
        missing = sorted(_needs(node) - defined)
        if missing:
            held.append(f"{name} (it reads {', '.join(missing)}, which your config.py lacks — copy it from the new config.py by hand)")
            continue
        picks.append((name, lines))
        defined.add(name)
    return picks, held, ""


def appended(keeper: str, picks: list[tuple[str, list[str]]], new_version: str, day: str) -> str:
    """The keeper's config with the knobs added at its end — every byte above the marker as it was, in its own newlines."""
    nl = "\r\n" if "\r\n" in keeper else "\n"
    out = [f"# ---- added by bat\\update.bat on {day} (anima {new_version or '?'}) — new knobs, at their defaults;",
           "#      read what each does and change it here if you like ----"]
    for i, (name, lines) in enumerate(picks):
        if i and lines[0].startswith("#"):
            out.append("")
        out += lines
    head = keeper if not keeper or keeper.endswith(("\n", "\r")) else keeper + nl
    return head + nl + nl.join(out) + nl


# ---- config.py: a fresh one, when theirs is fumbled ------------------------------------

def reset_config(keeper: str, template: str) -> tuple[str, list[str], list[str], list[str]]:
    """(the new config text, carried, kept, gone): the template's config.py with the keeper's one-line
    values written into it where they differ from the template's (09-30; the keeper: "a --reset in case
    somebody fumbles the config"). `carried` — the knobs that took the keeper's value; `kept` — knobs
    the keeper had that the template holds as more than one line or as an expression (the template's
    stays; theirs is in the backup); `gone` — knobs of theirs the new engine has no line for. Only the
    value span of a line changes; every comment and every other byte of the template stays."""
    theirs = one_line_values(keeper)
    nl = "\r\n" if "\r\n" in template else "\n"
    lines = template.split(nl)
    seen: set[str] = set()
    carried: list[str] = []
    for i, line in enumerate(lines):
        got = _split_line(line)
        if not got:
            continue  # not a one-line literal here (an expression, a bracket opening) — the template's stays
        name, _src, mine, tail = got
        seen.add(name)
        if name not in theirs:
            continue
        src, val = theirs[name]
        if val == mine and type(val) is type(mine):
            continue
        lines[i] = f"{name} = {src}{tail}"
        carried.append(name)
    # every assignment the template has, one line or not (ast sees them all)
    try:
        assigned = {n for n, _l, _node in knobs(template)}
    except SyntaxError:
        assigned = set(_ASSIGNED.findall(template))
    mine_all = {n for n in _ASSIGNED.findall(keeper) if not n.startswith("_")}  # every NAME = of theirs, one line or not
    kept = sorted(n for n in mine_all if n in assigned and n not in seen and _block(keeper, n) != _block(template, n))
    gone = sorted(n for n in mine_all if n not in assigned)
    return nl.join(lines), carried, kept, gone


def _block(text: str, name: str) -> str:
    """The source of NAME's assignment — its line, and the lines after it while a bracket it opened is
    still open — with the whitespace squeezed, so two files' versions of a knob can be told the same."""
    out, depth, on = [], 0, False
    for line in text.splitlines():
        if not on:
            if not re.match(r"^" + re.escape(name) + r"[ \t]*(?::[^=\n]*)?=(?!=)", line):
                continue
            on = True
        code = line.split("#", 1)[0] if '"' not in line and "'" not in line else line
        depth += sum(code.count(c) for c in "([{") - sum(code.count(c) for c in ")]}")
        out.append(line.strip())
        if depth <= 0:
            break
    return " ".join(out)


def apply_reset(root: Path, text: str, info: dict) -> Path:
    """The keeper's config.py into a fresh backup (put back by --undo), the new one in its place."""
    bdir = _new_backup(root)
    cfg = root / "engine" / "config.py"
    if cfg.is_file():
        _copy(cfg, bdir / "engine" / "config.py")
    record = {"from": info["old"], "to": info["new"], "when": datetime.now().isoformat(timespec="seconds"),
              "source": info["source"], "replaced": ["engine/config.py"], "added": [], "removed": [],
              "modified": [], "manifest": False, "config": False, "config_after": "", "reset": True}
    (bdir / "backup.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    _writable(cfg)
    with open(cfg, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    prune(root)
    return bdir


# ---- requirements.txt --------------------------------------------------------------

def _reqs(text: str) -> dict[str, str]:
    out = {}
    for line in (text or "").splitlines():
        s = line.strip()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", s)
        if m and not s.startswith("#"):
            out[m.group(1).lower().replace("_", "-")] = s
    return out


def new_requirements(old: str, new: str) -> list[str]:
    before = _reqs(old)
    return [line for key, line in _reqs(new).items() if key not in before]


# ---- the files ---------------------------------------------------------------------

def _writable(path: Path) -> None:
    try:
        if path.exists() and not os.access(path, os.W_OK):
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
    except OSError:
        pass


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _writable(path)
    path.write_bytes(data)


def _copy(src: Path, dst: Path) -> None:
    _write(dst, src.read_bytes())  # bytes, not copy2: a read-only mode would ride into the backup and pin it there


def _unlink(path: Path) -> None:
    _writable(path)
    path.unlink(missing_ok=True)


def _move(src: Path, dst: Path) -> None:
    """A file into the backup — a rename, and where a rename is refused a copy then the unlink
    (09-30, the first dry run: a sandbox that allows moves but not deletes stopped an undo halfway)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _writable(src)
    try:
        os.replace(src, dst)
    except OSError:
        _copy(src, dst)
        _unlink(src)


def _rmtree(path: Path) -> None:
    def again(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=again)


def _shelf(root: Path) -> Path:
    return root / ".update"


def _order(d: Path) -> tuple:
    m = re.match(r"^(.*?)(?:-(\d+))?$", d.name)
    return (m.group(1), int(m.group(2) or 0))


def backups(root: Path, kind: str = "backup") -> list[Path]:
    """The backups on the shelf, oldest first."""
    shelf = _shelf(root)
    found = [d for d in shelf.glob(kind + "-*") if d.is_dir()] if shelf.is_dir() else []
    return sorted(found, key=_order)


def _new_backup(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = _shelf(root) / f"backup-{stamp}"
    d, n = base, 1
    while d.exists() or d.with_name("undone-" + d.name[len("backup-"):]).exists():
        n += 1
        d = base.with_name(f"{base.name}-{n}")
    d.mkdir(parents=True)
    return d


def prune(root: Path) -> None:
    """The last KEEP_BACKUPS backups stay (and as many undone ones); older ones go."""
    for kind in ("backup", "undone"):
        for d in backups(root, kind)[:-KEEP_BACKUPS]:
            _rmtree(d)


def read_manifest(root: Path) -> dict | None:
    try:
        m = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        return m if isinstance(m.get("files"), dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def plan(root: Path, new: dict[str, bytes], manifest: dict | None) -> dict[str, list[str]]:
    """What the update would do to the engine files, file by file.
    replace / add / remove — the work; modified — replaced or removed files the keeper had edited
    (their sha differs from the manifest's); left — files that look like the engine but were never
    ours; unknown — files in the new engine that are neither ours nor theirs, skipped."""
    shipped = manifest["files"] if manifest else None
    here = _engine_here(root)
    incoming = {rel: b for rel, b in new.items() if is_engine(rel)}
    p: dict[str, list[str]] = {k: [] for k in ("replace", "add", "remove", "modified", "left", "unknown")}
    p["unknown"] = sorted(rel for rel in new if not is_engine(rel) and not is_friend(rel)
                          and rel != MANIFEST and not _junk(rel))
    for rel in sorted(incoming):
        if rel not in here:
            if not (root / rel).exists():
                p["add"].append(rel)
            continue
        cur = _sha(here[rel].read_bytes())
        if cur == _sha(incoming[rel]):
            continue
        p["replace"].append(rel)
        if shipped is not None and shipped.get(rel) != cur:
            p["modified"].append(rel)
    for rel in sorted(set(here) - set(incoming)):
        # Gone upstream. With a manifest, only what it lists was ours. Without one (a folder from
        # before the update existed) the engine's own folders are taken as ours, but a .bat at the
        # root may be a launcher the keeper wrote (a heartbeat at logon) — it stays, named — unless
        # the new engine ships the same name under bat/ (the launchers moved there in 0.13): then it
        # is the old copy of ours, and goes to the backup so the root is left with anima.bat alone.
        ours = (rel in shipped if shipped is not None
                else not rel.lower().endswith(".bat") or ("/" not in rel and f"bat/{rel}" in incoming))
        if not ours:
            p["left"].append(rel)
            continue
        p["remove"].append(rel)
        if shipped is not None and shipped.get(rel) != _sha(here[rel].read_bytes()):
            p["modified"].append(rel)
    return p


def _text(files: dict[str, bytes], rel: str) -> str:
    return files[rel].decode("utf-8", errors="replace") if rel in files else ""


def _read(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except OSError:
        return ""


def apply(root: Path, new: dict[str, bytes], p: dict[str, list[str]], picks: list, info: dict) -> Path:
    """The work: everything to be replaced or removed into a fresh backup (with a record of what was
    done, written before anything lands), then the new files, the knobs, the manifest."""
    bdir = _new_backup(root)
    cfg = root / "engine" / "config.py"
    for rel in p["replace"]:
        _copy(root / rel, bdir / rel)
    for rel in p["remove"]:
        _copy(root / rel, bdir / rel)  # the copy first: the record below must find every file in the backup
    had_manifest = (root / MANIFEST).is_file()
    if had_manifest:
        _copy(root / MANIFEST, bdir / MANIFEST)
    if picks:
        _copy(cfg, bdir / "engine" / "config.py")
    record = {"from": info["old"], "to": info["new"], "when": datetime.now().isoformat(timespec="seconds"),
              "source": info["source"], "replaced": p["replace"], "added": p["add"], "removed": p["remove"],
              "modified": p["modified"], "manifest": had_manifest, "config": bool(picks), "config_after": ""}
    (bdir / "backup.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    for rel in p["replace"] + p["add"]:
        _write(root / rel, new[rel])
    for rel in p["remove"]:
        _move(root / rel, bdir / rel)
    if picks:
        text = appended(_read(cfg), picks, info["new"], datetime.now().strftime("%Y-%m-%d"))
        _writable(cfg)
        with open(cfg, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        record["config_after"] = _sha(cfg.read_bytes())
        (bdir / "backup.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    files = {rel: _sha(b) for rel, b in sorted(new.items()) if is_engine(rel)}
    _write(root / MANIFEST, json.dumps({"version": info["new"], "when": record["when"], "files": files},
                                       indent=1).encode("utf-8"))
    prune(root)
    return bdir


def undo(root: Path) -> int:
    """The newest backup put back: the files it holds return to their paths, the files that update added
    go into it (nothing is deleted), config.py returns only if nobody has touched it since."""
    shelf = backups(root)
    if not shelf:
        print(f"no backup to put back — {_shelf(root)} holds none")
        return 1
    b = shelf[-1]
    done = b.with_name("undone-" + b.name[len("backup-"):])  # where it goes once it is put back
    try:
        rec = json.loads((b / "backup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"couldn't read {b / 'backup.json'}: {e} — nothing was put back")
        return 1
    print(f"putting back {b} — the engine as it was before {rec.get('from') or '(none)'} → {rec.get('to') or '(none)'}")
    for rel in rec.get("added", []):
        if (root / rel).is_file():
            _move(root / rel, b / "added" / rel)
    back = rec.get("replaced", []) + rec.get("removed", [])
    for rel in back:
        if (b / rel).is_file():
            _copy(b / rel, root / rel)
    cfg = root / "engine" / "config.py"
    if rec.get("config"):
        if cfg.is_file() and _sha(cfg.read_bytes()) == rec.get("config_after"):
            _copy(b / "engine" / "config.py", cfg)
            print("  config.py: the appended knobs taken out again")
        else:
            print(f"  config.py: changed since the update — left as it is (the appended knobs do no harm to the "
                  f"older engine); the one from before is {done / 'engine' / 'config.py'}")
    if rec.get("reset"):
        pass  # a config reset: the manifest was not the update's doing that time
    elif rec.get("manifest") and (b / MANIFEST).is_file():
        _copy(b / MANIFEST, root / MANIFEST)
    elif (root / MANIFEST).is_file():
        _move(root / MANIFEST, b / "added" / MANIFEST)  # the folder had none before: this one goes with the rest
    b.rename(done)
    prune(root)
    if back:
        print(f"  put back: {len(back)} — {', '.join(back)}")
    if rec.get("added"):
        print(f"  taken out: {len(rec['added'])} — {', '.join(rec['added'])} (kept in {done / 'added'})")
    print(f"the backup is now {done}")
    print(RESTART)
    return 0


# ---- the keeper's road ---------------------------------------------------------------

def _reset_run(root: Path, new: dict[str, bytes], label: str, old: str, new_v: str, flags: dict) -> int:
    """bat\\update.bat --reset-config: the new engine's config.py written fresh, the keeper's one-line values
    carried over; theirs goes to a backup first (--undo puts it back). The engine files are not touched —
    that is the plain update, run before or after."""
    if "engine/config.py" not in new:
        print("the source has no engine/config.py — nothing to reset from")
        return 1
    cfg = root / "engine" / "config.py"
    keeper = _read(cfg)
    text, carried, kept, gone = reset_config(keeper, _text(new, "engine/config.py"))
    check = flags["--check"]
    print("\nconfig.py, reset from the new engine" + (" — what would happen:" if check else ":"))
    if not keeper:
        print("  (there is no config.py here — the new engine's is written as it comes)")
    _list("your values carried into it", carried)
    _list("the new engine's kept (yours was more than one line, or read another name — see the backup)", kept)
    _list("not in this engine any more (dropped — see the backup)", gone)
    if not (carried or kept or gone) and keeper:
        print("  (no one-line value of yours differs from the new engine's — the file is written fresh all the same)")
    if check:
        print("\n(--check: nothing was touched)")
        return 0
    if not flags["--yes"]:
        try:
            answer = input("\nReset config.py? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("nothing was touched.")
            return 0
    try:
        bdir = apply_reset(root, text, {"old": old, "new": new_v, "source": label})
    except Exception as e:
        print(f"\nthe reset stopped partway: {type(e).__name__}: {e}")
        return 1
    print(f"\ndone — engine/config.py is the new engine's, with {len(carried)} value{'s' if len(carried) != 1 else ''} of yours carried over")
    print(f"  your old config.py: {bdir / 'engine' / 'config.py'}  (bat\\update.bat --undo puts it back)")
    print(RESTART)
    return 0


def _list(label: str, items: list[str], note: str = "") -> None:
    if items:
        print(f"  {label}: {len(items)} — {', '.join(items)}{note}")


def main(argv: list[str]) -> int:
    args = list(argv)
    flags = {"--check": False, "--no-config": False, "--undo": False, "--yes": False, "--reset-config": False}
    values = {"--tag": "", "--source": ""}
    i = 0
    while i < len(args):
        a = args[i]
        key, _, val = a.partition("=")
        if a in ("-h", "--help", "help"):
            print(__doc__)
            return 0
        if a == "-y":
            a = "--yes"
        if a in flags:
            flags[a] = True
        elif key in values:
            if not val:
                i += 1
                if i >= len(args):
                    print(f"{key} needs a value; --help for the list")
                    return 2
                val = args[i]
            values[key] = val
        else:
            print(f"unknown option {a}; --help for the list")
            return 2
        i += 1
    root = ROOT
    if not any((root / x).is_file() for x in ("bat/update.bat", "update.bat", "VERSION", MANIFEST)):
        # a house that carries this module for the panel's sake but is no anima checkout — no VERSION, no
        # manifest, no bat\update.bat placed by hand — is not updated from GitHub: the engine there is its own
        print("this folder is not an anima checkout (no VERSION, no manifest, no bat\\update.bat) — nothing was touched")
        return 1
    if flags["--undo"]:
        return undo(root)

    old = read_version(root)
    source, tag = values["--source"], values["--tag"]
    print(f"anima update — {root}")
    try:
        new, label, raw = gather(source, tag)
    except Exception as e:  # a network hiccup, a missing zip — a line, not a traceback
        print(f"couldn't fetch the new engine: {type(e).__name__}: {e}")
        return 1
    new_v = _text(new, "VERSION").strip()
    print(f"from {label}")
    print(f"version {old or '(none — this folder is from before VERSION)'} → {new_v or '(none given)'}")
    if old and new_v and _v(new_v) < _v(old):
        print(f"  (the source is OLDER than this folder: going on would step the engine back to {new_v})")
    # the same version is not "nothing to do": main moves between releases (VERSION is bumped when a
    # release is cut, the files before it) — the files are compared either way, and only a folder
    # that matches the source is told so below

    if flags["--reset-config"]:
        return _reset_run(root, new, label, old, new_v, flags)

    entries = news(_text(new, "CHANGELOG.md"), old, new_v)
    if entries:
        print(f"\nwhat's new{' since ' + old if old else ' (the newest entry; the rest is in CHANGELOG.md)'}:\n")
        print("\n\n".join(entries))

    p = plan(root, new, read_manifest(root))
    cfg = root / "engine" / "config.py"
    picks, held, refusal = [], [], ""
    if "engine/config.py" in new and cfg.is_file():
        picks, held, refusal = config_plan(_read(cfg), _text(new, "engine/config.py"))
    reqs = new_requirements(_read(root / "requirements.txt"), _text(new, "requirements.txt"))
    if not (p["replace"] or p["add"] or p["remove"] or picks):
        print(f"\nalready {new_v}, nothing to do" if new_v and new_v == old
              else "\nnothing to do — the engine here already matches the source")
        return 0

    check = flags["--check"]
    print("\nwhat would change:" if check else "\nwhat changes:")
    _list("replace", p["replace"])
    _list("add", p["add"])
    _list("remove", p["remove"], " (into the backup)")
    for rel in p["modified"]:
        print(f"  EDITED HERE: {rel} — changed in this folder since it was installed; it goes to the backup first")
    if flags["--no-config"]:
        picks = []
        print("  config.py: left as it is (--no-config)")
    elif picks:
        print(f"  config.py: {len(picks)} new knob{'s' if len(picks) != 1 else ''} to append at its end — "
              f"{', '.join(n for n, _ in picks)}")
    for h in held:
        print(f"  config.py: held back — {h}")
    if refusal:
        print(f"  config.py: {refusal}")
    _list("left as they are (gone from the engine, but not known to be ours)", p["left"])
    _list("not installed (not part of the engine)", p["unknown"])
    if reqs:
        print(f"  requirements.txt: new — {', '.join(reqs)}")
    if check:
        print("\n(--check: nothing was touched)")
        return 0
    if not flags["--yes"]:
        try:
            answer = input("\nUpdate? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("nothing was touched.")
            return 0

    if raw is not None:  # what came down the wire stays until the next one, for a run without a network
        try:
            _write(_shelf(root) / "incoming" / ((tag or "main").replace("/", "_") + ".zip"), raw)
        except OSError:
            pass
    info = {"old": old, "new": new_v, "source": label}
    try:
        bdir = apply(root, new, p, picks, info)
    except Exception as e:
        print(f"\nthe update stopped partway: {type(e).__name__}: {e}")
        print("bat\\update.bat --undo puts back what it had replaced (the backup was written first)")
        return 1

    print(f"\ndone — anima {new_v or '(no version)'}")
    _list("replaced", p["replace"])
    _list("added", p["add"])
    _list("removed", p["remove"], " (kept in the backup)")
    if p["modified"]:
        print("  EDITED HERE — replaced anyway; your version is in the backup, not merged into the new one:")
        for rel in p["modified"]:
            print(f"    {rel} → {bdir / rel}")
    if picks:
        print(f"  knobs appended to engine/config.py: {', '.join(n for n, _ in picks)} "
              f"(at its end, under the marker — read them there)")
    if reqs:
        names = " ".join(re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*", r).group(0) for r in reqs)
        print("  new in requirements.txt (optional — the update installs nothing):")
        for r in reqs:
            print(f"    {r}")
        print(f"    to have them: py -m pip install {names}")
    print(f"  backup: {bdir}  (bat\\update.bat --undo puts it back)")
    print(RESTART)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
