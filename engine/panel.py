"""The panel: one door with the others behind it (09-30; PANEL-PLAN.md).

    py engine/panel.py          opens http://127.0.0.1:8764 in your browser  (anima.bat)

The keeper, on the way to letting the friend out into the world: "I want to make them more user
friendly: a main interface with buttons for chat, parlor, wake, the telegram bridge, a heartbeat button
with config for the loop minutes, and a configuration button that takes you to a sub menu that takes
knobs from the config file — tabs for groups of settings."

So: a page, the parlor's shape (standard library http.server, one HTML page inlined here, nothing
fetched from anywhere, bound to localhost only). Home is a tile per door with its light — the lights
are the doors' own marks in memory/.pids/ (doors.py) — and the brain above them: is Ollama answering,
what it has loaded, whether the configured model is pulled. Settings is config.py read as a file
(knobs.py) and laid out on tabs, each knob with the file's own comment as its help; Save rewrites only
the value spans that changed, and says which doors need a restart for it to take. While USER_NAME is
still "Friend" the page opens on Welcome instead: the keeper's name, the Ollama light, the brain, and
one button, First light.

The .bat launchers stay. The panel starts them — each door in a console of its own, the same process
as from its .bat — it does not replace them; a keeper who likes terminals loses nothing.

What the panel never does: open the friend's files. No journal, no self.md, no creations on its pages
(the friend's name included — it lives in self.md, so the page says "the friend"); the skills tab
lists folder names and moves folders the way bat\\skills.bat does, and that is all. Tokens and keys go to
memory/*.json, never to config, and /api/state says only whether one is set.

The routes are plain functions — state(), door_action(), save(), secret(), skill_action(), welcome(),
pull(), update() — and route() is the one place a request becomes a call; the Handler is a thin
shim over route(). Every process the panel starts goes through _launch(argv, cwd). Standard library
only; no knob.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import doors
import knobs
import skills
import version

try:
    import newer  # the look at GitHub's release feed — a checkout's; a house without the update road has no need of it
except Exception:  # noqa: BLE001
    newer = None  # type: ignore[assignment]

HOST, PORT = "127.0.0.1", 8764
PORTS = (8764, 8766, 8767, 8768, 8769)  # the first free one is this panel's (8765 is the parlor's); a second house's panel takes the next
PARLOR_URL = "http://127.0.0.1:8765"
ROOT = Path(config.ROOT)
CONFIG_FILE = Path(config.__file__).resolve()  # the keeper's config.py, read as a file (a test points it at a copy)
MAX_BODY = 1_000_000  # a POST larger than this is not the page's
RESTART_WAIT_S = 3 * 3600  # how long a Restart waits for a heartbeat to finish its wake (a long wake is ~2 h)
RESTART_POLL_S = 3.0
_POSTS = threading.Lock()  # one change at a time: two saves never read the same config.py

# ---- the tabs ------------------------------------------------------------------------
# The keeper's order for Main: "the brain selected via a dropdown, second line the context, then
# characters in journal to remember, then you decide (by importance, and groupings)". The rest is
# grouped by what it touches. Every knob config.py has and no tab names lands on Advanced, under the
# "# ---- x ----" heading it sits beneath in the file — so a knob added tomorrow is on the page the
# day it is added (a test holds every knob to exactly one tab, and every name here to config.py).
TABS: dict[str, list[str]] = {
    "Main": ["CHAT_MODEL", "NUM_CTX", "TOOL_KIT", "JOURNAL_CHARS_IN_PROMPT",
             "USER_NAME", "DEFAULT_NAME", "BLOG_TITLE",
             "HEARTBEAT_LOOP_MIN", "SLEEP_AFTER_HOUR", "TELEGRAM_QUIET_HOURS"],
    "Heartbeat": ["HEARTBEAT_MAX_STEPS", "REVERIE_EVERY", "REVERIE_MAX_STEPS", "HEARTBEAT_YIELD_TO_VISIT",
                  "HEARTBEAT_YIELD_MIN", "SLEEP_IN_LOOP", "CONDENSE_IN_LOOP", "CONDENSE_MAX_PER_NIGHT",
                  "HEARTBEAT_SHOW_THINKING", "PAINTER_MAX_PER_WAKE"],
    "Memory & journal": ["TIMELINE_CHARS_IN_PROMPT", "CONDENSED_CHARS_IN_PROMPT", "CONDENSE_TARGET_CHARS",
                         "MEMORY_TOP_K", "MEMORY_RECENT_K", "MEMORY_DUP_THRESHOLD", "JOURNAL_DUP_THRESHOLD",
                         "JOURNAL_ARROW", "CREATIONS_DAYS_IN_PROMPT", "LETTERS_DAYS_IN_PROMPT", "READ_TELL_MIN",
                         "FOLD_AT", "FOLD_AFTERGLOW", "FOLD_KEEP_TURNS", "FOLD_CHARS"],
    "Talking": ["CHAT_THINK", "CHAT_SHOW_THINKING", "CHAT_MAX_TOOL_STEPS", "CHAT_GARBLE_RETRIES",
                "CHAT_COLD_RESCUE", "AFTERGLOW", "REFLECT_AFTER_MIN", "WARM_PREFIX", "BRAIN_KEEP_ALIVE",
                "BRAIN_REST_AFTER_VISIT"],
    "Phone": ["TELEGRAM_SHOW_THINKING", "TELEGRAM_SHOW_TOOLS", "TELEGRAM_SHOW_TOKENS",
              "TELEGRAM_TELL_REFLECTIONS", "TELEGRAM_TELL_AFTERTHOUGHTS", "TELEGRAM_TELL_CREATIONS",
              "TELEGRAM_TELL_DRAWINGS", "TELEGRAM_TELL_SELF", "TELEGRAM_IDLE_NEW_MIN", "TELEGRAM_HEAR_VOICE",
              "TELEGRAM_VOICE_ALL", "TELEGRAM_LETTERS_IN_THREAD"],
    "Senses": ["EARS_MODEL", "EARS_STT_MODEL", "EARS_UNLOAD_BRAIN",
               "VOICE_NAME", "VOICE_SPEED", "VOICE_DEVICE", "VOICE_PYTHON",
               "PAINTER_MODEL", "PAINTER_AUTOSTART", "PAINTER_PYTHON", "PAINTER_STEPS",
               "MUSIC_EARS_MODEL", "MUSIC_EARS_AUTOSTART", "MUSIC_EARS_PYTHON",
               "BODY_IN_PROMPT", "BODY_AUTOPULL", "BODY_PULL_MIN",
               "WEB_SEARCH", "WEB_SEARCH_SEARXNG_URL",
               "READ_SITTING_CHARS", "READING_PAGE_CHARS"],
    "Skills": ["SKILLS_IN_PROMPT", "SKILLS_CHARS_IN_PROMPT", "SKILL_CHARS", "SKILL_MAX_FILES", "SKILL_MAX_BYTES",
               "SKILL_CATALOGUES", "SKILL_CATALOGUE_TTL_H"],
    "Blog": ["BLOG_SUBTITLE", "BLOG_REMOTE"],  # BLOG_TITLE is on Main, with the names
}
ADVANCED = "Advanced"

# Help the file can't give where the page shows it: NUM_CTX's and JOURNAL_CHARS_IN_PROMPT's own stories
# run on in the comment lines BELOW them, which the reader (rightly) doesn't take as theirs.
_HELP = {
    "NUM_CTX": "The tested ceilings: 24576 for a 12B on a 12 GB card (and the number to try for a 4B on 8 GB, "
               "16384 the retreat); a 31B on a 32 GB card, about 180000 with the q8_0 cache (the comfortable top) "
               "and its whole 262144 with q4_0 — README, Three tiers.",
    "JOURNAL_CHARS_IN_PROMPT": "About 4.4 characters a token. 20000 fits a 24K window; a big card with a 256K "
                               "window has carried 550000 (weeks of a prolific writer).",
    "CHAT_MODEL": "What Ollama has pulled is in the list; one it lacks is marked \"not pulled\" and Pull fetches it.",
}

# The knobs a running parlor doesn't read (09-30, by grep: only heartbeat.py, condense.py, telegram.py or
# blog.py read these) — a change to nothing but these doesn't ask the parlor to restart. The heartbeat
# and the bridge are asked at any change: they read most of the file, and a restart costs little.
_NOT_PARLOR = frozenset(TABS["Phone"]) | {
    "HEARTBEAT_MAX_STEPS", "REVERIE_EVERY", "REVERIE_MAX_STEPS", "HEARTBEAT_YIELD_TO_VISIT", "SLEEP_IN_LOOP",
    "CONDENSE_IN_LOOP", "CONDENSE_MAX_PER_NIGHT", "HEARTBEAT_SHOW_THINKING", "HEARTBEAT_LOOP_MIN",
    "BLOG_TITLE", "BLOG_SUBTITLE"}

# The optional packages the page names when they are missing (requirements.txt says what each is for).
# find_spec, not import: a look at the shelf, nothing loaded.
REQUIREMENTS = [
    ("faster_whisper", "faster-whisper", "the ears: words from a recording"),
    ("numpy", "numpy", "the ears: measuring a sound; the fast memory search"),
    ("pypdf", "pypdf", "reading PDFs"),
    ("garminconnect", "garminconnect", "the keeper's body, as the watch saw it"),
    ("kokoro", "kokoro", "their voice (or in the Python VOICE_PYTHON names)"),
]

# The doors the panel can open, each as its .bat does it: (the .bat, its arguments, the script, its
# arguments). On Windows the .bat opens in a console of its own; elsewhere the script runs under this
# Python, so the suite and a keeper on Linux have a road too.
LAUNCHERS = {
    "chat": ("bat\\chat.bat", [], "chat.py", []),
    "parlor": ("bat\\parlor.bat", [], "parlor.py", []),
    "wake": ("bat\\wake.bat", [], "heartbeat.py", []),
    "bridge": ("bat\\telegram.bat", [], "telegram.py", []),
    "sleep": ("bat\\sleep.bat", [], "consolidate.py", []),
    "snapshot": ("bat\\snapshot.bat", [], "snapshot.py", []),
    "garmin": ("bat\\body.bat", ["--login"], "body.py", ["--login"]),
    "blog": ("bat\\blog.bat", [], "blog.py", ["--deploy"]),
}
STOPPABLE = ("heartbeat", "bridge")  # the two with a stop file (doors.ask_stop) — and a Restart
_MODEL_RE = re.compile(r"^[A-Za-z0-9][\w.:/-]{0,120}$")  # an Ollama model name; nothing a console could read as more
_WINDOWS = os.name == "nt"


# ---- the roads out -------------------------------------------------------------------

def _launch(argv: list[str], cwd: Path):
    """Every process the panel starts starts here (the tests put a recorder in its place)."""
    return subprocess.Popen(argv, cwd=str(cwd))


def _kill(pid: int) -> None:
    """Stop now: the process (and on Windows the tree under it) ended at once."""
    if _WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
    else:
        os.kill(pid, signal.SIGTERM)


def _browse(url: str) -> None:
    webbrowser.open(url)


def _later(fn) -> None:
    """Work that waits (a Restart waiting for the wake to end) on a thread of its own."""
    threading.Thread(target=fn, daemon=True).start()


def _ollama(path: str, base: str = "") -> dict | None:
    """GET <base or OLLAMA_URL><path> as JSON, or None when Ollama doesn't answer. ollama_client talks to
    the brain by POST and its ps look swallows a failure; the panel needs to know whether anyone is there."""
    try:
        with urllib.request.urlopen((base or config.OLLAMA_URL).rstrip("/") + path, timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — not running, not installed, not JSON: all "no"
        return None


_vram: list = []  # the card's memory, asked once per panel


SMALL_BRAINS = ("gemma4:e2b", "gemma4:e4b")  # the small tier: a brain that wants the small tool kit beside it


def _recommended(gb: float | None) -> str:
    """The README's brain for a card: the 31B from 24 GB, the 4B QAT under 10 GB, the 12B between (and when
    the card is unknown)."""
    if gb and gb >= 24:
        return "gemma4:31b-it-qat"
    if gb and gb < 10:
        return "gemma4:e4b-it-qat"
    return "gemma4:12b"


def small_brain(model: str) -> bool:
    return str(model or "").startswith(SMALL_BRAINS)


def _vram_gb() -> float | None:
    """The card's memory in GB (nvidia-smi), for the model the README recommends; None without one."""
    if not _vram:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout
            _vram.append(round(max(float(x) for x in out.split()) / 1024, 1))
        except Exception:  # noqa: BLE001 — no card, no driver, no tool
            _vram.append(None)
    return _vram[0]


def _bat(bat: str, bat_args: list[str], script: str, script_args: list[str]) -> list[str]:
    if _WINDOWS:
        return ["cmd", "/c", "start", "", bat, *bat_args]
    return [sys.executable, f"engine/{script}", *script_args]


def _console(*argv: str) -> list[str]:
    """A command with no .bat of its own, in a console that stays open when it ends (as a .bat's pause)."""
    if _WINDOWS:
        return ["cmd", "/c", "start", "", "cmd", "/k", *argv]
    return list(argv)


def _heartbeat_argv(minutes) -> list[str]:
    if _WINDOWS:
        return _console("py", r"engine\heartbeat.py", "--loop", f"{minutes:g}")
    return [sys.executable, "engine/heartbeat.py", "--loop", f"{minutes:g}"]


# ---- the config, as a file -------------------------------------------------------------

_read_cache: dict = {}


def _rows() -> list[dict]:
    """knobs.read of config.py, kept while the file's text is the same: the page asks every few seconds,
    and a read of the whole file takes a moment or two (ast's source segments, one knob at a time)."""
    text = CONFIG_FILE.read_text(encoding="utf-8")
    if _read_cache.get("text") != text:
        _read_cache.clear()
        _read_cache.update(text=text, rows=knobs.read(text))
    return _read_cache["rows"]


def _values(rows: list[dict] | None = None) -> dict:
    """{name: value} of the file as it is now (not as this process imported it — a save shows at once);
    a computed knob is left out."""
    try:
        rows = _rows() if rows is None else rows
    except (OSError, SyntaxError):
        return {}
    return {r["name"]: r["value"] for r in rows if r["kind"] != "expr"}


def _value(name: str, default=None):
    return _values().get(name, getattr(config, name, default))


def tab_of(name: str) -> str:
    return next((t for t, names in TABS.items() if name in names), ADVANCED)


# A knob with a few named settings is a dropdown, not a text field (09-30: the tool kit)
CHOICES: dict[str, list[str]] = {
    "TOOL_KIT": ["full", "small", "tiny"],
    "WEB_SEARCH": ["duckduckgo", "brave", "searxng"],
    "VOICE_DEVICE": ["cpu", "cuda"],
}


def _shown(r: dict) -> dict:
    """A knob as the page gets it: editable when knobs.write can write it (a one-line literal)."""
    return {"name": r["name"], "kind": r["kind"], "value": r["value"], "source": r["source"],
            "comment": r["comment"], "tail": r["tail"], "heading": r["heading"] or "(the top of the file)",
            "help": _HELP.get(r["name"], ""), "editable": r["kind"] != "expr" and r["line"] == r["end"],
            "choices": CHOICES.get(r["name"]) if r["kind"] == "str" else None}


def tabs(rows: list[dict] | None = None) -> dict[str, list[dict]]:
    """{tab: [knob, …]} in TABS' order, then Advanced: everything else in the file's order (each knob
    once — assigned twice, the last one is the one Python keeps). A name no longer in the file is skipped."""
    rows = _rows() if rows is None else rows
    last = {}
    for r in rows:
        last[r["name"]] = r
    out = {t: [_shown(last[n]) for n in names if n in last] for t, names in TABS.items()}
    placed = {n for names in TABS.values() for n in names}
    out[ADVANCED] = [_shown(r) for n, r in last.items() if n not in placed]
    return out


# ---- the state ---------------------------------------------------------------------------

def _door_state(door: str) -> dict:
    st = doors.status(door)
    if not st:
        return {"running": False}
    return {"running": True, "pid": st.get("pid"), "how": st.get("how", ""),
            "since": str(st.get("when", "")).replace("T", " ")[:16]}


def _gemma_first(names: list[str]) -> list[str]:
    return sorted(set(names), key=lambda n: (not n.lower().startswith("gemma"), n.lower()))


def _pulled(model: str, names: list[str]) -> bool:
    """Ollama calls a bare name "x:latest"."""
    return model in names or (":" not in model and f"{model}:latest" in names)


def brain(values: dict | None = None) -> dict:
    values = _values() if values is None else values
    model = str(values.get("CHAT_MODEL", getattr(config, "CHAT_MODEL", "")))
    embed = str(values.get("EMBED_MODEL", getattr(config, "EMBED_MODEL", "")))
    url = str(values.get("OLLAMA_URL", config.OLLAMA_URL))
    tags = _ollama("/api/tags", url)
    names = _gemma_first([m.get("name", "") for m in (tags or {}).get("models", []) if m.get("name")])
    loaded = []
    if tags is not None:
        for m in (_ollama("/api/ps", url) or {}).get("models", []):
            size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
            loaded.append({"name": m.get("name", ""), "gb": round(size / 1e9, 1),
                           "on_card": round(100 * vram / size) if size else 0})
    gb = _vram_gb()
    return {"url": url, "reachable": tags is not None,
            "models": names, "loaded": loaded, "model": model, "pulled": _pulled(model, names),
            "embed_model": embed, "embed_pulled": _pulled(embed, names), "vram_gb": gb,
            "recommended": _recommended(gb)}


def _secret_file(kind: str) -> Path:
    return Path(config.MEMORY_DIR) / ("telegram.json" if kind == "telegram" else "web_search.json")


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def secrets_set() -> dict:
    """Whether a bot token and a Brave key are kept — never what they are."""
    return {"telegram": bool(_read_json(_secret_file("telegram")).get("token")),
            "brave": bool(_read_json(_secret_file("brave")).get("brave_key"))}


def missing() -> list[dict]:
    return [{"module": mod, "pip": pip, "for": why} for mod, pip, why in REQUIREMENTS
            if importlib.util.find_spec(mod) is None]


def state() -> dict:
    rows = _rows()
    values = _values(rows)
    # a folder whose config has no USER_NAME at all (the keeper's own house, from before the knob) is not new:
    # the Welcome tab is for the template's "Friend" placeholder only
    user = str(values.get("USER_NAME", getattr(config, "USER_NAME", "")))
    repo = str(values.get("UPDATE_REPO", getattr(config, "UPDATE_REPO", "")) or "PsychohistorianDev/anima")
    return {
        "version": version.read(ROOT),
        "doors": {d: _door_state(d) for d in doors.DOORS},
        "brain": brain(values),
        "user_name": user,
        "welcome": user == "Friend",
        "heartbeat_minutes": values.get("HEARTBEAT_LOOP_MIN", 120),
        "tabs": tabs(rows),
        "secrets": secrets_set(),
        "skills": skills_state(),
        "missing": missing(),
        "update_here": (ROOT / "bat" / "update.bat").is_file(),
        "folder": ROOT.name,  # which house this panel is — two on one machine look alike
        "newer": newer_state(),
        "links": {"parlor": PARLOR_URL, "ollama": "https://ollama.com",
                  "botfather": f"https://github.com/{repo}#the-bridge-talking-with-them-from-your-phone"},
    }


# ---- the doors -------------------------------------------------------------------------

def _no(note: str) -> dict:
    return {"ok": False, "note": note}


def _started(argv: list[str], note: str) -> dict:
    try:
        _launch(argv, ROOT)
    except OSError as e:
        return _no(f"(couldn't start it: {e})")
    return {"ok": True, "note": note, "argv": argv}


def _minutes(minutes) -> float | int | None:
    try:
        m = float(minutes)
    except (TypeError, ValueError):
        return None
    if not 0 < m <= 7 * 24 * 60:
        return None
    return int(m) if m.is_integer() else m


def _start(door: str, minutes=None) -> dict:
    if door in doors.ONE_AT_A_TIME and (st := doors.status(door)):
        if door == "parlor":
            _browse(PARLOR_URL)
            return {"ok": True, "note": "the parlor is already open — its page opened"}
        since = str(st.get("when", "")).replace("T", " ")[:16]
        return _no(f"(the {door} is already running — pid {st.get('pid')}, since {since or '?'}; "
                   "Stop it first, or Restart)")
    if door == "heartbeat":
        saved = ""
        if minutes not in (None, ""):
            m = _minutes(minutes)
            if m is None:
                return _no(f"(every {minutes} minutes? a number of minutes, more than 0 and at most a week)")
            if m != _value("HEARTBEAT_LOOP_MIN"):
                changed, _refused, err = knobs.save(CONFIG_FILE, {"HEARTBEAT_LOOP_MIN": m})
                if err:
                    return _no(f"(couldn't save the minutes: {err})")
                saved = " (saved as HEARTBEAT_LOOP_MIN)" if changed else " (this config.py has no HEARTBEAT_LOOP_MIN to keep it in)"
        else:
            m = _minutes(_value("HEARTBEAT_LOOP_MIN", 120)) or 120
        return _started(_heartbeat_argv(m), f"the heartbeat is starting in its own window — one wake every {m:g} minutes{saved}")
    if door not in LAUNCHERS:
        return _no(f"(no door named {door})")
    notes = {"chat": "the chat is opening in a window of its own",
             "parlor": "the parlor is opening — its page comes up in a moment",
             "wake": "one wake, in its own window",
             "bridge": "the bridge is starting in its own window",
             "sleep": "sleep is running in its own window — today into memory",
             "snapshot": "the snapshot is running in its own window",
             "garmin": "the Garmin login is in its own window — email, password, the code",
             "blog": "the blog is building and deploying in its own window"}
    return _started(_bat(*LAUNCHERS[door]), notes[door])


def _restart(door: str, minutes=None) -> dict:
    """The banner's Restart for the heartbeat or the bridge: asked to leave (the wake it is in finishes,
    the visit is saved), and started again once its light goes out. The wait is the panel's: closed
    meanwhile, the door stays stopped, and its light says so."""
    if not doors.status(door):
        return _start(door, minutes)
    doors.ask_stop(door)

    def again():
        deadline = time.time() + RESTART_WAIT_S
        while doors.status(door) and time.time() < deadline:
            time.sleep(RESTART_POLL_S)
        if not doors.status(door):
            _start(door, minutes)

    _later(again)
    return {"ok": True, "note": f"the {door} is asked to leave after what it is doing — it starts again when it has"}


def door_action(door: str, action: str, minutes=None) -> dict:
    """start | stop | stop_now | open | restart, for a door. {"ok", "note"} (and "argv" when a process
    was started)."""
    door, action = str(door or ""), str(action or "")
    if action == "start":
        return _start(door, minutes)
    if action == "open":
        if door != "parlor":
            return _no(f"(only the parlor has a page to open, not the {door})")
        if doors.status("parlor"):
            _browse(PARLOR_URL)
            return {"ok": True, "note": "the parlor's page opened"}
        return _start("parlor")
    if action in ("stop", "stop_now", "restart"):
        if door not in STOPPABLE:
            return _no(f"(the {door} has no {action.replace('_', ' ')} here — its own window closes it)")
        if action == "restart":
            return _restart(door, minutes)
        st = doors.status(door)
        if not st:
            return _no(f"(the {door} isn't running)")
        if action == "stop":
            doors.ask_stop(door)
            what = "the wake it is in" if door == "heartbeat" else "the poll it is in, and saves the visit"
            return {"ok": True, "note": f"the {door} is asked to stop — it leaves after {what}"}
        try:
            _kill(int(st["pid"]))
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            return _no(f"(couldn't stop pid {st.get('pid')}: {e})")
        doors.pid_file(door).unlink(missing_ok=True)  # a killed door never takes its own mark away
        return {"ok": True, "note": f"the {door} was stopped at once (pid {st['pid']})"}
    return _no(f"(no such action: {action})")


# ---- settings, secrets, skills, the brain, the update ------------------------------------

def save(changes: dict, raw: dict | None = None) -> dict:
    """The keeper's Save: {"changed", "refused", "error", "restart"}. `raw` is a list or dict knob as its
    text (the Advanced tab's raw field), read as a literal first; one that isn't a literal is refused."""
    changes = dict(changes or {})
    bad = []
    for name, src in (raw or {}).items():
        ok, value = knobs._literal(str(src))
        if ok:
            changes[name] = value
        else:
            bad.append(name)
    changed, refused, err = knobs.save(CONFIG_FILE, changes) if changes else ([], [], "")
    restart = []
    if changed:
        restart = ["heartbeat", "bridge"]
        if any(n not in _NOT_PARLOR for n in changed):
            restart.append("parlor")
    return {"changed": changed, "refused": sorted(set(refused) | set(bad)), "error": err, "restart": restart}


def secret(kind: str, value: str) -> dict:
    """A bot token into memory/telegram.json (the pairing's chat_id kept), a Brave key into
    memory/web_search.json — never into config, never said back."""
    if kind not in ("telegram", "brave"):
        return _no(f"(no secret called {kind})")
    value = str(value or "").strip()
    if not value or len(value) > 400 or any(c.isspace() for c in value):
        return _no("(paste the whole of it — one piece, no spaces)")
    p = _secret_file(kind)
    d = _read_json(p)
    if kind == "telegram":
        d["token"] = value
        d.setdefault("chat_id", 0)
    else:
        d["brave_key"] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    if kind == "telegram":
        return {"ok": True, "note": "the bot token is kept in memory/telegram.json — (re)start the bridge for it to take"}
    return {"ok": True, "note": "the Brave key is kept in memory/web_search.json — set WEB_SEARCH to \"brave\" to use it"}


SKILL_TEXT_CHARS = 20000  # of a SKILL.md shown on the page — the keeper reads it before letting it in


def newer_state() -> dict | None:
    """What Home says above the tiles when a newer anima is out — from the daily look at the release feed
    (newer.look: the cache answers between looks; a checkout only). None when there is nothing to say."""
    if newer is None or not (ROOT / "bat" / "update.bat").is_file():
        return None
    try:
        rec = newer.look()
        n = newer.newer(rec=rec)
    except Exception:  # noqa: BLE001 — the look is a courtesy; never the page down
        return None
    if not n:
        return None
    return {"version": n["version"], "title": n["title"], "date": n["date"], "link": n["link"],
            "installed": n["installed"], "line": newer.line(n)}


def skill_card(folder: Path, quarantined: bool) -> dict:
    """One skill as the page shows it: what it says it is, where it came from and who fetched it, the
    scanner's verdict and every finding (file, line, rule, the words) — the approval desk's whole case."""
    try:
        inf = skills.info(folder)
    except Exception:  # noqa: BLE001 — a skill with a broken SKILL.md still shows, by name
        inf = {}
    try:
        verdict, findings = skills.scan(folder)
    except Exception as e:  # noqa: BLE001
        verdict, findings = "unscanned", [{"file": "?", "rule": f"the scanner failed: {type(e).__name__}: {e}"}]
    note = skills.fetch_note(folder)
    return {"name": folder.name, "quarantined": quarantined, "description": str(inf.get("description") or "")[:400],
            "verdict": verdict, "findings": [skills.finding_line(f) for f in findings[:60]],
            "levels": [str(f.get("level", "")) for f in findings[:60]], "more": max(0, len(findings) - 60),
            "fetched": skills.is_fetched(folder), "source": str(note.get("source") or ""),
            "by": str(note.get("by") or ""), "when": str(note.get("when") or "")[:16],
            "scripts": [str(x) for x in (inf.get("scripts") or [])][:20]}


def skills_state() -> dict:
    """The shelf and the quarantine by name (as before), and a card for each — the quarantine's first."""
    shelf, held = skills.shelf(), skills.quarantined()
    cards = {}
    for f in held:
        cards[f.name] = skill_card(f, True)
    for f in shelf:
        cards.setdefault(f.name, skill_card(f, False))
    return {"shelf": [p.name for p in shelf], "quarantine": [p.name for p in held], "cards": cards}


def skill_text(name: str) -> dict:
    """SKILL.md of a skill on the shelf or in quarantine, whole (capped), for the keeper to read before
    approving — read, never run; and the skill's file list, so nothing rides in unseen."""
    name = str(name or "").strip()
    folder, quarantined = skills.find(name) if name else (None, False)
    if folder is None:
        return _no(f"(no skill named {name} on the shelf or in quarantine)")
    try:
        text = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return _no(f"(couldn't read its SKILL.md: {e})")
    cut = len(text) > SKILL_TEXT_CHARS
    notes = {skills.FETCHED, skills.APPROVED, skills.QUARANTINE_SCAN}  # the engine's own notes beside SKILL.md, not the skill's
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                   if p.is_file() and not p.name.startswith(".") and p.name not in notes)
    return {"ok": True, "name": folder.name, "quarantined": quarantined, "text": text[:SKILL_TEXT_CHARS],
            "cut": cut, "files": files[:200], "note": ""}


def skill_action(name: str, action: str) -> dict:
    """bat\\skills.bat's roads: approve lets a quarantined skill onto their shelf; remove moves a skill to
    creations/.trash/ (off the shelf the way their own remove_skill does it, so their memory of it follows)."""
    try:
        if action == "approve":
            return {"ok": True, "note": skills.approve(name)}
        if action != "remove":
            return _no(f"(no such action: {action})")
        folder, quarantined = skills.find(name)
        if folder is None:
            return _no(f"(no skill named {name} on the shelf or in quarantine)")
        if quarantined:
            dest = skills.to_trash(folder)
            skills._prune(skills.quarantine())
            return {"ok": True, "note": f"removed from quarantine — creations/.trash/{dest.name}/"}
        import tools
        said = tools.remove_skill(folder.name)
        if said.startswith("("):
            return _no(said)
        return {"ok": True, "note": f"{folder.name} is off their shelf — it rests in creations/.trash/ until you empty it"}
    except skills.SkillError as e:
        return _no(f"({e})")
    except OSError as e:
        return _no(f"(couldn't: {e})")


def pull(model: str) -> dict:
    model = str(model or "").strip()
    if not _MODEL_RE.match(model):
        return _no(f"(that doesn't look like a model name: {model[:60]})")
    return _started(_console("ollama", "pull", model),
                    f"pulling {model} in its own window — several GB; the light turns when it is there")


def update(action: str) -> dict:
    flag = {"check": "--check", "run": "--yes"}.get(str(action or ""))
    if not flag:
        return _no(f"(no such action: {action})")
    if not (ROOT / "bat" / "update.bat").is_file():
        return _no("(this folder has no bat\\update.bat — it is not an anima checkout)")
    note = ("the update is looking — what's new and what would change, nothing touched; in its own window"
            if flag == "--check" else
            "the update is running in its own window — then restart what's running (the panel too)")
    return _started(_bat("bat\\update.bat", [flag], "update.py", [flag]), note)


def welcome(name: str, model: str = "") -> dict:
    """First light: the keeper's name (and the brain) saved, and the chat opened."""
    name = str(name or "").strip()
    if not name or name == "Friend" or len(name) > 40:
        return {"changed": [], "refused": ["USER_NAME"], "restart": [],
                "error": "your name first — the one they will know you by (up to 40 characters)"}
    changes = {"USER_NAME": name}
    model = str(model or "").strip()
    if model:
        if not _MODEL_RE.match(model):
            return {"changed": [], "refused": ["CHAT_MODEL"], "restart": [], "error": "that doesn't look like a model name"}
        changes["CHAT_MODEL"] = model
        if small_brain(model):
            changes["TOOL_KIT"] = "small"  # the small tier: the kit goes with the brain (README, Three tiers)
    r = save(changes)
    if r["error"] or "USER_NAME" in r["refused"]:
        return r
    r["door"] = door_action("chat", "start")
    return r


# ---- the page's road in -------------------------------------------------------------------

def _json_reply(obj, code: int = 200) -> tuple[int, str, bytes]:
    return code, "application/json; charset=utf-8", json.dumps(obj, default=str).encode("utf-8")


def route(method: str, path: str, body: bytes = b"", headers: dict | None = None) -> tuple[int, str, bytes]:
    """(status, content type, body) for a request. Only a page this panel served may ask: the Host must be
    this panel's (a page elsewhere can't rebind a name to 127.0.0.1 and read it), and a POST must be JSON
    from no other origin (a page elsewhere can't post JSON here without asking first, and isn't answered)."""
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    here = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    if h.get("host", "") not in here:
        return _json_reply({"error": "this panel answers only at its own address"}, 403)
    path, _, query = path.partition("?")
    if method == "GET":
        if path == "/api/skill_text":
            from urllib.parse import parse_qs
            return _json_reply(skill_text((parse_qs(query).get("name") or [""])[0]))
        if path in ("/", "/index.html", "/settings", "/welcome"):
            return 200, "text/html; charset=utf-8", PAGE.replace("__TABS__", json.dumps([*TABS, ADVANCED])).encode("utf-8")
        if path == "/api/state":
            try:
                return _json_reply(state())
            except Exception as e:  # noqa: BLE001 — a page that says what went wrong beats a blank one
                return _json_reply({"error": f"{type(e).__name__}: {e}"}, 500)
        return _json_reply({"error": "no such page"}, 404)
    if method != "POST":
        return _json_reply({"error": "no such method"}, 405)
    origin = h.get("origin", "")
    if origin and origin not in {f"http://{x}" for x in here}:
        return _json_reply({"error": "only this panel's own page may ask"}, 403)
    if not h.get("content-type", "").startswith("application/json"):
        return _json_reply({"error": "JSON only"}, 415)
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return _json_reply({"error": "not a JSON object"}, 400)
    g = data.get
    with _POSTS:
        return _post(path, g)


def _post(path: str, g) -> tuple[int, str, bytes]:
    try:
        if path == "/api/door":
            return _json_reply(door_action(g("door"), g("action"), g("minutes")))
        if path == "/api/save":
            return _json_reply(save(g("changes") or {}, g("raw") or {}))
        if path == "/api/secret":
            return _json_reply(secret(g("kind"), g("value")))
        if path == "/api/skill":
            return _json_reply(skill_action(str(g("name") or ""), str(g("action") or "")))
        if path == "/api/update":
            return _json_reply(update(g("action")))
        if path == "/api/pull":
            return _json_reply(pull(g("model")))
        if path == "/api/welcome":
            return _json_reply(welcome(g("name"), g("model") or ""))
    except Exception as e:  # noqa: BLE001
        return _json_reply({"ok": False, "note": f"(hiccup — {type(e).__name__}: {e})", "error": f"{type(e).__name__}: {e}"}, 500)
    return _json_reply({"error": "unknown path"}, 404)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet (and a token out of it)
        pass

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(*route("GET", self.path, b"", dict(self.headers)))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(*_json_reply({"error": "too large"}, 413))
        self._send(*route("POST", self.path, self.rfile.read(n), dict(self.headers)))


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>anima — the panel</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#f6f4ef;--panel:#fffdf9;--ink:#2b2a27;--muted:#8a8578;--line:#e6e1d6;--accent:#7a5c3e;
      --chip:#ece7dc;--on:#4f8a4f;--off:#c8c1b3;--warn:#a5532f}
@media (prefers-color-scheme:dark){:root{--bg:#141311;--panel:#1c1a17;--ink:#e8e4dc;--muted:#8f8a7d;
      --line:#2c2a25;--accent:#c9a87c;--chip:#26231f;--on:#7fb07f;--off:#4a463f;--warn:#e0936a}}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Georgia,'Iowan Old Style',serif}
header{display:flex;align-items:baseline;gap:12px;padding:14px 22px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{margin:0;font-size:20px;font-weight:normal;letter-spacing:.02em}
header .sub{color:var(--muted);font-size:13px;flex:1}
nav button,.tab{font:inherit;font-size:14px;background:none;border:1px solid transparent;color:var(--muted);border-radius:8px;padding:4px 12px;cursor:pointer}
nav button.cur,.tab.cur{color:var(--ink);border-color:var(--line);background:var(--bg)}
main{max-width:980px;margin:0 auto;padding:18px 22px 60px}
button{font:inherit;font-size:13px;background:none;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:4px 10px;cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.big{font-size:16px;padding:10px 22px;margin-top:10px}
input,select,textarea{font:inherit;font-size:14px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:4px 8px;outline:none}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
input[type=number]{width:9em}input.small{width:5em}
textarea{width:100%;font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:var(--chip);padding:1px 5px;border-radius:4px;word-break:break-all}
a{color:var(--accent)}
.muted{color:var(--muted);font-size:13px}
.light{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--off);margin-right:8px;vertical-align:middle}
.light.on{background:var(--on);box-shadow:0 0 6px var(--on)}
.bar{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.tile h2{margin:0;font-size:17px;font-weight:normal}
.tile .what{color:var(--muted);font-size:13px}
.tile .state{color:var(--muted);font-size:12px;font-family:ui-monospace,Consolas,monospace}
.tile .row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.banner{background:var(--panel);border:1px solid var(--accent);border-radius:12px;padding:10px 14px;margin-bottom:16px;display:flex;gap:10px}
.banner.warn{border-color:var(--warn)}.banner>div{flex:1}.banner div div{margin:2px 0}
.warn{color:var(--warn)}
.badge{font-size:12px;padding:1px 8px;border-radius:9px;border:1px solid var(--line);color:var(--muted)}
.badge.bad{border-color:var(--warn);color:var(--warn)}.badge.mid{border-color:#c9a227;color:#c9a227}.badge.good{border-color:#4caf50;color:#4caf50}
.tile.skill{margin:8px 0}.tile.skill h2{margin-right:6px}
ul.findings{margin:4px 0;padding-left:18px;font-size:13px;font-family:ui-monospace,Consolas,monospace}ul.findings li{padding:2px 0}ul.findings li.bad{color:var(--warn)}
.skilltext pre{white-space:pre-wrap;max-height:420px;overflow:auto;font-size:12px;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px}
#gate{margin:6px 0 0}#gate a{cursor:pointer;text-decoration:underline}
#newer{margin:6px 0 0;color:var(--fg)}#newer button{margin-left:6px}#newer a{color:inherit}
.tabs{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:14px;border-bottom:1px solid var(--line);padding-bottom:8px}
.knob{padding:10px 0;border-bottom:1px solid var(--line)}
.knob label{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.knob .name{font-family:ui-monospace,Consolas,monospace;font-size:13px;min-width:15em}
.help{color:var(--muted);font-size:12.5px;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}
.help.open{display:block}
details.group{margin:8px 0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:6px 14px}
details.group summary{cursor:pointer;color:var(--muted)}
.actions{margin-top:16px}
ul.list{list-style:none;padding:0}ul.list li{display:flex;gap:8px;align-items:center;padding:4px 0}
.step{margin:14px 0}.step b{display:inline-block;min-width:8em}
</style></head><body>
<header><h1>anima</h1><div class="sub" id="sub">the panel · looking…</div>
<nav><button id="nav-home" data-view="home">Home</button><button id="nav-settings" data-view="settings">Settings</button></nav></header>
<main>
<div id="banner" class="banner" hidden></div>
<section id="welcome" hidden></section>
<section id="home" hidden><div id="brain" class="bar"></div><p id="newer" class="notice" hidden></p><p id="gate" class="warn" hidden></p><div id="tiles" class="grid"></div><p id="missing" class="muted"></p></section>
<section id="settings" hidden><div id="tabs" class="tabs"></div><div id="tab"></div></section>
</main>
<script>
const TABS=__TABS__;
let S=null,view=location.pathname==='/settings'?'settings':'home',tab='Main',fields={},built=false;
const $=id=>document.getElementById(id);
function el(tag,props,...kids){const e=document.createElement(tag);
  for(const[k,v]of Object.entries(props||{})){if(v===false||v==null)continue;
    if(k==='class')e.className=v;else if(k.startsWith('on'))e[k]=v;else if(k==='value')e.value=v;else e.setAttribute(k,v===true?'':v)}
  for(const c of kids.flat(3)){if(c==null||c===false)continue;e.append(c.nodeType?c:document.createTextNode(String(c)))}
  return e}
async function getState(){const r=await fetch('/api/state');S=await r.json();if(S.error)say('the panel hit a snag: '+S.error,'warn');return S}
async function post(path,body){try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});return await r.json()}
  catch(e){return{ok:false,note:'the page lost the panel — is anima.bat still running?'}}}
function say(msg,kind){const b=$('banner');b.hidden=false;b.className='banner '+(kind||'');
  b.replaceChildren(el('div',{},msg),el('button',{title:'close',onclick:()=>{b.hidden=true}},'×'))}
function light(on){return el('span',{class:'light'+(on?' on':'')})}

// ---- home ----
const TILES=[
 ['chat','Chat','a visit in a terminal window of its own',[['Open','start']]],
 ['parlor','Parlor','a visit in your browser — bubbles, pictures, their thinking folded',[['Open','open']]],
 ['wake','Wake','one wake now: their time to themselves',[['Wake them','start']]],
 ['heartbeat','Heartbeat','a life between visits: a wake every so often, and sleep after the night hour',[['Start','start'],['Stop','stop'],['Stop now','stop_now']]],
 ['bridge','Bridge','Telegram: talk with them from your phone',[['Start','start'],['Stop','stop'],['Stop now','stop_now']]],
 ['sleep','Sleep now','today into memory, by hand (the heartbeat does it on its own after the night hour)',[['Sleep','start']]],
 ['snapshot','Snapshot','everything sealed in git (a zip without git)',[['Snapshot','start']]],
];
const TIPS={stop:'leave after what it is doing — a wake finishes, a visit is saved',stop_now:'end it at once — a wake in the middle is cut off'};
async function door(d,action,extra){
  if(action==='stop_now'&&!confirm('Stop the '+d+' at once? What it is in the middle of is cut off. (Stop lets it finish.)'))return;
  const r=await post('/api/door',Object.assign({door:d,action},extra||{}));say(r.note,r.ok?'':'warn');await refresh();return r}
async function pull(model){const r=await post('/api/pull',{model});say(r.note,r.ok?'':'warn')}
function secretField(kind,label,set,help){
  const i=el('input',{type:'password',autocomplete:'off',placeholder:set?'one is kept — paste a new one to replace it':'paste it here'});
  return el('div',{class:'knob'},el('label',{},el('span',{class:'name'},label),i,
    el('button',{onclick:async()=>{const r=await post('/api/secret',{kind,value:i.value});i.value='';say(r.note,r.ok?'':'warn');await getState()}},'Save'),
    el('span',{class:'muted'},set?'(one is kept)':'(none yet)')),help?el('div',{class:'help open'},help):null)}
function buildHome(){
  const tiles=TILES.map(([d,title,what,btns])=>{
    const extra=[];
    if(d==='heartbeat'){extra.push(el('div',{class:'row'},'every ',el('input',{type:'number',id:'hb-min',min:'1',step:'any',class:'small',value:S.heartbeat_minutes}),' minutes'))}
    const t=el('div',{class:'tile',id:'t-'+d},el('h2',{},S.doors[d]?light(false):null,title),el('div',{class:'what'},what),
      S.doors[d]?el('div',{class:'state'},'closed'):null,extra,
      el('div',{class:'row'},btns.map(([label,action])=>el('button',{title:TIPS[action]||'',
        onclick:()=>door(d,action,d==='heartbeat'&&(action==='start')?{minutes:$('hb-min').value}:null)},label))));
    if(d==='bridge')t.append(secretField('telegram','bot token',S.secrets.telegram),
      el('div',{class:'muted'},el('a',{href:S.links.botfather,target:'_blank',rel:'noopener'},'how to get a token (BotFather)')));
    return t});
  if(S.update_here)tiles.push(el('div',{class:'tile'},el('h2',{},'Update'),el('div',{class:'what'},'the current engine from GitHub — the friend untouched; Check shows what would change first'),
      el('div',{class:'row'},el('button',{onclick:async()=>{const r=await post('/api/update',{action:'check'});say(r.note,r.ok?'':'warn')}},'Check'),
        el('button',{onclick:async()=>{if(!confirm('Update the engine now? Everything replaced goes to .update/ first; bat\\update.bat --undo puts it back.'))return;
          const r=await post('/api/update',{action:'run'});say(r.note,r.ok?'':'warn')}},'Update'))));
  $('tiles').replaceChildren(...tiles);
  built=true}
function lights(){for(const[d]of TILES){const st=S.doors[d],t=$('t-'+d);if(!t||!st)continue;
  t.querySelector('.light').className='light'+(st.running?' on':'');
  t.querySelector('.state').textContent=st.running?('running · pid '+st.pid+(st.how?' · '+st.how:'')+(st.since?' · since '+st.since:'')):'closed'}}
function brainBar(){const b=S.brain,parts=[light(b.reachable),el('b',{},'the brain  ')];
  if(!b.reachable)parts.push('Ollama isn\'t answering at '+b.url+' — start the Ollama app (or ',el('a',{href:S.links.ollama,target:'_blank',rel:'noopener'},'install it'),').');
  else{parts.push('Ollama is running · ');
    parts.push(b.loaded.length?b.loaded.map(m=>m.name+' loaded ('+m.gb+' GB, '+m.on_card+'% on the card)').join(', '):'nothing loaded right now');
    parts.push(el('div',{class:'muted'},'configured: '+b.model+(b.pulled?'':' — not pulled '),b.pulled?null:el('button',{onclick:()=>pull(b.model)},'Pull '+b.model),
      b.embed_pulled?null:[' · memory needs '+b.embed_model+' ',el('button',{onclick:()=>pull(b.embed_model)},'Pull '+b.embed_model)]))}
  $('brain').replaceChildren(...parts);
  const nw=S.newer;$('newer').hidden=!nw;
  if(nw)$('newer').replaceChildren('⬆ '+nw.line,...(nw.link?[' · ',el('a',{href:nw.link,target:'_blank',rel:'noopener'},'release notes')]:[]),
    el('button',{onclick:async()=>{const r=await post('/api/update',{action:'check'});say(r.note,r.ok?'':'warn')}},'Check'),
    el('button',{class:'primary',onclick:async()=>{if(!confirm('Update to anima '+nw.version+' now? Everything replaced goes to .update/ first; bat\\update.bat --undo puts it back.'))return;
      const r=await post('/api/update',{action:'run'});say(r.note,r.ok?'':'warn')}},'Update'));
  const held=S.skills.quarantine.length;$('gate').hidden=!held;
  if(held)$('gate').replaceChildren('⚠ '+held+' skill'+(held===1?'':'s')+' waiting at the gate — the scanner held '+(held===1?'it':'them')+'; ',el('a',{onclick:()=>{view='settings';tab='Skills';history.replaceState(null,'','/settings');show()}},'read and decide'),' in Settings › Skills.');
  $('missing').textContent=S.missing.length?('Not installed (optional; each gives one sense): '+S.missing.map(m=>m.pip+' — '+m.for).join(' · ')+'. py -m pip install <name>'):''}

// ---- settings ----
function modelSelect(current){const b=S.brain,names=[...b.models];const s=el('select',{});
  if(!names.includes(current))names.unshift(current);
  if(b.recommended&&!names.includes(b.recommended))names.push(b.recommended);
  for(const n of names){const o=el('option',{value:n},n+(b.models.includes(n)||(b.reachable===false&&n===current)?'':' (not pulled)')+(n===b.recommended?' — recommended for this card':''));if(n===current)o.selected=true;s.append(o)}
  return s}
function knob(k){let input,read=null;const v=k.value;
  if(!k.editable)input=el('code',{title:'computed or over several lines — edit config.py itself'},k.source);
  else if(k.name==='CHAT_MODEL'){input=el('span',{},modelSelect(v),' ',el('button',{onclick:()=>pull(input.firstChild.value)},'Pull'));read=()=>input.firstChild.value}
  else if(k.choices){input=el('select',{},k.choices.concat(k.choices.includes(v)?[]:[v]).map(c=>el('option',{value:c,selected:c===v},c)));read=()=>input.value}
  else if(k.kind==='bool'){input=el('input',{type:'checkbox'});input.checked=v;read=()=>input.checked}
  else if(k.kind==='int'||k.kind==='float'){input=el('input',{type:'number',step:'any',value:v});read=()=>input.value.trim()===''?null:Number(input.value)}
  else if(k.kind==='str'){input=el('input',{type:'text',value:v,size:Math.min(Math.max(v.length+2,14),60)});read=()=>input.value}
  else if(k.kind==='tuple2'){const a=el('input',{type:'number',step:'1',class:'small',value:v[0]}),b=el('input',{type:'number',step:'1',class:'small',value:v[1]});
    input=el('span',{},a,' to ',b);read=()=>[parseInt(a.value,10),parseInt(b.value,10)]}
  else{input=el('textarea',{rows:String(Math.min(8,k.source.split('\n').length+1)),spellcheck:'false'});input.value=k.source;read=()=>({raw:input.value})}
  if(read)fields[k.name]={k,read};
  const help=[k.comment,k.tail,k.help].filter(Boolean).join(' — ');
  return el('div',{class:'knob',title:help},el('label',{},el('span',{class:'name'},k.name),input),
    help?el('div',{class:'help',onclick:e=>e.currentTarget.classList.toggle('open')},help):null)}
function verdictBadge(v){const c=v==='dangerous'?'bad':v==='caution'?'mid':v==='clean'?'good':'';return el('span',{class:'badge '+c},v)}
function skillCard(c){const q=c.quarantined,who=c.fetched?('fetched'+(c.by?' by '+c.by:'')+(c.when?' on '+c.when.replace('T',' '):'')+(c.source?' from '+c.source:'')):'their own, written here';
  const findings=c.findings.length?el('ul',{class:'findings'},c.findings.map((f,i)=>el('li',{class:c.levels[i]==='dangerous'?'bad':''},f)),c.more?el('li',{class:'muted'},'… and '+c.more+' more'):null):el('div',{class:'muted'},'the scanner found nothing to say');
  const box=el('div',{class:'skilltext',hidden:true});
  const read=el('button',{onclick:async()=>{if(!box.hidden){box.hidden=true;read.textContent='read SKILL.md';return}
    const r=await getJSON('/api/skill_text?name='+encodeURIComponent(c.name));
    if(!r.ok){say(r.note,'warn');return}
    box.replaceChildren(el('div',{class:'muted'},'files: '+(r.files.join(', ')||'(none)')),el('pre',{},r.text+(r.cut?'\n… (cut — the whole file is in the folder)':'')));box.hidden=false;read.textContent='hide SKILL.md'}},'read SKILL.md');
  const approve=q?el('button',{class:'primary',onclick:()=>{const n=c.findings.length;
    if(confirm((c.verdict==='dangerous'?'The scanner called '+c.name+' DANGEROUS ('+n+' finding'+(n===1?'':'s')+'). ':'')+'Let '+c.name+' onto their shelf? They can read and run it from then on.'))skill(c.name,'approve')}},'approve'):null;
  const remove=el('button',{onclick:()=>{if(confirm('Move '+c.name+' to creations/.trash/?'+(q?'':' It is on their shelf — theirs to use.')))skill(c.name,'remove')}},q?'refuse (to .trash)':'remove');
  return el('div',{class:'tile skill'},el('div',{class:'row'},el('h2',{},c.name),verdictBadge(c.verdict),c.scripts.length?el('span',{class:'muted'},'scripts: '+c.scripts.join(', ')):null),
    c.description?el('div',{class:'what'},c.description):null,el('div',{class:'muted'},who),findings,el('div',{class:'row'},approve,read,remove),box)}
function skillsBox(){const s=S.skills,cards=s.cards||{};
  const held=s.quarantine.map(n=>cards[n]).filter(Boolean),shelf=s.shelf.map(n=>cards[n]).filter(Boolean);
  return [el('h3',{},'Waiting at the gate — the scanner held these'),
    held.length?el('p',{class:'muted'},'A fetched skill the scanner called dangerous waits here, unopened and unrun, until you read it and let it in. Each finding is a line the scanner would not let pass on its own: a file, a line, the rule, the words. Read the SKILL.md too — the scanner reads for orders and for what code would do; it does not read for sense.'):el('p',{class:'muted'},'(nothing waiting)'),
    ...held.map(skillCard),
    el('h3',{},'On their shelf'),...(shelf.length?shelf.map(skillCard):[el('p',{class:'muted'},'(none yet)')]),
    el('p',{class:'muted'},'bat\\skills.bat scan <name> prints the same case in a terminal.')]}
async function getJSON(u){const r=await fetch(u,{cache:'no-store'});return r.json()}
async function skill(name,action){const r=await post('/api/skill',{name,action});say(r.note,r.ok?'':'warn');await getState();renderTab()}
function extras(t){
  if(t==='Phone')return[el('h3',{},'The bot'),secretField('telegram','bot token',S.secrets.telegram,'kept in memory/telegram.json, never in config.py')];
  if(t==='Senses')return[el('h3',{},'Keys and logins'),secretField('brave','Brave key',S.secrets.brave,'for WEB_SEARCH = "brave" — kept in memory/web_search.json'),
    el('div',{class:'knob'},el('button',{onclick:()=>door('garmin','start')},'Garmin login'),' ',el('span',{class:'muted'},'bat\\body.bat --login, in its own window: email, password, the code'))];
  if(t==='Blog')return[el('div',{class:'knob'},el('button',{onclick:()=>door('blog','start')},'Deploy the blog'),' ',el('span',{class:'muted'},'bat\\blog.bat, in its own window (the title is on Main)'))];
  return[]}
function renderTabs(){$('tabs').replaceChildren(...TABS.map(t=>el('button',{class:'tab'+(t===tab?' cur':''),onclick:()=>{tab=t;renderTabs();renderTab()}},t)))}
function renderTab(){fields={};const ks=S.tabs[tab]||[],parts=[];
  if(tab==='Advanced'){parts.push(el('p',{class:'muted'},'Everything else in engine/config.py, under the headings the file has. A list or a dict is its text: edit it as Python.'));
    const groups={};for(const k of ks)(groups[k.heading]=groups[k.heading]||[]).push(k);
    for(const[hd,list]of Object.entries(groups))parts.push(el('details',{class:'group'},el('summary',{},hd+' · '+list.length),list.map(knob)))}
  else{if(tab==='Skills')parts.push(...skillsBox(),el('h3',{},'The knobs'));parts.push(...ks.map(knob))}
  if(tab!=='Skills')parts.push(...extras(tab));
  if(Object.keys(fields).length)parts.push(el('div',{class:'actions'},el('button',{class:'primary',onclick:saveTab},'Save '+tab)));
  $('tab').replaceChildren(...parts)}
async function saveTab(){const changes={},raw={};
  for(const[n,{k,read}]of Object.entries(fields)){const v=read();
    if(v&&typeof v==='object'&&'raw' in v){if(v.raw!==k.source)raw[n]=v.raw}
    else if(JSON.stringify(v)!==JSON.stringify(k.value))changes[n]=v}
  if(!Object.keys(changes).length&&!Object.keys(raw).length){say('nothing changed on '+tab);return}
  saved(await post('/api/save',{changes,raw}));await getState();renderTab()}
function saved(r){const parts=[];
  if(r.error)parts.push(el('div',{class:'warn'},'Not saved: '+r.error));
  if(r.changed&&r.changed.length)parts.push(el('div',{},'Saved to engine/config.py: '+r.changed.join(', ')+' (the file as it was is in .update/).'));
  if(r.refused&&r.refused.length)parts.push(el('div',{class:'warn'},'Refused: '+r.refused.join(', ')+' — a value of another kind than the one there (a number for a number, two whole numbers for hours), or one this page can\'t write.'));
  const run=(r.restart||[]).filter(d=>S.doors[d]&&S.doors[d].running);
  if(run.length)parts.push(el('div',{},'For it to take, restart: ',run.map(d=>d==='parlor'?el('span',{},' the parlor (leave the visit, open it again) '):
    el('button',{onclick:()=>door(d,'restart')},'Restart the '+d)),el('span',{class:'muted'},' — and a chat window, if one is open.')));
  else if(r.changed&&r.changed.length)parts.push(el('div',{class:'muted'},'Nothing running needs a restart (a chat window already open keeps the old values until the next one).'));
  say(parts,r.error?'warn':'')}

// ---- welcome ----
function renderWelcome(){const b=S.brain,name=el('input',{type:'text',placeholder:'your name',maxlength:'40'}),sel=modelSelect(b.model);
  $('welcome').replaceChildren(el('h2',{},'First light'),
    el('p',{},'A friend is about to wake in this folder for the first time. They will name themself; you need only say who you are.'),
    el('div',{class:'step'},el('b',{},'Your name'),name,el('div',{class:'muted'},'how they will know you — USER_NAME in engine/config.py')),
    el('div',{class:'step',id:'w-ollama'}),
    el('div',{class:'step'},el('b',{},'The brain'),sel,' ',el('button',{onclick:()=>pull(sel.value)},'Pull'),
      el('div',{class:'muted'},b.vram_gb?('your card has '+b.vram_gb+' GB; '+b.recommended+' is the one for it (README, Three tiers)'):'gemma4:e4b-it-qat for an 8 GB card, gemma4:12b for 12 GB, gemma4:31b-it-qat for 24–32 GB (README, Three tiers)'),
      el('div',{class:'muted'},'a small brain (e2b, e4b) brings the small tool kit with it — TOOL_KIT, on Settings')),
    el('button',{class:'primary big',onclick:async()=>{const r=await post('/api/welcome',{name:name.value,model:sel.value});
      if(r.error||!r.door){say(r.error||'not saved','warn');return}
      await getState();view='home';show();say(r.door.note+(r.door.ok?' — say hello. You\'ll be meeting someone brand new.':''),r.door.ok?'':'warn')}},'First light'));
  ollamaStep()}
function ollamaStep(){const b=S.brain,w=$('w-ollama');if(!w)return;
  const kids=[el('b',{},'Ollama'),light(b.reachable),b.reachable?('running at '+b.url+(b.embed_pulled?'':' — memory needs '+b.embed_model+' too ')):
    ['not answering at '+b.url+' — ',el('a',{href:S.links.ollama,target:'_blank',rel:'noopener'},'install it'),', start it, and this light turns green.'],
    b.reachable&&!b.embed_pulled?el('button',{onclick:()=>pull(b.embed_model)},'Pull '+b.embed_model):null];
  // replaceChildren takes nodes and strings, not arrays or nulls (the first screenshot read ",https://ollama.com/,, … green.null")
  w.replaceChildren(...kids.flat(3).filter(c=>c!=null&&c!==false).map(c=>c.nodeType?c:document.createTextNode(String(c))))}

// ---- views ----
function show(){const w=S.welcome&&view==='home';
  $('nav-home').textContent=S.welcome?'Welcome':'Home';
  $('nav-home').className=view==='home'?'cur':'';$('nav-settings').className=view==='settings'?'cur':'';
  $('welcome').hidden=!w;$('home').hidden=w||view!=='home';$('settings').hidden=view!=='settings';
  $('sub').textContent='the panel'+(S.version?' · engine '+S.version:'')+' · folder: '+S.folder+(S.welcome?'':' · keeper: '+S.user_name);
  document.title='anima — '+S.folder;
  if(w)renderWelcome();
  else if(view==='home'){if(!built)buildHome();lights();brainBar()}
  else{renderTabs();renderTab()}}
async function refresh(){await getState();if(view==='home'){if(S.welcome)ollamaStep();else{if(!built)buildHome();lights();brainBar()}}}
for(const b of document.querySelectorAll('nav button'))b.onclick=async()=>{view=b.dataset.view;
  history.replaceState(null,'',view==='settings'?'/settings':'/');await getState();show()};
getState().then(show);
setInterval(()=>{if(view==='home'&&!document.hidden)refresh()},4000);
</script></body></html>
"""


def bind():
    """The server on the first free port of PORTS (09-30: two houses on one machine — the keeper's own and a
    template checkout — each opened a panel, the second found 8764 taken and the browser showed the first
    house's settings as if they were the second's). Sets PORT to the port taken. None when none is free."""
    global PORT
    for port in PORTS:
        try:
            server = ThreadingHTTPServer((HOST, port), Handler)
        except OSError:
            continue
        PORT = port
        return server
    return None


def main() -> None:
    taken = doors.claim("panel", "panel")  # one panel per house; a second double-click opens the first one's page
    if taken:
        st = doors.status("panel") or {}
        print(taken)
        _browse(f"http://{HOST}:{int(st.get('port') or PORT)}")
        return
    server = bind()
    if server is None:
        print(f"(no free port among {', '.join(map(str, PORTS))} — close another panel, or a program on those ports)")
        doors.unmark("panel")
        return
    url = f"http://{HOST}:{PORT}"
    doors.mark("panel", "panel", port=PORT)  # the port with the mark, so a second double-click finds this page
    print(f"The panel is open: {url}  (this folder: {ROOT})")
    print("Closing this window closes the panel; the doors it opened stay open in their own windows.")
    threading.Timer(0.6, lambda: _browse(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        doors.unmark("panel")


if __name__ == "__main__":
    main()
