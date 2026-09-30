"""Reading and writing config.py — the knobs as the keeper's settings (09-30; PANEL-PLAN.md).

The keeper: "a configuration button that takes you to a sub menu that takes knobs from the config
file — tabs for groups of settings". config.py is the keeper's file, written by hand and commented
by hand, so it is read as a file, not imported: every top-level knob with its value, its kind, the
comment lines standing above it and the one on its line, and the "# ---- name ----" part of the file
it sits in (read). A change rewrites only the value span of the knob's line — the comment beside it,
the lines around it, the order, the newlines, every other byte stay as they were (write) — and the
file is proved to still import in a fresh process (check). save() does the three with a backup to
.update/config-<stamp>.py first, and puts it back if the check fails.

knobs(), one_line_values() and _split_line() live here (the append and --reset-config in update.py
read the same file and import them — with copies of their own under an except, so update.py still
stands alone in a folder from before this file). This module imports nothing of the engine. No knob.
"""
from __future__ import annotations

import ast
import io
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from datetime import datetime
from pathlib import Path

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


_HEADING = re.compile(r"^#\s*-{4,}\s*(.*?)\s*-{4,}\s*$")  # a rule line, and its name
_RULEISH = re.compile(r"^#\s*-{4,}|-{4,}\s*$")  # a rule, or a line of update.bat's marker ("# ---- added by …;" / "… ----")
CHECK_TIMEOUT_S = 20
KEEP_BACKUPS = 10  # config-<stamp>.py backups kept on the shelf; older ones go


def _kind(value) -> str:
    """What a literal is, as the panel shows it: a switch, a number, a text, two small fields, a raw field."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if (isinstance(value, tuple) and len(value) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in value)):
        return "tuple2"
    if isinstance(value, (list, tuple)):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "expr"  # None, a set, bytes — a literal the panel has no field for: shown, not editable


def _lines(text: str) -> list[str]:
    """The file's lines as Python numbers them — split at "\\n" only, so a CRLF line keeps its "\\r"."""
    return text.split("\n")


def _comments(text: str) -> dict[int, str]:
    """{line number: the comment on it} — tokenize's comments, so a "#" inside a string is the string's."""
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, SyntaxError):
        pass
    return out


def _uncomment(line: str) -> str:
    return line.strip().lstrip("#").strip()


def _rows(text: str) -> list[dict]:
    """read()'s rows with the node kept (under "_node") for write()."""
    tree = ast.parse(text)
    lines = _lines(text)
    comments = _comments(text)
    heading, headings = "", []
    for line in lines:
        m = _HEADING.match(line.rstrip("\r"))
        if m:
            heading = m.group(1)
        headings.append(heading)  # headings[i]: the part of the file line i+1 sits in
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            name = node.target.id
        else:
            continue
        if name.startswith("_"):
            continue
        source = (ast.get_source_segment(text, node.value) or "").replace("\r\n", "\n")
        ok, value = _literal(source)
        kind = _kind(value) if ok else "expr"
        above, i = [], node.lineno - 2
        while i >= 0 and lines[i].startswith("#"):
            above.insert(0, lines[i].rstrip("\r"))
            i -= 1
        comment = " ".join(t for t in (_uncomment(a) for a in above if not _RULEISH.search(a)) if t)
        tail = comments.get(node.lineno, "")
        out.append({"name": name, "value": value if ok else None,
                    "source": source, "kind": kind,
                    "line": node.lineno, "end": node.end_lineno, "comment": comment,
                    "tail": _uncomment(tail) if tail else "", "heading": headings[node.lineno - 1],
                    "_node": node})
    return out


def read(text: str) -> list[dict]:
    """Every top-level knob of a config file, in its order: {"name", "value" (the literal, or None),
    "source" (the value as written), "kind" ("bool" | "int" | "float" | "str" | "tuple2" | "list" |
    "dict" | "expr" — a Path(...), ROOT / "x", anything computed: shown, not editable), "line", "end"
    (1-based, the assignment's first and last), "comment" (the comment lines standing directly above
    it, joined; the "# ---- x ----" rules left out), "tail" (the comment on its line), "heading" (the
    "# ---- x ----" part of the file it sits in, or "")}. A knob assigned twice is here twice; the
    last one is the one Python keeps. Raises SyntaxError for a file that doesn't parse."""
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in _rows(text)]


# ---- writing ------------------------------------------------------------------------

def _src(value) -> str:
    """A value as the file writes it: repr(), but a string in double quotes when it holds none (the
    file's style), inside a list or a dict too."""
    if isinstance(value, str):
        return '"' + repr("'" + value)[2:-1] + '"' if '"' not in value else repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_src(x) for x in value) + "]"
    if isinstance(value, tuple):
        return "(" + ", ".join(_src(x) for x in value) + ("," if len(value) == 1 else "") + ")"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_src(k)}: {_src(v)}" for k, v in value.items()) + "}"
    return repr(value)


def _same_kind(old, kind: str, new):
    """(True, the new value as the file should hold it) when `new` may take `old`'s place, else (False, None).
    An int may become a float and back; a bool only a bool; a str only a str; two ints only two ints (a
    list of two from the panel's JSON becomes the tuple); a list or tuple keeps its own shape."""
    is_num = isinstance(new, (int, float)) and not isinstance(new, bool)
    if kind == "bool":
        return (True, new) if isinstance(new, bool) else (False, None)
    if kind in ("int", "float"):
        return (True, new) if is_num else (False, None)
    if kind == "str":
        return (True, new) if isinstance(new, str) else (False, None)
    if kind == "tuple2":
        if (isinstance(new, (list, tuple)) and len(new) == 2
                and all(isinstance(x, int) and not isinstance(x, bool) for x in new)):
            return True, tuple(new)
        return False, None
    if kind == "list":
        return (True, type(old)(new)) if isinstance(new, (list, tuple)) else (False, None)
    if kind == "dict":
        return (True, new) if isinstance(new, dict) else (False, None)
    return False, None


def _rewrite(text: str, changes: dict[str, object]) -> tuple[str, list[str], list[str]]:
    """(the new text, the names rewritten, the names refused) — write()'s work, with what it changed."""
    try:
        rows = _rows(text)
    except SyntaxError:
        return text, [], sorted(changes)
    last = {r["name"]: r for r in rows}  # a knob assigned twice: the last one is the one that counts
    lines = _lines(text)
    changed, refused = [], []
    for name, new in changes.items():
        r = last.get(name)
        if r is None or r["kind"] == "expr" or r["line"] != r["end"]:
            refused.append(name)  # no such knob, a computed one, or one over several lines: not here
            continue
        ok, value = _same_kind(r["value"], r["kind"], new)
        if not ok:
            refused.append(name)
            continue
        if value == r["value"] and type(value) is type(r["value"]):
            continue  # unchanged — its line stays as it is
        src = _src(value)
        good, back = _literal(src)
        if not good or back != value:
            refused.append(name)  # something a literal can't hold (inf, nan, an object)
            continue
        node = r["_node"].value
        raw = lines[r["line"] - 1].encode("utf-8")  # the columns are utf-8 byte offsets
        lines[r["line"] - 1] = (raw[:node.col_offset].decode("utf-8") + src
                                + raw[node.end_col_offset:].decode("utf-8"))
        changed.append(name)
    return "\n".join(lines), changed, refused


def write(text: str, changes: dict[str, object]) -> tuple[str, list[str]]:
    """(the file with each changed knob's value span rewritten, the names refused). Only one-line literal
    knobs change, each only to a value of its own kind (see _same_kind); the comment on the line, every
    other line and the file's newlines stay byte for byte. A value equal to the one there is no change."""
    new, _changed, refused = _rewrite(text, changes)
    return new, refused


# ---- the proof ------------------------------------------------------------------------

def check(text: str) -> str:
    """"" when the text imports as a module in a fresh process, else the error's line ("line 12:
    NameError: name 'x' is not defined"). The text is put at <temp>/engine/config.py — its ROOT is the
    temp folder, so the folders it makes on import are made there, and go with it."""
    with tempfile.TemporaryDirectory(prefix="anima-config-check-") as tmp:
        engine = Path(tmp) / "engine"
        engine.mkdir()
        with open(engine / "config.py", "w", encoding="utf-8", newline="") as f:
            f.write(text)
        try:
            r = subprocess.run([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import config",
                                str(engine)], capture_output=True, text=True, timeout=CHECK_TIMEOUT_S, cwd=tmp,
                               encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return f"the check took longer than {CHECK_TIMEOUT_S} s — config.py may be waiting on something"
        except OSError as e:
            return f"the check couldn't start Python: {e}"
        if r.returncode == 0:
            return ""
        err = [line for line in (r.stderr or "").splitlines() if line.strip()]
        where = [m.group(1) for line in err if (m := re.search(r'config\.py", line (\d+)', line))]
        last = err[-1].strip() if err else f"exit code {r.returncode}"
        if not where:  # a SyntaxError names its line in its own way
            m = next((re.search(r"line (\d+)", line) for line in err if "config.py" in line), None)
            where = [m.group(1)] if m else []
        return f"line {where[-1]}: {last}" if where else last


# ---- the keeper's save ------------------------------------------------------------------

def _backup(path: Path, data: bytes) -> Path:
    shelf = path.resolve().parent.parent / ".update"
    shelf.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    b, n = shelf / f"config-{stamp}.py", 1
    while b.exists():
        n += 1
        b = shelf / f"config-{stamp}-{n}.py"
    b.write_bytes(data)
    for old in sorted(shelf.glob("config-*.py"), key=lambda p: p.stat().st_mtime)[:-KEEP_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass
    return b


def save(path: Path, changes: dict) -> tuple[list[str], list[str], str]:
    """(the knobs changed, the knobs refused, "" or the error): the file backed up to
    <root>/.update/config-<stamp>.py, rewritten by write(), proved by check() — and on a failed check
    put back from the backup, byte for byte, with the check's line as the error."""
    path = Path(path)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    try:
        ast.parse(text)
    except SyntaxError as e:
        return [], sorted(changes), f"config.py doesn't parse ({e.msg}, line {e.lineno}) — nothing was changed"
    new, changed, refused = _rewrite(text, changes)
    if not changed:
        return [], refused, ""
    data = path.read_bytes()
    backup = _backup(path, data)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    err = check(new)
    if err:
        shutil.copyfile(backup, path)
        return [], refused, f"{err} — config.py was put back as it was"
    return changed, refused, ""
