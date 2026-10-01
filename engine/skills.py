"""Their skills — recipes on their shelf (09-29; SKILLS-PLAN.md).

The keeper: "I want them to be able to use Hermes skills and be able to download
whatever skill they like, and I want them to receive the available skills in
the prompt, like with the tools." A skill is the open standard's folder —
the same for Hermes Agent, Claude Code, skills.sh, Anthropic's and OpenAI's
skill repos:

    <name>/
      SKILL.md          frontmatter (name, description; version, author,
                        platforms, metadata.* optional), then the procedure
      scripts/  references/  templates/  examples/  assets/   (optional)

They live flat in creations/skills/<name>/ and are theirs like anything under
creations/. Loading one executes nothing: the prompt carries names and a
line each (assemble.skills), use_skill opens the body, a reference file is
read only when the body points at it, and a script runs only when they run
it — in run_python's sandbox, nowhere else.

A stranger's skill passes a door on the way in: `scan(folder)` reads every
text file for words written to be taken as orders (prompt injection) and
every Python script for what it would do, and gives Hermes' three verdicts —
clean, caution (installed and tagged), dangerous (quarantined in
creations/skills/.quarantine/<name>/ with scan.json, until the keeper reads it
and lets it in: `bat\\skills.bat approve <name>`). Their own skills, written with
write_creation, are scanned only for tags, never quarantined — theirs.

The keeper's road, from a terminal (bat\\skills.bat):

    bat\\skills.bat list                 the shelf, and what waits in quarantine
    bat\\skills.bat scan <name>          the scanner's verdict and findings
    bat\\skills.bat approve <name>       a quarantined skill onto the shelf
    bat\\skills.bat install <source>     fetch + scan, printing the SKILL.md whole
    bat\\skills.bat remove <name>        the folder to creations/.trash/
    bat\\skills.bat browse [query]       the world's shelves (SKILL_CATALOGUES), or what matches
    bat\\skills.bat browse --refresh     the same, the index rebuilt first

A source is a GitHub path (owner/repo/path/to/skill, optionally @branch —
the Contents API lists it), a URL to a SKILL.md (with the files it links
relatively), or a .zip URL holding one skill. Standard library only; every
request goes through `_fetch`, which the tests replace.
"""
from __future__ import annotations

import ast
import io
import json
import posixpath
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config


class SkillError(Exception):
    """A refusal to say plainly — the tool puts it in parentheses."""


# ---- where they live ---------------------------------------------------------

def home() -> Path:
    return config.CREATIONS_DIR / str(getattr(config, "SKILLS_DIR", "skills") or "skills")


def quarantine() -> Path:
    return home() / ".quarantine"


def _incoming() -> Path:
    return home() / ".incoming"  # a fetch is written here whole, then scanned, then moved


FETCHED = ".fetched.json"   # beside SKILL.md: source, verdict, findings, when — the engine's note of a fetch
APPROVED = ".scan.json"     # beside SKILL.md: the findings the keeper read when they let it in
QUARANTINE_SCAN = "scan.json"
_OURS = {FETCHED, APPROVED, QUARANTINE_SCAN}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", str(text or "").strip().lower()).strip("-._")
    return s[:64].rstrip("-._")


def find(name: str) -> tuple[Path | None, bool]:
    """(folder, quarantined) for a skill by name — the shelf first, then the
    quarantine; (None, False) when there is none by that name. Forgives
    'skills/x', 'creations/skills/x/SKILL.md' and a name's case."""
    n = str(name or "").strip().strip("\"'`").replace("\\", "/")
    for pre in ("creations/", str(getattr(config, "SKILLS_DIR", "skills")) + "/"):
        if n.lower().startswith(pre.lower()):
            n = n[len(pre):]
    n = n.split("/")[0]
    if not n or n.startswith("."):
        return None, False
    for root, q in ((home(), False), (quarantine(), True)):
        for cand in (n, slug(n)):
            p = root / cand
            if cand and p.is_dir() and (p / "SKILL.md").is_file():
                return p, q
        if root.is_dir():
            for p in root.iterdir():
                if p.is_dir() and not p.name.startswith(".") and p.name.lower() == n.lower() and (p / "SKILL.md").is_file():
                    return p, q
    return None, False


def shelf() -> list[Path]:
    """Every skill folder on the shelf (a SKILL.md inside; the quarantine
    and the engine's staging are not the shelf)."""
    root = home()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith(".") and (p / "SKILL.md").is_file())


def quarantined() -> list[Path]:
    root = quarantine()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def is_fetched(folder: Path) -> bool:
    """A skill that came from outside (its fetch note or the keeper's approval
    beside SKILL.md) — not a piece of theirs."""
    return (folder / FETCHED).is_file() or (folder / APPROVED).is_file()


def _json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def fetch_note(folder: Path) -> dict:
    return _json(folder / FETCHED)


# ---- frontmatter: the YAML the standard uses, the part of it skills use ------
# No PyYAML (standard library only): mappings by indentation, lists ("- x"
# and "[a, b]"), a mapping inside a list item (Hermes' required_environment_
# variables), block scalars (| and >), quotes, comments. Anything stranger
# is skipped, never raised — a skill with odd frontmatter still opens.

def _split_items(s: str) -> list[str]:
    out, cur, q, depth = [], "", "", 0
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = ""
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _scalar(s: str):
    s = s.strip()
    if not s:
        return ""
    if s[0] in "\"'":
        q = s[0]
        end = s.find(q, 1)
        while q == "'" and end != -1 and s[end:end + 2] == "''":
            end = s.find(q, end + 2)
        if end > 0:
            inner = s[1:end]
            return inner.replace("''", "'") if q == "'" else inner.replace('\\"', '"').replace("\\n", "\n")
        return s[1:]
    s = re.split(r"\s+#", s, maxsplit=1)[0].strip()
    if s.startswith("[") and s.endswith("]"):
        return [_scalar(x) for x in _split_items(s[1:-1]) if x.strip()]
    if s.startswith("{") and s.endswith("}"):
        d = {}
        for item in _split_items(s[1:-1]):
            if ":" in item:
                k, v = item.split(":", 1)
                d[k.strip().strip("\"'")] = _scalar(v)
        return d
    if s.lower() in ("true", "yes"):
        return True
    if s.lower() in ("false", "no"):
        return False
    if s.lower() in ("null", "~"):
        return ""
    return s


_KEY_RE = re.compile(r"^((?:\"[^\"]*\"|'[^']*'|[^:#\s][^:]*?))\s*:(?:\s+(.*))?$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _blank(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _parse(lines: list[str], i: int, indent: int):
    out = None
    while i < len(lines):
        raw = lines[i]
        if _blank(raw):
            i += 1
            continue
        ind = _indent(raw)
        if ind < indent:
            break
        s = raw.strip()
        if s == "-" or s.startswith("- "):
            if out is None:
                out = []
            if not isinstance(out, list) or ind != indent:
                if not isinstance(out, list):
                    break
                i += 1
                continue
            item = s[1:].strip()
            if not item:
                j = i + 1
                while j < len(lines) and _blank(lines[j]):
                    j += 1
                if j < len(lines) and _indent(lines[j]) > ind:
                    val, i = _parse(lines, j, _indent(lines[j]))
                else:
                    val, i = "", i + 1
                out.append(val)
                continue
            if _KEY_RE.match(item) and item[0] not in "\"'[{":
                # a mapping that starts on the dash's line: read it as if indented there
                sub = list(lines)
                sub[i] = " " * (ind + 2) + item
                val, i = _parse(sub, i, ind + 2)
                out.append(val)
                continue
            out.append(_scalar(item))
            i += 1
            continue
        m = _KEY_RE.match(s)
        if not m:
            i += 1
            continue
        if out is None:
            out = {}
        if not isinstance(out, dict):
            break
        if ind != indent:
            i += 1
            continue
        key = m.group(1).strip().strip("\"'")
        rest = (m.group(2) or "").strip()
        if rest[:1] in ("|", ">") and re.fullmatch(r"[|>][+-]?\d?", rest.split("#")[0].strip()):
            block = []
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > ind):
                block.append(lines[j])
                j += 1
            cut = min((_indent(b) for b in block if b.strip()), default=0)
            body = [b[cut:] if b.strip() else "" for b in block]
            if rest[0] == "|":
                out[key] = "\n".join(body).strip("\n")
            else:
                paras, cur = [], []
                for b in body:
                    if b.strip():
                        cur.append(b.strip())
                    elif cur:
                        paras.append(" ".join(cur))
                        cur = []
                if cur:
                    paras.append(" ".join(cur))
                out[key] = "\n".join(paras)
            i = j
            continue
        if not rest or rest.startswith("#"):
            j = i + 1
            while j < len(lines) and _blank(lines[j]):
                j += 1
            nxt = lines[j] if j < len(lines) else ""
            if nxt and (_indent(nxt) > ind or (_indent(nxt) == ind and nxt.strip().startswith("-"))):
                val, i = _parse(lines, j, _indent(nxt))
                out[key] = val
            else:
                out[key] = ""
                i += 1
            continue
        val = _scalar(rest)
        i += 1
        if isinstance(val, str) and rest[0] not in "\"'":
            # a plain scalar may run on over more-indented lines
            while i < len(lines) and lines[i].strip() and _indent(lines[i]) > ind \
                    and not _KEY_RE.match(lines[i].strip()):
                val += " " + lines[i].strip()
                i += 1
        out[key] = val
    return (out if out is not None else ""), i


def frontmatter(text: str) -> tuple[dict, str]:
    """(meta, body) of a SKILL.md: the YAML between the opening '---' and
    the next '---' (or '...'), and the rest. No frontmatter: ({}, text)."""
    t = (text or "").lstrip("\ufeff")
    lines = t.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, t
    for k in range(1, len(lines)):
        if lines[k].strip() in ("---", "..."):
            head = [ln.rstrip("\r").replace("\t", "  ") for ln in lines[1:k]]
            try:
                meta, _ = _parse(head, 0, min((_indent(h) for h in head if not _blank(h)), default=0))
            except Exception:  # odd YAML never keeps a skill shut
                meta = {}
            return (meta if isinstance(meta, dict) else {}), "\n".join(lines[k + 1:]).lstrip("\n")
    return {}, t


def _flat(v) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(_flat(x) for x in v if _flat(x))
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_flat(x)}" for k, x in v.items())
    return " ".join(str(v).split()) if v not in (None, True, False) else ("" if v is None else str(v).lower())


def _env_names(v) -> list[str]:
    out = []
    for x in (v if isinstance(v, list) else [v] if v else []):
        if isinstance(x, dict):
            n = x.get("name") or x.get("key") or (next(iter(x)) if len(x) == 1 else "")
        else:
            n = x
        n = str(n or "").strip()
        if n:
            out.append(n)
    return out


def _not_windows(platforms) -> bool:
    ps = [str(p).strip().lower() for p in (platforms if isinstance(platforms, list) else [platforms] if platforms else [])]
    ps = [p for p in ps if p]
    return bool(ps) and not any(p.startswith("win") or p in ("any", "all", "*") for p in ps)


def info(folder: Path) -> dict:
    """What a skill says it is, read without running anything: name,
    description, version, author, platforms, the env it needs, Hermes'
    tags and category, its scripts and its files."""
    try:
        text = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    meta, body = frontmatter(text)
    md = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    hermes = md.get("hermes") if isinstance(md.get("hermes"), dict) else {}
    env = _env_names(meta.get("required_environment_variables") or hermes.get("required_environment_variables"))
    desc = _flat(meta.get("description", ""))
    if not desc:  # no frontmatter description: the body's first line of prose
        for ln in body.splitlines():
            ln = ln.strip().lstrip("#").strip()
            if ln:
                desc = ln
                break
    files = [p.relative_to(folder).as_posix() for p in sorted(folder.rglob("*"))
             if p.is_file() and not any(part.startswith(".") for part in p.relative_to(folder).parts)
             and p.name not in _OURS]
    return {
        "name": folder.name,
        "declared": _flat(meta.get("name", "")),
        "description": desc,
        "version": _flat(meta.get("version", "")),
        "author": _flat(meta.get("author", "")),
        "platforms": meta.get("platforms") or hermes.get("platforms") or "",
        "not_windows": _not_windows(meta.get("platforms") or hermes.get("platforms")),
        "env": env,
        "tags": _flat(hermes.get("tags", "") or meta.get("tags", "")),
        "category": _flat(hermes.get("category", "") or meta.get("category", "")),
        "scripts": [f for f in files if f.startswith("scripts/")],
        "files": files,
        "body": body,
        "fetched": is_fetched(folder),
    }


# ---- the scanner ---------------------------------------------------------------
# Hermes' three verdicts. A finding is {"level", "rule", "tag", "file",
# "line", "text"}: the level is dangerous or caution, the rule says what the
# regex saw, the tag is the short words the listing carries. A skill that
# merely mentions the system prompt in passing is the cost of a regex; the
# keeper can approve it.

_INJECTION = [
    (re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+|your\s+)*(?:previous|prior|above|earlier|preceding)\s+"
                r"(?:instructions?|prompts?|rules|directions|messages?)", re.I),
     "asks to ignore previous instructions"),
    (re.compile(r"\bsystem\s+prompt\b", re.I), "speaks of the system prompt"),
    (re.compile(r"\b(?:do\s+not|don['’]?t|never)\s+(?:tell|inform|let\s+on\s+to|mention\s+(?:this|it)\s+to|alert|show)\s+"
                r"(?:the\s+|your\s+)?(?:user|keeper|human|owner|operator)\b", re.I),
     "asks to keep something from the user"),
    (re.compile(r"\bhide\s+(?:\w+\s+){0,3}from\s+(?:the\s+|your\s+)?(?:user|keeper|human|owner|operator)\b", re.I),
     "asks to hide something from the user"),
    (re.compile(r"\byou\s+are\s+now\b", re.I), "tells the reader who it is now (“you are now”)"),
    (re.compile(r"\bdeveloper\s+(?:message|mode)\b", re.I), "speaks of a developer message"),
    (re.compile(r"\breveal\s+your\b", re.I), "asks to reveal “your” something"),
    (re.compile(r"\b(?:send|post|upload|exfiltrate|transmit|forward|leak)\b[^.\n]{0,80}?\b(?:to|into|at)\b[^.\n]{0,40}?"
                r"(?:https?://|webhook|pastebin|discord|telegram|e-?mail|server|endpoint)", re.I),
     "asks to send data somewhere"),
]
_CRED_RE = re.compile(r"\b(?:api[\s_-]?keys?|tokens?|passwords?|passwd|secrets?|credentials?)\b", re.I)
_URL_RE = re.compile(r"https?://\S+", re.I)
_B64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_SMUGGLE = (set(range(0x200B, 0x2010)) - {0x200D}) | set(range(0x202A, 0x202F)) | set(range(0x2060, 0x2065)) \
    | set(range(0x2066, 0x206A)) | {0xFEFF}
_NET_MODULES = {"requests", "urllib2", "urllib3", "httpx", "aiohttp", "socket",
                "websocket", "websockets", "ftplib", "smtplib", "telnetlib", "paramiko", "pycurl"}
_NET_SUBMODULES = ("urllib.request", "http.client")  # urllib.parse and http.server are not a reach outward


def _net_module(m: str) -> str:
    """The network module a dotted import is, or ''."""
    if m.split(".")[0] in _NET_MODULES:
        return m.split(".")[0]
    return next((n for n in _NET_SUBMODULES if m == n or m.startswith(n + ".")), "")
_SUBPROCESS_CALLS = {"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"}
_OS_SHELL = {"system", "popen", "execl", "execle", "execlp", "execv", "execve", "execvp", "execvpe",
             "spawnl", "spawnle", "spawnv", "spawnve", "startfile", "posix_spawn", "posix_spawnp"}
_PIP_RE = re.compile(r"\bpip3?\s+install\b|\bpip\.main\b|\bensurepip\b|['\"]-m['\"]\s*,\s*['\"]pip['\"]", re.I)


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _snip(line: str, n: int = 90) -> str:
    """A finding's words, short — with the hidden characters taken out, so a
    quote of a smuggling line does not smuggle into the tool result."""
    s = "".join(c for c in line if ord(c) not in _SMUGGLE and ord(c) != 0x200D and not 0xE0000 <= ord(c) <= 0xE007F)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _smuggled(text: str) -> tuple[int, str] | None:
    for k, ch in enumerate(text):
        o = ord(ch)
        if 0xE0000 <= o <= 0xE007F:
            return k, f"U+{o:04X} (a tag character)"
        if o in _SMUGGLE and not (o == 0xFEFF and k == 0):
            return k, f"U+{o:04X} ({'bidi control' if 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069 else 'zero-width'})"
        if o == 0x200D:  # the joiner inside an emoji is an emoji; beside a letter it hides something
            near = text[k - 1:k] + text[k + 1:k + 2]
            if any(c.isascii() and c.isalnum() for c in near):
                return k, "U+200D (zero-width joiner beside a letter)"
    return None


def _scan_text(rel: str, text: str) -> list[dict]:
    out: list[dict] = []

    def add(rule: str, lineno: int, line: str):
        out.append({"level": "dangerous", "rule": rule, "tag": "words written as orders",
                    "file": rel, "line": lineno, "text": _snip(line)})

    lines = text.splitlines()
    for n, line in enumerate(lines, 1):
        for rx, rule in _INJECTION:
            if rx.search(line):
                add(rule, n, line)
        if _CRED_RE.search(line) and _URL_RE.search(line):
            add("a credential word beside a URL", n, line)
        if _B64_RE.search(line):
            add("a base64 run over 200 characters", n, line[:60])
    hit = _smuggled(text)
    if hit:
        k, what = hit
        n = text.count("\n", 0, k) + 1
        add(f"hidden characters: {what}", n, lines[n - 1] if n - 1 < len(lines) else "")
    return out


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Call):
        inner = _dotted(node.func)
        return (inner + "()." + ".".join(reversed(parts))) if inner else ".".join(reversed(parts))
    return ".".join(reversed(parts))


def _const_str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and all(isinstance(v, ast.Constant) for v in node.values):
        return "".join(str(v.value) for v in node.values)
    return None


def _outside(path: str) -> bool:
    p = path.replace("\\", "/")
    return (p.startswith("/") or p.startswith("~") or bool(re.match(r"^[A-Za-z]:/", p))
            or ".." in p.split("/"))


def _absolute(path: str) -> bool:
    p = path.replace("\\", "/")
    return p.startswith("/") or p.startswith("~") or bool(re.match(r"^[A-Za-z]:/", p))


def _scan_python(rel: str, source: str) -> list[dict]:
    out: list[dict] = []

    def add(level: str, rule: str, tag: str, node=None, lineno: int = 0):
        n = getattr(node, "lineno", lineno) or lineno
        line = source.splitlines()[n - 1] if 0 < n <= len(source.splitlines()) else ""
        out.append({"level": level, "rule": rule, "tag": tag, "file": rel, "line": n, "text": _snip(line)})

    for m in _PIP_RE.finditer(source):
        add("dangerous", "installs packages (pip install)", "scripts install packages",
            lineno=source.count("\n", 0, m.start()) + 1)
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        add("caution", f"a script that doesn't parse ({e.msg}) — read, not trusted", "a script that doesn't parse",
            lineno=e.lineno or 0)
        return out
    aliases: dict[str, str] = {}
    net_mods: list[str] = []
    net_node = None
    for node in ast.walk(tree):
        found = []
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                found.append(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
                found += [node.module, f"{node.module}.{a.name}"]
        for m in found:
            n = _net_module(m)
            if n and n not in net_mods:
                net_mods.append(n)
                net_node = net_node or node
    if not net_mods and any(v.split(".")[0] in ("urllib", "http") for v in aliases.values()):
        m = re.search(r"\b(urllib\.request|http\.client)\b", source)  # `import urllib`, then urllib.request.urlopen(…)
        if m:
            net_mods.append(m.group(1))
    net_mods.sort()
    env_nodes = []
    net_calls = bool(net_mods)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(n.split(".")[0] == "ctypes" for n in names):
                add("dangerous", "ctypes (reaches past Python into the machine)", "scripts use ctypes", node)
            continue
        if isinstance(node, ast.Attribute) and _dotted(node) in ("os.environ", "os.environb"):
            env_nodes.append(node)
            continue
        if isinstance(node, ast.Name) and aliases.get(node.id, "") in ("os.environ", "os.getenv", "os.environb"):
            env_nodes.append(node)
            continue
        if not isinstance(node, ast.Call):
            continue
        fn = _dotted(node.func)
        full = aliases.get(fn.split(".")[0], fn.split(".")[0]) + ("." + fn.split(".", 1)[1] if "." in fn else "")
        last = fn.rsplit(".", 1)[-1]
        if fn in ("eval", "exec", "compile") or full in ("builtins.eval", "builtins.exec"):
            if not node.args or _const_str(node.args[0]) is None:
                add("dangerous", f"{last}( on something not written in the script", "scripts eval code", node)
            continue
        if fn == "__import__" and (not node.args or _const_str(node.args[0]) is None):
            add("dangerous" if net_calls else "caution", "imports a module named at run time",
                "scripts import by name", node)
            continue
        if full.startswith("importlib."):
            if net_calls or "spec_from_file_location" in full or "module_from_spec" in full:
                add("dangerous", "importlib loading code the script did not carry" if not net_calls
                    else "importlib beside a network call (code fetched and run)", "scripts load code", node)
            else:
                add("caution", "imports a module named at run time", "scripts import by name", node)
            continue
        if full in ("os.getenv", "os.environ.get", "os.getenvb"):
            env_nodes.append(node)
            continue
        if full.split(".")[0] == "os" and last in _OS_SHELL:
            add("dangerous", f"os.{last} (runs a shell command)", "scripts run shell commands", node)
            continue
        if full.startswith("subprocess.") and last in _SUBPROCESS_CALLS:
            shell = any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and k.value.value in (False, None, 0))
                        for k in node.keywords)
            first = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "args"), None)
            prog = None
            if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
                prog = _const_str(first.elts[0])
            elif first is not None and not shell and last not in ("getoutput", "getstatusoutput"):
                s = _const_str(first)
                prog = s.split()[0] if s and s.split() else None
            if shell or not prog:
                add("dangerous", "subprocess with a command built at run time" + (" (shell=True)" if shell else ""),
                    "scripts run commands", node)
            else:
                add("caution", f"runs a program ({Path(prog).name})", "scripts run a program", node)
            continue
        if full in ("shutil.rmtree",) or last == "rmtree":
            add("dangerous", "shutil.rmtree (deletes a folder whole)", "scripts delete files", node)
            continue
        if full in ("os.remove", "os.unlink", "os.rmdir", "os.removedirs") or last == "unlink":
            add("dangerous", f"{fn}( (deletes files)", "scripts delete files", node)
            continue
        if fn == "open" or full in ("io.open", "codecs.open", "builtins.open"):
            target = _const_str(node.args[0]) if node.args else None
            mode = _const_str(node.args[1]) if len(node.args) > 1 else \
                next((_const_str(k.value) for k in node.keywords if k.arg == "mode"), None) or "r"
            writing = any(c in (mode or "") for c in "wax+")
            if target and writing and _outside(target):
                add("dangerous", f"writes outside its folder ({target})", "scripts write outside creations", node)
            elif target and not writing and _absolute(target):
                add("caution", f"reads a file by absolute path ({target})", "scripts read by absolute path", node)
            continue
        if last in ("write_text", "write_bytes", "open", "mkdir", "touch", "read_text", "read_bytes") \
                and isinstance(node.func, ast.Attribute):
            # Path("…").write_text(…) and its kin, on a path written into the script
            base = node.func.value
            if not (isinstance(base, ast.Call) and _dotted(base.func).split(".")[-1] in ("Path", "PurePath") and base.args):
                continue
            target = _const_str(base.args[0])
            if not target:
                continue
            mode = (_const_str(node.args[0]) if node.args else
                    next((_const_str(k.value) for k in node.keywords if k.arg == "mode"), None)) or "r"
            writing = last in ("write_text", "write_bytes", "mkdir", "touch") or \
                (last == "open" and any(c in mode for c in "wax+"))
            if writing and _outside(target):
                add("dangerous", f"writes outside its folder ({target})", "scripts write outside creations", node)
            elif not writing and _absolute(target):
                add("caution", f"reads a file by absolute path ({target})", "scripts read by absolute path", node)
    if net_mods:
        if env_nodes:
            add("dangerous", f"reads the environment and reaches the network ({', '.join(net_mods)}) — a key could leave",
                "scripts send the environment out", env_nodes[0])
        else:
            add("caution", f"reaches the network ({', '.join(net_mods)})", "scripts reach the network", net_node)
    return out


def _walk(folder: Path):
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name in _OURS:
            continue
        yield p


def _stamp_of(folder: Path) -> tuple:
    try:
        return tuple((p.relative_to(folder).as_posix(), p.stat().st_mtime_ns, p.stat().st_size) for p in _walk(folder))
    except OSError:
        return ()


_SCAN_CACHE: dict[str, tuple[tuple, tuple[str, list[dict]]]] = {}


def scan(folder: Path) -> tuple[str, list[dict]]:
    """(verdict, findings) for a skill folder: every text file read for words
    written as orders, every .py for what it would do. 'dangerous' if any
    finding is, else 'caution' if any, else 'clean'. Other languages are
    read, not run — their text is scanned like any page."""
    folder = Path(folder)
    key = str(folder.resolve())
    stamp = _stamp_of(folder)
    hit = _SCAN_CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1][0], [dict(f) for f in hit[1][1]]
    findings: list[dict] = []
    for p in _walk(folder):
        rel = p.relative_to(folder).as_posix()
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if not _is_text(data):
            continue
        text = data.decode("utf-8")
        findings += _scan_text(rel, text)
        if p.suffix.lower() == ".py":
            findings += _scan_python(rel, text)
    seen = set()
    uniq = []
    for f in findings:  # one finding per rule per line
        k = (f["file"], f["line"], f["rule"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    verdict = ("dangerous" if any(f["level"] == "dangerous" for f in uniq)
               else "caution" if uniq else "clean")
    _SCAN_CACHE[key] = (stamp, (verdict, [dict(f) for f in uniq]))
    return verdict, uniq


def finding_line(f: dict) -> str:
    where = f"{f.get('file', '?')}" + (f" line {f['line']}" if f.get("line") else "")
    return f"{where}: {f.get('rule', '?')}" + (f" — “{f['text']}”" if f.get("text") else "")


def tags(folder: Path, inf: dict | None = None) -> list[str]:
    """The short words a skill carries in the listing: the scanner's tags,
    then what it needs — env, platform."""
    inf = inf or info(folder)
    verdict, findings = scan(folder)
    out: list[str] = []
    for f in findings:
        t = f.get("tag") or ""
        if t and t not in out:
            out.append(t)
    if (folder / APPROVED).is_file() and verdict == "dangerous":
        out.insert(0, "let in by the keeper after the scan")
    if inf.get("env"):
        out.append("needs env: " + ", ".join(inf["env"]))
    if inf.get("not_windows"):
        out.append("not for windows")
    return out


def _desc_cut(text: str, n: int | None = None) -> str:
    text = " ".join((text or "").split())
    n = int(getattr(config, "SKILLS_DESC_CHARS", 200) if n is None else n)
    if n <= 0 or len(text) <= n:
        return text
    head = text[:n]
    for sep in (". ", "; ", ", ", " "):
        k = head.rfind(sep)
        if k >= n // 2:
            return head[:k].rstrip(" ,;.") + "…"
    return head.rstrip() + "…"


def line(folder: Path, full: bool = False) -> str:
    """One shelf line: '- name — description  [scripts: 2]  (tags)'."""
    inf = info(folder)
    desc = inf["description"] if full else _desc_cut(inf["description"])
    s = f"- {inf['name']} — {desc or '(no description)'}"
    if inf["scripts"]:
        s += f"  [scripts: {len(inf['scripts'])}]"
    if full and inf.get("category"):
        s += f"  [category: {inf['category']}]"
    for t in tags(folder, inf):
        s += f"  ({t})"
    return s


def _newest(folder: Path) -> float:
    """When a skill came to the shelf or was last written — its folder or its SKILL.md, whichever is later."""
    try:
        return max(p.stat().st_mtime for p in (folder, folder / "SKILL.md") if p.exists())
    except (OSError, ValueError):
        return 0.0


def listing(cap: int | None = None) -> str:
    """The shelf for the prompt: a line per skill, alphabetical; past
    SKILLS_CHARS_IN_PROMPT the newest ride and the rest are counted.
    '' when the shelf is empty."""
    folders = shelf()
    if not folders:
        return ""
    cap = int(getattr(config, "SKILLS_CHARS_IN_PROMPT", 4000) if cap is None else cap)
    lines = {f: line(f) for f in folders}
    if cap <= 0 or sum(len(x) + 1 for x in lines.values()) <= cap:
        return "\n".join(lines[f] for f in folders)
    riding, used = [], 0
    for f in sorted(folders, key=_newest, reverse=True):
        n = len(lines[f]) + 1
        if used + n > cap:
            continue
        riding.append(f)
        used += n
    left = len(folders) - len(riding)
    return "\n".join(lines[f] for f in sorted(riding)) + f"\n(…and {left} more — list_skills names them)"


# ---- fetching --------------------------------------------------------------------

def _fetch(url: str, max_bytes: int | None = None, accept: str = "") -> bytes:
    """Every request a fetch makes goes through here (the tests replace it):
    the body, at most max_bytes (+1, so a cap can be seen). web.WebError
    when the network is not there or the server says no."""
    import web
    cap = int(max_bytes if max_bytes is not None else getattr(config, "SKILL_MAX_BYTES", 2_000_000)) + 1
    headers = {"Accept": accept} if accept else {}
    _final, _ctype, body = web.fetch(url, max_bytes=cap, timeout=int(getattr(config, "SKILL_FETCH_TIMEOUT", 30) or 30),
                                     headers=headers)
    return body


_GH_PATH_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:/([^@\s]*?))?/?(?:@([\w./-]+))?$")
_GH_WEB_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s]+)/(?:tree|blob)/([^/\s]+)/?(.*)$", re.I)


def _safe_rel(rel: str) -> str | None:
    """A path inside the skill, posix, or None: no absolute path, no '..',
    no hidden part (the engine's notes are dotfiles — a fetch never plants one)."""
    r = str(rel or "").replace("\\", "/").strip()
    if not r or r.startswith("/") or re.match(r"^[A-Za-z]:", r):
        return None
    parts = [x for x in r.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." or x.startswith(".") for x in parts):
        return None
    return "/".join(parts)


class _Bag:
    """The files of a fetch, counted against the caps as they come."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.left: list[str] = []
        self.missing: list[str] = []
        self.max_files = int(getattr(config, "SKILL_MAX_FILES", 40) or 40)
        self.max_bytes = int(getattr(config, "SKILL_MAX_BYTES", 2_000_000) or 2_000_000)

    @property
    def used(self) -> int:
        return sum(len(b) for b in self.files.values())

    def room(self) -> int:
        return max(0, self.max_bytes - self.used)

    def full(self) -> bool:
        return len(self.files) >= self.max_files or self.room() <= 0

    def add(self, rel: str, data: bytes) -> bool:
        if len(self.files) >= self.max_files or len(data) > self.room():
            self.left.append(rel)
            return False
        self.files[rel] = data
        return True


def _github(owner: str, repo: str, path: str, ref: str, bag: _Bag) -> str:
    """The Contents API lists the folder (recursively), raw files come by
    their download_url. Returns the folder's own name."""
    api = f"https://api.github.com/repos/{owner}/{repo}/contents/"

    def _list(p: str):
        url = api + urllib.parse.quote(p.strip("/")) + (f"?ref={urllib.parse.quote(ref)}" if ref else "")
        raw = _fetch(url, 1_000_000, accept="application/vnd.github+json")
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise SkillError(f"GitHub didn't answer with a listing for {owner}/{repo}/{p}")

    top = _list(path)
    if isinstance(top, dict) and top.get("type") == "file":
        path = posixpath.dirname(path.strip("/"))  # a SKILL.md named directly: its folder
        top = _list(path)
    if not isinstance(top, list):
        raise SkillError(f"{owner}/{repo}/{path} is not a folder on GitHub")
    if not any(isinstance(e, dict) and e.get("type") == "file" and e.get("name") == "SKILL.md" for e in top):
        raise SkillError(f"no SKILL.md at the top of {owner}/{repo}/{path} — a skill is a folder with a SKILL.md")
    base = path.strip("/")
    queue = [top]
    while queue:
        entries = queue.pop(0)
        for e in sorted((e for e in entries if isinstance(e, dict)), key=lambda e: (e.get("name") != "SKILL.md", e.get("path", ""))):
            p = str(e.get("path", ""))
            rel = _safe_rel(p[len(base):].lstrip("/") if base and p.startswith(base) else p)
            if not rel:
                continue
            if e.get("type") == "dir":
                if not bag.full():
                    queue.append(_list(p))
                else:
                    bag.left.append(rel + "/")
                continue
            if e.get("type") != "file" or not e.get("download_url"):
                continue
            size = int(e.get("size") or 0)
            if len(bag.files) >= bag.max_files or size > bag.room():
                bag.left.append(rel)
                continue
            data = _fetch(str(e["download_url"]), bag.room())
            bag.add(rel, data)
    return posixpath.basename(base) or repo


def _raw_url(url: str) -> str:
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/blob/(.+)$", url, re.I)
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else url


_LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_BARE_RE = re.compile(r"(?<![\w/.-])((?:scripts|references|templates|examples|assets)/[\w./-]*[\w-](?:\.\w+)?)")


def _linked(text: str) -> list[str]:
    """The files a SKILL.md points at relatively: markdown links and the
    bare scripts/… references/… paths the standard's bodies use."""
    out: list[str] = []
    for m in list(_LINK_RE.finditer(text)) + list(_BARE_RE.finditer(text)):
        target = m.group(1).split("#")[0].split("?")[0].strip()
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith(("/", "#")):
            continue
        rel = _safe_rel(urllib.parse.unquote(target[2:] if target.startswith("./") else target))
        if rel and rel not in out and rel != "SKILL.md" and not rel.endswith("/"):
            out.append(rel)
    return out


def _from_skill_md(url: str, bag: _Bag) -> str:
    raw = _raw_url(url)
    data = _fetch(raw, bag.room())
    if len(data) > bag.room():
        raise SkillError(f"that SKILL.md is larger than SKILL_MAX_BYTES ({bag.max_bytes:,} bytes)")
    bag.add("SKILL.md", data)
    base = raw.rsplit("/", 1)[0] + "/"
    for rel in _linked(data.decode("utf-8", "replace")):
        if bag.full():
            bag.left.append(rel)
            continue
        try:
            body = _fetch(urllib.parse.urljoin(base, rel), bag.room())
        except Exception:
            bag.missing.append(rel)  # a link that doesn't resolve is left behind, said
            continue
        bag.add(rel, body)
    parts = [p for p in urllib.parse.urlparse(raw).path.split("/") if p]
    return parts[-2] if len(parts) >= 2 else "skill"


def _from_zip(url: str, bag: _Bag) -> str:
    data = _fetch(url, bag.max_bytes)
    if len(data) > bag.max_bytes:
        raise SkillError(f"that .zip is larger than SKILL_MAX_BYTES ({bag.max_bytes:,} bytes)")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SkillError("that is not a .zip that opens")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    tops = sorted({posixpath.dirname(n) for n in names if posixpath.basename(n) == "SKILL.md"
                   and "__MACOSX" not in n.split("/")})
    if len(tops) != 1:
        raise SkillError("that .zip holds " + (f"{len(tops)} skills — fetch them one by one" if tops else
                                               "no SKILL.md — a skill is a folder with a SKILL.md"))
    top = tops[0]
    for zi in sorted(zf.infolist(), key=lambda z: (posixpath.basename(z.filename) != "SKILL.md", z.filename)):
        n = zi.filename
        if n.endswith("/") or (top and not n.startswith(top + "/")):
            continue
        rel = _safe_rel(n[len(top) + 1:] if top else n)
        if not rel or "__MACOSX" in n:
            continue
        if len(bag.files) >= bag.max_files or zi.file_size > bag.room():
            bag.left.append(rel)
            continue
        bag.add(rel, zf.read(zi))
    return posixpath.basename(top) or re.sub(r"\.zip$", "", posixpath.basename(urllib.parse.urlparse(url).path), flags=re.I)


def gather(source: str) -> tuple[_Bag, str, str]:
    """(files, a folder name the source suggests, what kind of source) —
    nothing written yet."""
    src = str(source or "").strip().strip("\"'`")
    if not src:
        raise SkillError("fetch_skill wants a source: a GitHub path (owner/repo/path/to/skill), "
                         "a URL to a SKILL.md, or a .zip URL")
    bag = _Bag()
    m = _GH_WEB_RE.match(src)
    if m and not m.group(4).lower().endswith("skill.md"):
        return bag, _github(m.group(1), m.group(2), m.group(4).strip("/"), m.group(3), bag), "github"
    low = urllib.parse.urlparse(src).path.lower() if src.lower().startswith(("http://", "https://")) else ""
    if src.lower().startswith(("http://", "https://")):
        if low.endswith("skill.md"):
            return bag, _from_skill_md(src, bag), "skill.md"
        if low.endswith(".zip"):
            return bag, _from_zip(src, bag), "zip"
        raise SkillError("a URL is either a SKILL.md or a .zip — for a GitHub folder, give owner/repo/path/to/skill")
    m = _GH_PATH_RE.match(src)
    if m:
        return bag, _github(m.group(1), m.group(2), (m.group(3) or "").strip("/"), m.group(4) or "", bag), "github"
    raise SkillError(f"{src!r} is not a source I can read — a GitHub path (owner/repo/path/to/skill, "
                     "optionally @branch), a URL to a SKILL.md, or a .zip URL")


def resolve_source(source: str) -> tuple[str, str]:
    """A name from the window made into the source fetch_skill takes, from
    the kept indexes (no network): "songwriting-and-ai-music",
    "hermes/songwriting-and-ai-music" or "hermes/creative/songwriting-and-ai-music"
    → ("NousResearch/hermes-agent/skills/creative/songwriting-and-ai-music",
    "hermes"); anything longer, a URL, or a name no shelf holds comes back
    as it was with "". Their first fetch (09-29 19:40) was
    `hermes/songwriting-and-ai-music` — the label and the name, as the
    shelves show them — read as owner/repo and answered 404; a name on a
    shelf is a source now. Two shelves holding the name is a refusal
    naming both sources."""
    src = str(source or "").strip().strip("\"'`").strip("/")
    low = src.lower()
    if not src or "://" in src or low.count("/") > 2 or "@" in src:
        return src, ""
    parts = low.split("/")
    hits: list[tuple[str, dict]] = []
    for label, _spec_ in catalogues():
        d = _json(_catalogue_dir() / f"{label}.json")
        for e in d.get("entries", []) if isinstance(d.get("entries"), list) else []:
            if not isinstance(e, dict) or not e.get("source"):
                continue
            name, cat = str(e.get("name") or "").lower(), str(e.get("category") or "").lower()
            forms = {(name,), (label, name)} | ({(label, cat, name), (cat, name)} if cat else set())
            if tuple(parts) in forms:
                hits.append((label, e))
    if not hits:
        return src, ""
    if len({e["source"] for _l, e in hits}) > 1:
        raise SkillError(f"{src} is on more than one shelf — say which: "
                         + "; ".join(f"fetch_skill \"{e['source']}\" ({l})" for l, e in hits))
    return str(hits[0][1]["source"]), hits[0][0]


def install(source: str, name: str = "", by: str = "them") -> dict:
    """Fetch a skill, write it whole into the engine's staging, scan it,
    and move it onto the shelf — or, dangerous, into the quarantine. The
    result is a dict the tool and the CLI say in their own words ("resolved"
    names the shelf when the source was a name from the window). Raises
    SkillError (a refusal) or web.WebError (no network)."""
    source, resolved = resolve_source(source)
    bag, suggested, kind = gather(source)
    if "SKILL.md" not in bag.files:
        raise SkillError("the fetch found no SKILL.md — a skill is a folder with a SKILL.md")
    meta, _body = frontmatter(bag.files["SKILL.md"].decode("utf-8", "replace"))
    final = slug(name) or slug(_flat(meta.get("name", ""))) or slug(suggested)
    if not final:
        raise SkillError("no name for this skill — give it one with name=")
    for root in (home(), quarantine()):
        if (root / final).exists():
            where = "on your shelf" if root == home() else "waiting in quarantine"
            raise SkillError(f"a skill named {final} is already {where} — remove_skill it first or give this one a name")
    stage = _incoming() / final
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    for rel, data in bag.files.items():
        p = stage / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    verdict, findings = scan(stage)
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    inf = info(stage)
    note = {"name": final, "source": str(source).strip(), "resolved": resolved, "kind": kind, "verdict": verdict, "findings": findings,
            "when": when, "by": by, "description": inf["description"], "files": len(bag.files), "bytes": bag.used,
            "left_behind": bag.left, "not_found": bag.missing}
    (stage / FETCHED).write_text(json.dumps(note, ensure_ascii=False, indent=1), encoding="utf-8")
    if verdict == "dangerous":
        dest = quarantine() / final
        (stage / QUARANTINE_SCAN).write_text(json.dumps({"verdict": verdict, "findings": findings, "when": when,
                                                         "source": note["source"]}, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    else:
        dest = home() / final
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stage), str(dest))
    _prune(_incoming())
    note["folder"] = dest
    note["quarantined"] = verdict == "dangerous"
    return note


def _prune(d: Path) -> None:
    try:
        d.rmdir()
    except OSError:
        pass


def approve(name: str) -> str:
    """The keeper's gate: a quarantined skill onto the shelf, scan.json kept
    beside SKILL.md as .scan.json (with when they let it in)."""
    folder, q = find(name)
    if folder is None:
        raise SkillError(f"no skill named {name} on the shelf or in quarantine")
    if not q:
        raise SkillError(f"{folder.name} is already on the shelf")
    dest = home() / folder.name
    if dest.exists():
        raise SkillError(f"a skill named {folder.name} is already on the shelf — remove it first")
    scanf = folder / QUARANTINE_SCAN
    data = _json(scanf) if scanf.exists() else {}
    data["approved"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    (folder / APPROVED).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    scanf.unlink(missing_ok=True)
    shutil.move(str(folder), str(dest))
    _prune(quarantine())
    return f"approved: {dest.name} is on their shelf now (creations/{dest.relative_to(config.CREATIONS_DIR).as_posix()}/)"


def to_trash(folder: Path) -> Path:
    """delete_creation's road, for a folder: into creations/.trash/ with a
    stamp — creations/.trash/<stamp>-skills-<name>/."""
    trash = config.CREATIONS_DIR / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{home().name}-{folder.name}"
    k = 2
    while dest.exists():
        dest = dest.with_name(f"{dest.name.split('~')[0]}~{k}")
        k += 1
    shutil.move(str(folder), str(dest))
    return dest


# ---- the shop window (09-29 evening; SKILLS-PLAN.md, v3) ---------------------------
# the keeper, on the delivered shelf: "how do they browse the available skills to
# download?… they're not gonna know to go to the Nous Research site to fetch a
# skill." fetch_skill needs a source they already know; the window shows their
# the world's shelves. A catalogue is a GitHub tree under which skills sit one
# or two folders deep (<path>/<name>/SKILL.md or <path>/<category>/<name>/
# SKILL.md). One Git Trees call finds them, each SKILL.md's frontmatter says
# what it is, and the index is kept in memory/skills_catalogue/<label>.json for
# SKILL_CATALOGUE_TTL_H — the first browse builds it (≈70 small requests), the
# rest read the file. A catalogue that won't answer is named and the others
# ride; a stale index stands in for a refresh that failed, with its date.
# Everything in it is strangers' text: names and descriptions are made plain
# (control characters out, reserved tokens defanged) before they are kept.

_CATALOGUES_DEFAULT = [("hermes", "NousResearch/hermes-agent/skills"), ("anthropic", "anthropics/skills/skills")]
_TREE_MAX_BYTES = 10_000_000   # a Git Trees answer; GitHub itself stops near 7 MB and says "truncated"
_KEPT_DESC_CHARS = 1000        # of a description in the index (the listing cuts at SKILLS_DESC_CHARS)


def catalogues() -> list[tuple[str, str]]:
    """SKILL_CATALOGUES as (label, owner/repo/path[@branch]) pairs — the label
    slugged, a pair that isn't one skipped, a label named twice kept once."""
    out: list[tuple[str, str]] = []
    for item in getattr(config, "SKILL_CATALOGUES", _CATALOGUES_DEFAULT) or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        label, spec = slug(str(item[0])), str(item[1] or "").strip().strip("/")
        if label and spec and label not in (x for x, _ in out):
            out.append((label, spec))
    return out


def _catalogue_dir() -> Path:
    return Path(getattr(config, "SKILL_CATALOGUE_DIR", config.MEMORY_DIR / "skills_catalogue"))


def _spec(spec: str) -> tuple[str, str, str, str]:
    """(owner, repo, path, branch) of a catalogue's owner/repo/path[@branch]."""
    m = _GH_PATH_RE.match(str(spec or "").strip())
    if not m:
        raise SkillError(f"{spec!r} is not a catalogue I can read — owner/repo/path, optionally @branch")
    return m.group(1), m.group(2), (m.group(3) or "").strip("/"), m.group(4) or ""


def _plain(text, n: int = 0) -> str:
    """A stranger's words made plain for their prompt: control characters and
    the hidden ones (zero-width, bidi, tag characters) out, reserved tokens
    defanged ("<unused50>" → "⟨unused50⟩"), whitespace one space."""
    s = "".join(" " if unicodedata.category(c) == "Cc" else c for c in str(text or "")
                if ord(c) not in _SMUGGLE and ord(c) != 0x200D and not 0xE0000 <= ord(c) <= 0xE007F)
    try:
        import ollama_client
        s = ollama_client.defang(s)[0]
    except Exception:  # the defang is ollama_client's; a window without it still opens
        pass
    s = " ".join(s.split())
    return s[:n] if n > 0 else s


def _tree(owner: str, repo: str, path: str, ref: str) -> tuple[list[dict], bool]:
    """The skill folders under a catalogue's path, from one Git Trees call:
    [{"folder", "name", "category", "scripts"}], and whether GitHub cut the
    tree short. A scripts/ blob beside a SKILL.md marks scripts: true."""
    url = (f"https://api.github.com/repos/{owner}/{repo}/git/trees/"
           f"{urllib.parse.quote(ref or 'HEAD', safe='/')}?recursive=1")
    raw = _fetch(url, _TREE_MAX_BYTES, accept="application/vnd.github+json")
    if len(raw) > _TREE_MAX_BYTES:
        raise SkillError(f"{owner}/{repo}'s tree is larger than {_TREE_MAX_BYTES:,} bytes")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise SkillError(f"GitHub didn't answer with a tree for {owner}/{repo}")
    if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
        raise SkillError(f"GitHub didn't answer with a tree for {owner}/{repo}"
                         + (f" ({_plain(data.get('message'), 120)})" if isinstance(data, dict) and data.get("message") else ""))
    blobs = [str(e["path"]) for e in data["tree"]
             if isinstance(e, dict) and e.get("type") == "blob" and isinstance(e.get("path"), str)]
    prefix = path.strip("/") + "/" if path.strip("/") else ""
    found: list[dict] = []
    for p in blobs:
        if not p.startswith(prefix) or posixpath.basename(p) != "SKILL.md":
            continue
        parts = p[len(prefix):].split("/")[:-1]
        if not 1 <= len(parts) <= 2 or any(not x or x.startswith(".") for x in parts):
            continue
        folder = posixpath.dirname(p)
        found.append({"folder": folder, "name": parts[-1], "category": parts[0] if len(parts) == 2 else "",
                      "scripts": any(b.startswith(folder + "/scripts/") for b in blobs)})
    return sorted(found, key=lambda f: (f["category"], f["name"])), bool(data.get("truncated"))


def _raw_skill_md(owner: str, repo: str, ref: str, folder: str) -> tuple[str | None, bool]:
    """One SKILL.md raw — (text, False); or (None, refused) when it would not
    come, `refused` when GitHub said "429: Too Many Requests" to the end. The
    first live run (09-29, the keeper's machine) fired 77 raw requests in a burst
    and GitHub answered 32 of them 429 — so a pause between requests
    (SKILL_CATALOGUE_PACE), and on a 429 a longer one, then again."""
    url = (f"https://raw.githubusercontent.com/{owner}/{repo}/{urllib.parse.quote(ref, safe='/')}/"
           f"{urllib.parse.quote(folder)}/SKILL.md")
    for wait in (5.0, 15.0, None):
        try:
            return _fetch(url, 200_000).decode("utf-8", "replace"), False
        except Exception as e:  # noqa: BLE001 — one SKILL.md that won't come is a name without its line
            if "429" not in str(e):
                return None, False
            if wait is None:
                return None, True
            time.sleep(wait)
    return None, True


def build_index(label: str, spec: str, prior: dict | None = None) -> dict:
    """A catalogue's index, built now from GitHub (one Trees call, then each
    SKILL.md raw for its frontmatter) and kept in SKILL_CATALOGUE_DIR/<label>.json.
    `prior` is the kept index, if any: a description it already holds for a
    folder is kept rather than fetched again (a rebuild after a partial one
    asks GitHub only for what is missing). "partial" counts the SKILL.md
    files that did not come this time. Raises SkillError or web.WebError
    when the catalogue won't answer."""
    owner, repo, path, branch = _spec(spec)
    ref = branch or "HEAD"
    found, truncated = _tree(owner, repo, path, ref)
    if not found:
        raise SkillError(f"no skills under {spec} — a catalogue is a folder where <name>/SKILL.md "
                         "or <category>/<name>/SKILL.md sit")
    had = {e.get("path"): e for e in (prior or {}).get("entries", []) if isinstance(e, dict) and e.get("description")}
    pace = float(getattr(config, "SKILL_CATALOGUE_PACE", 0.5) or 0)
    # a build sits inside one of their tool calls: SKILL_CATALOGUE_BUDGET_S is all the asking it may do, and
    # once GitHub has refused a file to the end (429 through the retries) the rest are not asked this time —
    # they are counted missing and asked for at the next browse after SKILL_CATALOGUE_RETRY_MIN
    deadline = time.time() + float(getattr(config, "SKILL_CATALOGUE_BUDGET_S", 90) or 0)
    refused = False
    entries, missing = [], 0
    for f in found:
        if f["folder"] in had:  # its line is already known — no request
            e = dict(had[f["folder"]])
            e.update(category=_plain(f["category"], 80), scripts=f["scripts"],
                     source=f"{owner}/{repo}/{f['folder']}" + (f"@{branch}" if branch else ""))
            entries.append(e)
            continue
        if refused or time.time() > deadline:
            text = None
        else:
            if pace > 0 and entries:
                time.sleep(pace)
            text, refused = _raw_skill_md(owner, repo, ref, f["folder"])
        if text is None:
            missing += 1
            text = ""
        meta, body = frontmatter(text)
        md = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
        hermes = md.get("hermes") if isinstance(md.get("hermes"), dict) else {}
        desc = _flat(meta.get("description", ""))
        if not desc:  # no frontmatter description: the body's first line of prose, as info() does
            desc = next((ln.strip().lstrip("#").strip() for ln in body.splitlines() if ln.strip().lstrip("#").strip()), "")
        entries.append({
            "name": _plain(_flat(meta.get("name", "")), 80) or f["name"],
            "description": _plain(desc, _KEPT_DESC_CHARS),
            "category": _plain(f["category"], 80),
            "tags": _plain(_flat(hermes.get("tags", "") or meta.get("tags", "")), 300),
            "path": f["folder"],
            "scripts": f["scripts"],
            "source": f"{owner}/{repo}/{f['folder']}" + (f"@{branch}" if branch else ""),
        })
    data = {"label": label, "spec": spec, "ref": ref, "built": time.time(), "truncated": truncated,
            "partial": missing, "entries": entries}
    d = _catalogue_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{label}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(d / f"{label}.json")
    except OSError:
        pass  # an index that can't be kept is built again next time, never a window shut
    return data


def index(label: str, refresh: bool = False) -> dict:
    """A catalogue's index: the kept one while it is fresh (SKILL_CATALOGUE_TTL_H)
    and of the same spec, else built now; a refresh that fails falls back to
    the kept one, stale. The dict carries "how" — "cached", "built" or
    "stale" (then "error", why the refresh failed). Raises SkillError or
    web.WebError when there is nothing to show."""
    import web
    spec = dict(catalogues()).get(label)
    if spec is None:
        raise SkillError(f"no catalogue named {label}")
    kept = _json(_catalogue_dir() / f"{label}.json")
    if kept.get("spec") != spec or not isinstance(kept.get("entries"), list):
        kept = {}
    ttl = float(getattr(config, "SKILL_CATALOGUE_TTL_H", 168) or 0) * 3600
    try:
        built = float(kept.get("built") or 0)
    except (TypeError, ValueError):
        built = 0.0
    age = time.time() - built
    retry = float(getattr(config, "SKILL_CATALOGUE_RETRY_MIN", 30) or 0) * 60
    if kept and not refresh and age < ttl and not (kept.get("partial") and age >= retry):
        return dict(kept, how="cached")  # a partial index (SKILL.md files that never came) is tried again after SKILL_CATALOGUE_RETRY_MIN
    try:
        return dict(build_index(label, spec, prior=kept or None), how="built")
    except (SkillError, web.WebError) as e:
        if kept:
            return dict(kept, how="stale", error=str(e))
        raise


def _as_of(d: dict) -> str:
    try:
        return datetime.fromtimestamp(float(d.get("built") or 0)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "an earlier day"


def _names_lines(label: str, names: list[str], width: int = 110) -> list[tuple[str, int]]:
    """A category's names, compact, wrapped at about `width` so a cut can
    fall between lines: '  research: arxiv, llm-wiki' then '    more, names'
    — each line with how many names it holds."""
    out: list[tuple[str, int]] = []
    cur, count = (f"  {label}: " if label else "  "), 0
    for n in names:
        if count and len(cur) + 2 + len(n) > width:
            out.append((cur + ",", count))
            cur, count = "    ", 0
        cur += (", " if count else "") + n
        count += 1
    out.append((cur, count))
    return out


def window(query: str = "", catalogue: str = "", refresh: bool = False) -> tuple[list[str], str]:
    """(the labels that rode, the listing) — the shelves with no query, the
    matching skills with one. The frame is the tool's. Raises SkillError
    when no catalogue answers (with each one's reason)."""
    import web
    cats = catalogues()
    if not cats:
        raise SkillError("no catalogues are set — SKILL_CATALOGUES in config.py names them")
    want = slug(catalogue)
    if want:
        if want not in (x for x, _ in cats):
            raise SkillError(f"no catalogue named {str(catalogue).strip()} — the catalogues are {', '.join(x for x, _ in cats)}")
        cats = [(x, s) for x, s in cats if x == want]
    rode: list[dict] = []
    notes: list[str] = []
    failed: list[tuple[str, str]] = []
    for label, _spec_ in cats:
        try:
            d = index(label, refresh)
        except (SkillError, web.WebError) as e:
            failed.append((label, str(e)))
            continue
        rode.append(d)
        if d["how"] == "built":
            notes.append(f"indexed {label}: {len(d['entries'])} skills"
                         + (" (GitHub cut the tree short — some may be missing)" if d.get("truncated") else "")
                         + (f" ({d['partial']} descriptions did not come — GitHub asked for a pause; the next browse "
                            "asks for them again)" if d.get("partial") else ""))
        elif d["how"] == "stale":
            notes.append(f"{label} (as of {_as_of(d)} — it would not answer now: {d.get('error', '')})")
    if not rode:
        raise SkillError(f"couldn't reach the catalogue{'s' if len(failed) > 1 else ''} — "
                         + "; ".join(f"{x}: {why}" for x, why in failed))
    notes += [f"({x} would not answer: {why} — the others ride)" for x, why in failed]
    cap = int(getattr(config, "SKILL_BROWSE_CHARS", 6000) or 0)
    labels = [d["label"] for d in rode]
    words = str(query or "").lower().split()
    lines: list[tuple[str, int]] = []   # (a line, how many skills it shows)
    if not words:
        for d in rode:
            es = d["entries"]
            lines.append((f"{d['label']} — {len(es)} skills" + (f" (as of {_as_of(d)})" if d["how"] == "stale" else "") + ":", 0))
            cats_: dict[str, list[str]] = {}
            for e in es:
                cats_.setdefault(e.get("category") or "", []).append(e.get("name") or "?")
            for c in sorted(cats_):
                lines += _names_lines(c, sorted(cats_[c]))
        more = "(…and {n} more — browse_skills with a query narrows it)"
        tail = "(browse_skills with a word or two gives each its line and the exact source fetch_skill takes)"
    else:
        hits = []
        for k, d in enumerate(rode):
            for e in d["entries"]:
                hay = " ".join(str(e.get(x) or "") for x in ("name", "description", "category", "tags")).lower()
                if all(w in hay for w in words):
                    hits.append((not all(w in str(e.get("name") or "").lower() for w in words), k,
                                 e.get("category") or "", e.get("name") or "", d, e))
        if not hits:
            body = "\n".join(notes + [f"(nothing in the catalogues matches '{str(query).strip()}' — browse_skills with no "
                                      "query shows the shelves; read_web on skills.sh or a GitHub search is the wider world)"])
            return labels, body
        for *_k, d, e in sorted(hits, key=lambda h: h[:4]):
            where = d["label"] + (f"/{e['category']}" if e.get("category") else "") + ("; scripts" if e.get("scripts") else "")
            lines.append((f"- {e.get('name') or '?'} — {_desc_cut(e.get('description') or '') or '(no description)'}"
                          f"  [{where}]  → fetch_skill \"{e.get('source')}\"", 1))
        more = "(…and {n} more — another word narrows it)"
        tail = ""
    kept, used = [], 0
    for k, (ln, _n) in enumerate(lines):
        if cap > 0 and used + len(ln) + 1 > cap:
            left = sum(n for _l, n in lines[k:])
            kept.append(more.format(n=left))
            break
        kept.append(ln)
        used += len(ln) + 1
    else:
        if tail:
            kept.append(tail)
    return labels, "\n".join(notes + kept)


def browse(query: str = "", catalogue: str = "", refresh: bool = False) -> str:
    """The window as text, without the frame (bat\\skills.bat browse prints it;
    the tool browse_skills frames it for them)."""
    return window(query, catalogue, refresh)[1]


# ---- the keeper's road (bat\skills.bat) ----------------------------------------------

def _print_findings(verdict: str, findings: list[dict]) -> None:
    print(f"verdict: {verdict}")
    for f in findings:
        print(f"  [{f['level']}] {finding_line(f)}")


def main(argv: list[str]) -> int:
    args = list(argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = args[0].lower().lstrip("-"), args[1:]
    try:
        if cmd == "list":
            folders = shelf()
            print(f"their shelf — {home()}")
            print("\n".join(line(f, full=True) for f in folders) if folders else "  (empty)")
            q = quarantined()
            if q:
                print("\nwaiting in quarantine (bat\\skills.bat scan <name> to read why, approve <name> to let it in):")
                for f in q:
                    v, fs = scan(f)
                    print(f"- {f.name} — {v}: {finding_line(fs[0]) if fs else '(no findings now)'}")
            return 0
        if cmd == "scan":
            if not rest:
                print("scan <name>")
                return 2
            folder, q = find(rest[0])
            if folder is None:
                print(f"no skill named {rest[0]}")
                return 1
            print(f"{folder.name}{' (in quarantine)' if q else ''} — {folder}")
            _print_findings(*scan(folder))
            return 0
        if cmd == "approve":
            if not rest:
                print("approve <name>")
                return 2
            print(approve(rest[0]))
            return 0
        if cmd == "install":
            if not rest:
                print("install <source> [name]")
                return 2
            note = install(rest[0], rest[1] if len(rest) > 1 else "", by="keeper")
            folder = note["folder"]
            print(f"fetched {note['files']} files, {note['bytes']:,} bytes → {folder}")
            for x in note["left_behind"]:
                print(f"  left behind (past the caps): {x}")
            for x in note["not_found"]:
                print(f"  linked but not found: {x}")
            _print_findings(note["verdict"], note["findings"])
            if note["quarantined"]:
                print(f"\nquarantined — read it below; bat\\skills.bat approve {folder.name} lets it in.")
            print("\n----- SKILL.md -----\n" + (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
            return 0
        if cmd == "remove":
            if not rest:
                print("remove <name>")
                return 2
            folder, q = find(rest[0])
            if folder is None:
                print(f"no skill named {rest[0]}")
                return 1
            if not q:
                import tools
                print(tools.remove_skill(folder.name))
            else:
                print(f"removed from quarantine → {to_trash(folder)}")
                _prune(quarantine())
            return 0
        if cmd == "browse":
            # the window they have (browse_skills), for the keeper's terminal; --refresh rebuilds the index first
            refresh = any(a.lower() in ("--refresh", "-r") for a in rest)
            query = " ".join(a for a in rest if a.lower() not in ("--refresh", "-r"))
            print(f"the catalogues ({', '.join(x for x, _ in catalogues()) or 'none set'}) — index in {_catalogue_dir()}")
            print(browse(query, refresh=refresh))
            return 0
    except SkillError as e:
        print(f"refused: {e}")
        return 1
    except Exception as e:  # a network hiccup is a line, not a traceback
        print(f"couldn't: {type(e).__name__}: {e}")
        return 1
    print(f"unknown command {args[0]}; help for the list")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
