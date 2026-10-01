"""The doors' own marks — which of them is open, and a polite way to close two (09-30; PANEL-PLAN.md).

The keeper: "a main interface with buttons for chat, parlor, wake, the telegram bridge, a heartbeat
button…". A button needs a light beside it, and a light needs to know. So each door — the heartbeat,
the bridge, the parlor, a chat — writes memory/.pids/<door>.json when it starts

    {"pid": 4812, "when": "2026-09-30T21:14:03", "how": "loop 120", "argv": [...]}

and takes it away when it leaves. A door that died without leaving (the window's X, a power cut)
leaves its file behind: status() finds the pid gone, clears the file and says the door is closed.

One heartbeat, one bridge and one parlor at a time — a second heartbeat would wake them twice over and
share the card, a second bridge would answer every message twice, a second parlor finds its port taken.
claim() refuses a second one with a line naming the first one's pid. Two chats are fine.

The heartbeat and the bridge can also be asked to leave: memory/.stop-heartbeat, memory/.stop-bridge.
The loop looks for its file between beats (the bridge between polls), takes it away and leaves after
the wake it is in — a stop that never cuts a wake, or a visit's save, in half. ask_stop() writes the
file; stop_asked() is the loop's look (it clears what it finds).

Standard library only, no knob. On Windows os.kill(pid, 0) would TERMINATE the process, so a pid is
asked after through the kernel (ctypes), and through tasklist if that fails.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

DOORS = ("heartbeat", "wake", "bridge", "parlor", "chat", "panel")  # "wake" is a one-off wake (bat\wake.bat) — it runs beside a loop, as it always did
ONE_AT_A_TIME = ("heartbeat", "bridge", "parlor", "panel")

# why a second one is refused, said in the refusal
_WHY = {
    "heartbeat": "two heartbeats would wake them twice over and share the card",
    "bridge": "two bridges would answer every message twice",
    "parlor": "two parlors can't share the port",
    "panel": "two panels can't share the port",
}
# what to do instead, said in the refusal
_INSTEAD = {
    "heartbeat": "to stop that one: Ctrl+C in its window, or a file named .stop-heartbeat in memory/ "
                 "(it leaves after the wake it is in)",
    "bridge": "to stop that one: Ctrl+C in its window, or a file named .stop-bridge in memory/ "
              "(it saves the visit and leaves)",
    "parlor": "its page is http://127.0.0.1:8765 — open that one, or Ctrl+C in its window to close it",
    "panel": "its page is http://127.0.0.1:8764 — open that one, or Ctrl+C in its window to close it",
}

_marked: set[str] = set()  # the doors this process has registered its atexit for


def _memory() -> Path:
    return Path(config.MEMORY_DIR)


def pid_file(door: str) -> Path:
    return _memory() / ".pids" / f"{door}.json"


def stop_file(door: str) -> Path:
    return _memory() / f".stop-{door}"


# ---- is it alive ---------------------------------------------------------------

def _alive_windows(pid: int) -> bool:
    """The kernel's word for a pid: a process still running (STILL_ACTIVE) whose image is a Python — a
    pid Windows gave to something else since is not ours. tasklist when ctypes is not to be had."""
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: there, only not ours to open
        try:
            code = wintypes.DWORD()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
                return False
            buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return "py" in Path(buf.value).name.lower()  # python.exe, pythonw.exe
            return True
        finally:
            k.CloseHandle(h)
    except Exception:  # noqa: BLE001 — no ctypes, an older Windows: ask tasklist
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
        except Exception:  # noqa: BLE001
            return False
        return str(pid) in out and "py" in out.lower()


def alive(pid) -> bool:
    """Is a process with this pid running? (Our own pid counts — it is.)"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # there, only someone else's to signal
    except OSError:
        return False
    return True


# ---- the marks -------------------------------------------------------------------

def mark(door: str, how: str = "", **extra) -> dict:
    """This process is the door: its file written (whole, then moved into place, so a reader never
    sees half of one), and taken away again when the process leaves. Extra keys (the panel's port)
    ride in the record for whoever reads it."""
    rec = {"pid": os.getpid(), "when": datetime.now().isoformat(timespec="seconds"), "how": how,
           "argv": list(sys.argv), **extra}
    p = pid_file(door)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        return rec  # a mark that can't be written costs the panel a light, never the door its start
    if door not in _marked:
        _marked.add(door)
        atexit.register(unmark, door)
    return rec


def _read(p: Path) -> dict | None:
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def _remove(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def unmark(door: str) -> None:
    """The door's file taken away — only when it is this process's (a second chat's is its own)."""
    p = pid_file(door)
    rec = _read(p)
    if rec is not None and rec.get("pid") == os.getpid():
        _remove(p)


def status(door: str) -> dict | None:
    """The door's file with "alive": True, or None when it is closed. A file whose pid is gone — or
    that can't be read — is stale: it is cleared here."""
    p = pid_file(door)
    if not p.is_file():
        return None
    rec = _read(p)
    if rec is None or not alive(rec.get("pid")):
        _remove(p)
        return None
    return dict(rec, alive=True)


def running() -> dict[str, dict]:
    """{door: its status} for every door that is open."""
    return {door: st for door in DOORS if (st := status(door))}


def claim(door: str, how: str = "") -> str:
    """At a door's start: "" and the door marked as this process — or, for a door that runs one at a
    time and is already open, the line that says so (and nothing marked)."""
    if door in ONE_AT_A_TIME:
        st = status(door)
        if st:
            since = str(st.get("when", "")).replace("T", " ")[:16]
            how_run = f", {st['how']}" if st.get("how") else ""
            return (f"(the {door} is already running — pid {st.get('pid')}{how_run}, since {since or '?'}; "
                    f"{_WHY[door]}; {_INSTEAD[door]})")
    mark(door, how)
    return ""


# ---- the stop files ----------------------------------------------------------------

def ask_stop(door: str) -> Path:
    """Ask a running loop to leave after what it is doing (the panel's Stop; a keeper can make the
    file by hand)."""
    p = stop_file(door)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(datetime.now().isoformat(timespec="seconds") + "\n", encoding="utf-8")
    return p


def stop_asked(door: str) -> bool:
    """The loop's look: True when a stop was asked — the file is taken away with the look."""
    p = stop_file(door)
    if not p.exists():
        return False
    _remove(p)
    return True
