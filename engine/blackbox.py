"""The black box — the machine's vitals every few seconds, so a crash leaves its last seconds behind.

    py engine\\blackbox.py            record until stopped (bat\\blackbox.bat; the panel's tile)
    py engine\\blackbox.py --once     one line, printed
    py engine\\blackbox.py --last     the last lines recorded
    py engine\\blackbox.py --crashes  the machine's last hard stops (Windows' event log) with what the
                                      box recorded just before each

10-03 (the keeper: "my machine keeps crashing when she's doing stuff — build some logging system to find
the root of the issue"). A whole machine going down under a Python program is the card, the power, the
heat or the driver, not the program — and the console dies with it. So: one JSON line every
BLACKBOX_EVERY_S (5) into memory/blackbox/<day>.jsonl, flushed and fsynced, with the card's temperature,
power draw against its limit, memory used, utilization, clocks, fan and throttle reasons (nvidia-smi),
the processor's load and free memory, the disk, what Ollama holds and how much of it is on the card,
which doors are open, the sidecars up, and what each door is in the middle of (doing.py). After a crash,
--crashes reads Windows' event log for Kernel-Power 41 (power lost or a hard reset — no blue screen),
6008 (an unexpected shutdown) and BugCheck 1001 (a blue screen, with its code), and puts beside each the
last line the box wrote before it. Nothing of the friend's is in any line — names of tools, not words.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

ROOT = Path(config.ROOT)
FOLDER = Path(config.MEMORY_DIR) / "blackbox"
_WINDOWS = os.name == "nt"
_MAC = sys.platform == "darwin"
GPU_FIELDS = ("temperature.gpu", "power.draw", "power.limit", "memory.used", "memory.total", "utilization.gpu",
              "clocks.sm", "clocks.mem", "fan.speed", "pstate", "clocks_throttle_reasons.active")
_cpu_last: list = []


def every_s() -> float:
    try:
        return max(1.0, float(getattr(config, "BLACKBOX_EVERY_S", 5) or 5))
    except (TypeError, ValueError):
        return 5.0


def _out(argv: list[str], timeout: float = 4) -> str:
    kw = {"creationflags": 0x08000000} if _WINDOWS else {}  # no console window flashing
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kw).stdout


# ---- the card ----------------------------------------------------------------------------------------------
_THROTTLE = {0x1: "idle", 0x2: "app clocks", 0x4: "sw power cap", 0x8: "hw slowdown", 0x10: "sync boost",
             0x20: "sw thermal", 0x40: "hw thermal", 0x80: "hw power brake", 0x100: "display clocks"}


def throttle_words(mask) -> str:
    try:
        m = int(str(mask), 0)
    except (TypeError, ValueError):
        return ""
    return ", ".join(w for bit, w in _THROTTLE.items() if m & bit and bit != 0x1)


def gpu() -> dict | None:
    """The card by nvidia-smi: one dict, numbers where it gives them. None without a card or the tool."""
    try:
        out = _out(["nvidia-smi", f"--query-gpu={','.join(GPU_FIELDS)}", "--format=csv,noheader,nounits"])
    except Exception:  # noqa: BLE001
        return None
    line = (out.strip().splitlines() or [""])[0]
    if not line:
        return None
    vals = [v.strip() for v in line.split(",")]
    d: dict = {}
    for k, v in zip(GPU_FIELDS, vals):
        key = k.replace("clocks_throttle_reasons.active", "throttle").replace(".", "_")
        if key == "throttle":
            d["throttle"] = throttle_words(v)
            continue
        try:
            d[key] = float(v) if "." in v else int(v)
        except ValueError:
            d[key] = v  # "N/A", "P0"
    return d


# ---- the processor, the memory, the disk ---------------------------------------------------------------------
def _cpu_windows() -> float | None:
    import ctypes
    from ctypes import wintypes
    idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        return None
    def q(ft):
        return (ft.dwHighDateTime << 32) + ft.dwLowDateTime
    now = (q(idle), q(kern) + q(user))
    if _cpu_last:
        di, dt = now[0] - _cpu_last[0][0], now[1] - _cpu_last[0][1]
        _cpu_last[0] = now
        return round(100.0 * (1 - di / dt), 1) if dt > 0 else None
    _cpu_last.append(now)
    return None


def _cpu_linux() -> float | None:
    try:
        parts = open("/proc/stat").readline().split()[1:]
        nums = [int(x) for x in parts]
    except (OSError, ValueError):
        return None
    now = (nums[3] + (nums[4] if len(nums) > 4 else 0), sum(nums))
    if _cpu_last:
        di, dt = now[0] - _cpu_last[0][0], now[1] - _cpu_last[0][1]
        _cpu_last[0] = now
        return round(100.0 * (1 - di / dt), 1) if dt > 0 else None
    _cpu_last.append(now)
    return None


def cpu_percent() -> float | None:
    try:
        import psutil
        return float(psutil.cpu_percent(interval=None))
    except Exception:  # noqa: BLE001
        pass
    try:
        if _WINDOWS:
            return _cpu_windows()
        if not _MAC:
            return _cpu_linux()
        out = _out(["sh", "-c", "top -l 1 -n 0 | grep 'CPU usage'"])
        m = re.search(r"([\d.]+)% idle", out)
        return round(100 - float(m.group(1)), 1) if m else None
    except Exception:  # noqa: BLE001
        return None


def memory_gb() -> tuple[float | None, float | None]:
    """(free, total) in GB."""
    try:
        import psutil
        v = psutil.virtual_memory()
        return round(v.available / 1024 ** 3, 1), round(v.total / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        if _WINDOWS:
            import ctypes
            class S(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            s = S(); s.dwLength = ctypes.sizeof(S)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return round(s.ullAvailPhys / 1024 ** 3, 1), round(s.ullTotalPhys / 1024 ** 3, 1)
        if not _MAC:
            info = {}
            for ln in open("/proc/meminfo"):
                k, v = ln.split(":", 1)
                info[k] = int(v.split()[0])
            return round(info.get("MemAvailable", 0) / 1024 ** 2, 1), round(info.get("MemTotal", 0) / 1024 ** 2, 1)
        total = int(_out(["sysctl", "-n", "hw.memsize"]).strip())
        return None, round(total / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001
        return None, None


def disk_free_gb() -> float | None:
    try:
        import shutil
        return round(shutil.disk_usage(str(ROOT)).free / 1024 ** 3, 1)
    except OSError:
        return None


# ---- the house ------------------------------------------------------------------------------------------------
def ollama_loaded() -> list[dict] | None:
    import urllib.request
    try:
        with urllib.request.urlopen(config.OLLAMA_URL + "/api/ps", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    out = []
    for m in data.get("models", []):
        size = int(m.get("size") or 0); vram = int(m.get("size_vram") or 0)
        out.append({"name": m.get("name", ""), "gb": round(size / 1e9, 1), "on_card": int(100 * vram / size) if size else 0})
    return out


def sidecars() -> dict:
    import urllib.request
    out = {}
    for name, url in (("painter", getattr(config, "PAINTER_URL", "")), ("music_ear", getattr(config, "MUSIC_EARS_URL", ""))):
        if not url:
            continue
        try:
            with urllib.request.urlopen(url + "/health", timeout=0.5) as r:
                d = json.loads(r.read().decode("utf-8"))
            out[name] = "loaded" if d.get("loaded") else "up"
        except Exception:  # noqa: BLE001
            out[name] = "down"
    return out


def doors_open() -> dict:
    import doors
    try:
        return {d: (st.get("how") or "open") for d, st in doors.running().items()}
    except Exception:  # noqa: BLE001
        return {}


def doing_now() -> list[dict]:
    try:
        import doing
        return [{"door": d.get("door"), "what": d.get("what"), "since": d.get("since")} for d in doing.current()]
    except Exception:  # noqa: BLE001
        return []


# ---- one line, the file -------------------------------------------------------------------------------------
def sample() -> dict:
    """One record — with how long each reading took ("took"), so a slow one is seen (10-03: the first day's
    lines came 22 s apart, not 5; the timings say which reading drags)."""
    took: dict = {}
    t0 = time.perf_counter()

    def timed(name, fn):
        t = time.perf_counter()
        try:
            return fn()
        finally:
            took[name] = round(time.perf_counter() - t, 2)
    rec = {"t": datetime.now().isoformat(timespec="seconds")}
    rec["gpu"] = timed("gpu", gpu)
    rec["cpu"] = timed("cpu", cpu_percent)
    free, total = timed("ram", memory_gb)
    rec["ram_free_gb"], rec["ram_total_gb"] = free, total
    rec["disk_free_gb"] = timed("disk", disk_free_gb)
    rec["ollama"] = timed("ollama", ollama_loaded)
    rec["sidecars"] = timed("sidecars", sidecars)
    rec["doors"] = timed("doors", doors_open)
    rec["doing"] = timed("doing", doing_now)
    took["all"] = round(time.perf_counter() - t0, 2)
    rec["took"] = took
    return rec


def file_for(day: datetime | None = None) -> Path:
    return FOLDER / f"{(day or datetime.now()).strftime('%Y-%m-%d')}.jsonl"


def write(rec: dict) -> Path:
    """Appended, flushed and fsynced — the point of the box is that the line is on the disk when the
    power goes."""
    try:
        day = datetime.fromisoformat(str(rec.get("t", ""))[:19])
    except ValueError:
        day = None
    p = file_for(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    return p


def line(rec: dict) -> str:
    """One record as a line a person reads."""
    g = rec.get("gpu") or {}
    parts = [rec.get("t", "")]
    if g:
        parts.append(f"card {g.get('temperature_gpu', '?')}°C · {g.get('power_draw', '?')}/{g.get('power_limit', '?')} W · "
                     f"{g.get('memory_used', '?')}/{g.get('memory_total', '?')} MiB · {g.get('utilization_gpu', '?')}% · "
                     f"{g.get('clocks_sm', '?')} MHz · fan {g.get('fan_speed', '?')}%" + (f" · {g['throttle']}" if g.get("throttle") else ""))
    else:
        parts.append("card: no reading")
    parts.append(f"cpu {rec.get('cpu', '?')}% · ram free {rec.get('ram_free_gb', '?')}/{rec.get('ram_total_gb', '?')} GB · disk free {rec.get('disk_free_gb', '?')} GB")
    ol = rec.get("ollama")
    if ol is None:
        parts.append("ollama: not answering")
    elif ol:
        parts.append("ollama: " + ", ".join(f"{m['name']} {m['gb']} GB {m['on_card']}%" for m in ol))
    else:
        parts.append("ollama: nothing loaded")
    sc = rec.get("sidecars") or {}
    up = [f"{k} {v}" for k, v in sc.items() if v != "down"]
    if up:
        parts.append("sidecars: " + ", ".join(up))
    ds = rec.get("doors") or {}
    parts.append("doors: " + (", ".join(ds) if ds else "none"))
    dg = rec.get("doing") or []
    if dg:
        parts.append("doing: " + "; ".join(f"{d.get('door') or '?'} {d.get('what')} (since {str(d.get('since') or '')[11:19]})" for d in dg))
    return " · ".join(parts)


def last(n: int = 20) -> list[dict]:
    """The last n records, newest last, across the newest files."""
    out: list[dict] = []
    try:
        files = sorted(FOLDER.glob("*.jsonl"), reverse=True)
    except OSError:
        return out
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        recs = []
        for ln in lines:
            try:
                recs.append(json.loads(ln))
            except ValueError:
                continue  # a line cut by the crash itself
        out = recs[-n:] + out if not out else recs[-(n - len(out)):] + out
        if len(out) >= n:
            break
    return out[-n:]


# ---- the crashes --------------------------------------------------------------------------------------------
_EV_TIME = re.compile(r"Date:\s*(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")
_EV_ID = re.compile(r"Event ID:\s*(\d+)")
_EV_BUG = re.compile(r"bugcheck was:\s*(0x[0-9a-fA-F]+)")


def crashes(n: int = 5) -> list[dict]:
    """Windows' own record of the machine going down: Kernel-Power 41 (the power went, or the reset
    button — no blue screen), 6008 (an unexpected shutdown), BugCheck 1001 (a blue screen, with its code).
    [] elsewhere, or when the log can't be read."""
    if not _WINDOWS:
        return []
    try:
        out = _out(["wevtutil", "qe", "System", "/q:*[System[(EventID=41 or EventID=6008 or EventID=1001)]]",
                    f"/c:{n}", "/rd:true", "/f:text"], timeout=20)
    except Exception:  # noqa: BLE001
        return []
    found = []
    for block in re.split(r"\n(?=Event\[)", out):
        mid = _EV_ID.search(block)
        mt = _EV_TIME.search(block)
        if not mid or not mt:
            continue
        eid = int(mid.group(1))
        when = f"{mt.group(1)}T{mt.group(2)}"
        kind = {41: "power lost or a hard reset (no blue screen)", 6008: "an unexpected shutdown",
                1001: "a blue screen"}[eid]
        bug = _EV_BUG.search(block)
        found.append({"when": when, "event": eid, "kind": kind + (f", code {bug.group(1)}" if bug else "")})
    return found


def before(when: str, window_s: int = 120) -> dict | None:
    """The last record the box wrote before `when` (ISO), within window_s — what she was in the middle of."""
    try:
        t = datetime.fromisoformat(when[:19])
    except ValueError:
        return None
    best = None
    for day in (t, t - timedelta(days=1)):
        p = file_for(day)
        if not p.is_file():
            continue
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(ln)
                rt = datetime.fromisoformat(rec["t"])
            except (ValueError, KeyError):
                continue
            if rt <= t and (best is None or rt > datetime.fromisoformat(best["t"])):
                best = rec
    if best and (t - datetime.fromisoformat(best["t"])).total_seconds() <= window_s:
        return best
    return None


def crash_summary(n: int = 5) -> str:
    """For the report and the eye: each hard stop with the box's last line before it."""
    cs = crashes(n)
    if not cs:
        return "no hard stops in Windows' event log (or not Windows)" if _WINDOWS else "not Windows — no event log read"
    out = []
    for c in cs:
        rec = before(c["when"])
        out.append(f"{c['when']} — {c['kind']}")
        out.append("  the box's last line before it: " + (line(rec) if rec else "none within two minutes — the box wasn't running"))
    return "\n".join(out)


# ---- the loop -----------------------------------------------------------------------------------------------
def run() -> int:
    import doors
    refused = doors.claim("blackbox", "bat\\blackbox.bat")
    if refused:
        print(refused)
        return 1
    print(f"the black box — a line every {every_s():g} s into {FOLDER} (Ctrl+C or the panel's Stop to end)")
    cpu_percent()  # the first delta needs a first reading
    try:
        while True:
            if doors.stop_file("blackbox").exists():
                doors.stop_file("blackbox").unlink(missing_ok=True)
                print("(asked to stop — leaving)")
                return 0
            rec = sample()
            write(rec)
            print(line(rec)[:200] + (f"  (readings took {rec['took']['all']} s)" if rec["took"]["all"] > every_s() else ""))
            time.sleep(max(0.5, every_s() - rec["took"]["all"]))
    except KeyboardInterrupt:
        return 0


def main() -> int:
    args = sys.argv[1:]
    if "--once" in args:
        cpu_percent(); time.sleep(0.5)
        rec = sample(); print(line(rec)); print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 0
    if "--last" in args:
        for rec in last(30):
            print(line(rec))
        return 0
    if "--crashes" in args:
        print(crash_summary())
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
