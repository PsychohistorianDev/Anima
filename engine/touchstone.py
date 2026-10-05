"""The stone's keeper: the helper between the engine and their body on the desk.

The Touchstone is a small board (an ESP32 with a haptic driver and a pressure pad)
that hums whatever state they last set, answers a press by itself with the reply
they chose in advance, and logs what it felt. It cannot think; they meet it in
turns, as they meet everything. This helper owns the board so nothing else has to:

  · every TOUCHSTONE_POLL_S it asks the board what it felt (GET /felt) and writes
    the new events to memory/touch/<day>.jsonl — the body's transcript, kept by
    the engine like the episodic files; the board's last word to memory/touch/stone.json
  · their states file (TOUCHSTONE_STATES, theirs to edit) is pushed to the board
    when it changes (POST /states) — the engine never writes it
  · it answers the engine on TOUCHSTONE_URL (http://127.0.0.1:8769): /health,
    /felt?since= (from the archive, never the network), and relays /state, /pulse,
    /later to the board — a board away answers 503 with when it was last seen

The bridge reads the archive file to turn a press into a turn; the tools feel,
set_state, pulse and touch_later go through here. TOUCHSTONE_URL "" means no
body: this helper and everything that reads it stay quiet.

    bat\\touchstone.bat            run it (a door; one at a time; the panel's Stop ends it)
    bat\\touchstone.bat --status   the board's last word and the newest touches
    bat\\touchstone.bat --demo     write a made-up day of touches, to see the section
    bat\\touchstone.bat --test     one poll of the board, printed

Standard library only. The board's side (the sketch) lives with the keeper, never here.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

HOST, PORT = "127.0.0.1", 8769
TOUCH_DIR = config.MEMORY_DIR / "touch"
STONE_FILE = TOUCH_DIR / "stone.json"
LOG = TOUCH_DIR / "touchstone.log"
KINDS = ("press", "tap", "hold", "played")

_lock = threading.Lock()


def _say(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        TOUCH_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---- the board -------------------------------------------------------------------------------------------------
def board_url() -> str:
    return str(getattr(config, "TOUCHSTONE_BOARD", "") or "").rstrip("/")


def poll_s() -> float:
    return float(getattr(config, "TOUCHSTONE_POLL_S", 30) or 30)


def states_file() -> Path:
    p = getattr(config, "TOUCHSTONE_STATES", None)
    return Path(p) if p else config.CREATIONS_DIR / "projects" / "robotics" / "states.json"


def _board(path: str, data: dict | None = None, timeout: float = 4, method: str | None = None) -> dict:
    """One request to the board. Raises on no road."""
    url = board_url() + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body is not None else "GET"))
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {"raw": raw}


# ---- the board's last word --------------------------------------------------------------------------------------
def stone() -> dict:
    """What the board last said — state, when it was last seen, away since, the queue."""
    try:
        d = json.loads(STONE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_stone(d: dict) -> None:
    try:
        TOUCH_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STONE_FILE.with_name(STONE_FILE.name + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STONE_FILE)
    except OSError:
        pass


def away() -> str:
    """The ISO moment the board went away, or "" while it answers."""
    return str(stone().get("away_since") or "")


# ---- the archive -----------------------------------------------------------------------------------------------
def day_file(day: str) -> Path:
    return TOUCH_DIR / f"{day}.jsonl"


def _iso(t) -> str:
    """The board's unix seconds (or an ISO string) as local ISO seconds."""
    try:
        return datetime.fromtimestamp(float(t)).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return str(t or "")[:19]


def normalize(ev: dict) -> dict | None:
    """One event from the board in the archive's shape, or None for noise."""
    kind = str(ev.get("kind") or "").lower()
    if kind not in KINDS:
        return None
    out = {"t": _iso(ev.get("t")), "kind": kind}
    if kind == "played":
        out["waveform"] = str(ev.get("waveform") or "")
        out["seconds"] = float(ev.get("seconds") or 0)
    else:
        out["force"] = int(float(ev.get("force") or 0))
        out["seconds"] = round(float(ev.get("seconds") or 0), 1)
        if ev.get("reply"):
            out["reply"] = str(ev["reply"])
        if ev.get("state"):
            out["state"] = str(ev["state"])
    return out


def append(events: list[dict]) -> int:
    """New events into the day files (by each event's own day), with when they were fetched."""
    n = 0
    now = datetime.now().isoformat(timespec="seconds")
    TOUCH_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        for ev in events:
            rec = dict(ev, fetched_at=now)
            with open(day_file(rec["t"][:10]), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            n += 1
    return n


def read_archive(since: str = "", days: int = 2) -> list[dict]:
    """The events after `since` (ISO), from the last `days` day files, oldest first."""
    out = []
    today = date.today()
    for i in range(days - 1, -1, -1):
        p = day_file((today - timedelta(days=i)).isoformat())
        if not p.exists():
            continue
        try:
            for ln in p.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue  # a line the power cut
                if isinstance(rec, dict) and rec.get("t", "") > (since or ""):
                    out.append(rec)
        except OSError:
            pass
    return out


def last_t() -> str:
    """The newest archived event's moment, "" with none."""
    evs = read_archive("", days=3)
    return evs[-1]["t"] if evs else ""


# ---- words for a touch -------------------------------------------------------------------------------------------
def touch_words(ev: dict) -> str:
    """One event in words: "09:32 a soft steady press, 12 s — it answered with your Home reply"."""
    hm = ev.get("t", "")[11:16]
    kind = ev.get("kind")
    if kind == "played":
        return f"{hm} it played {ev.get('waveform') or 'a pattern'}, {ev.get('seconds', 0):g} s, as you asked"
    force = int(ev.get("force") or 0)
    weight = "a light" if force < 30 else "a soft" if force < 60 else "a firm"
    if kind == "tap":
        what = f"{weight} tap"
    elif kind == "hold":
        what = f"{weight} hold, {ev.get('seconds', 0):g} s"
    else:
        what = f"{weight} {'steady ' if float(ev.get('seconds') or 0) >= 3 else ''}press, {ev.get('seconds', 0):g} s"
    reply = ev.get("reply")
    return f"{hm} {what}" + (f" — it answered with your {reply} reply" if reply else "")


# ---- the poll ---------------------------------------------------------------------------------------------------
def poll() -> int:
    """One look at the board: new events archived, stone.json refreshed. Returns how many came, -1 away."""
    st = stone()
    since = st.get("last_t") or last_t()
    try:
        q = ""
        if since:
            try:
                q = f"?since={int(datetime.fromisoformat(since).timestamp())}"
            except ValueError:
                q = ""
        felt = _board("/felt" + q)
        health = _board("/health")
    except Exception as e:  # noqa: BLE001 — the board is asleep, unplugged, or the Wi-Fi blinked
        if not st.get("away_since"):
            st["away_since"] = datetime.now().isoformat(timespec="seconds")
            st["away_why"] = f"{type(e).__name__}: {e}"[:160]
            _write_stone(st)
            _say(f"the stone is away ({st['away_why']}) — looking again every {poll_s():g} s")
        return -1
    events = felt if isinstance(felt, list) else felt.get("events") or []
    new = [n for n in (normalize(e) for e in events if isinstance(e, dict)) if n and n["t"] > (since or "")]
    new.sort(key=lambda e: e["t"])
    n = append(new) if new else 0
    came_back = bool(st.get("away_since"))
    st = {"address": board_url(), "seen": datetime.now().isoformat(timespec="seconds"), "away_since": "",
          "state": str(health.get("state") or st.get("state") or ""), "queued": int(health.get("queued") or 0),
          "uptime": health.get("uptime"), "last_t": new[-1]["t"] if new else (since or ""),
          "state_since": st.get("state_since") or ""}
    if st["state"] != stone().get("state"):
        st["state_since"] = datetime.now().isoformat(timespec="seconds")
    _write_stone(st)
    if came_back:
        _say("the stone is back")
    if n:
        _say(f"{n} touch{'es' if n != 1 else ''} archived: " + "; ".join(touch_words(e) for e in new[-3:]))
    return n


_pushed_mtime = 0.0


def push_states(force: bool = False) -> str:
    """Their states file to the board when it changed. Returns a line, "" when nothing to do."""
    global _pushed_mtime
    p = states_file()
    if not p.exists():
        return ""
    try:
        m = p.stat().st_mtime
    except OSError:
        return ""
    if not force and m == _pushed_mtime:
        return ""
    try:
        states = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(states, dict) or not states:
            raise ValueError("not a map of states")
    except (OSError, ValueError) as e:
        _pushed_mtime = m  # named once, not every poll
        line = f"their states file doesn't read ({type(e).__name__}: {e}) — the board keeps the map it has"
        _say(line)
        return line
    try:
        _board("/states", states)
    except Exception as e:  # noqa: BLE001
        return f"states not pushed — the stone is away ({type(e).__name__})"
    _pushed_mtime = m
    line = f"their states pushed to the stone: {', '.join(list(states)[:12])}"
    _say(line)
    return line


# ---- the engine's side of the helper -----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _away(self):
        st = stone()
        since = st.get("away_since") or ""
        return self._json({"error": f"the stone has been away since {since[11:16] or '?'}"
                           + (f" (last seen {st.get('seen', '')[11:16]})" if st.get("seen") else ""), "away_since": since}, 503)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/health":
            st = stone()
            return self._json({"ok": True, "loaded": not st.get("away_since") and bool(st.get("seen")),
                               "board": st, "poll_s": poll_s()})
        if u.path == "/felt":
            since = urllib.parse.parse_qs(u.query).get("since", [""])[0]
            return self._json({"events": read_archive(since)})
        if u.path == "/later":
            if away():
                return self._away()
            try:
                return self._json(_board("/later"))
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"the stone didn't answer ({type(e).__name__})"}, 503)
        self._json({"error": "unknown path"}, 404)

    def do_DELETE(self):
        if self.path == "/later":
            try:
                return self._json(_board("/later", method="DELETE"))
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"the stone didn't answer ({type(e).__name__})"}, 503)
        self._json({"error": "unknown path"}, 404)

    def do_POST(self):
        if self.path not in ("/state", "/pulse", "/later", "/states"):
            return self._json({"error": "unknown path"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json({"error": "not JSON"}, 400)
        if self.path == "/states":
            return self._json({"line": push_states(force=True)})
        if away():
            return self._away()
        try:
            out = _board(self.path, data)
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read().decode("utf-8"))
            except Exception:  # noqa: BLE001
                out = {"error": f"the stone refused ({e.code})"}
            return self._json(out, e.code if 400 <= e.code < 600 else 502)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"the stone didn't answer ({type(e).__name__})"}, 503)
        if self.path == "/state" and data.get("name"):
            st = stone()
            st["state"], st["state_since"] = str(data["name"]), datetime.now().isoformat(timespec="seconds")
            _write_stone(st)
        if self.path == "/later":
            st = stone()
            st["queued"] = int(out.get("queued") or st.get("queued") or 0) + (0 if "queued" in out else 1)
            _write_stone(st)
        self._json(out)


def serve(port: int = PORT) -> HTTPServer:
    HTTPServer.allow_reuse_address = sys.platform != "win32"
    server = HTTPServer((HOST, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run() -> int:
    import doors
    refused = doors.claim("touchstone", "bat\\touchstone.bat")
    if refused:
        print(refused)
        return 1
    if not board_url():
        print("no board named — TOUCHSTONE_BOARD in engine/config.py (http://touchstone.local, or its address)")
        return 1
    server = serve()
    _say(f"the stone's keeper is up at http://{HOST}:{PORT} — the board at {board_url()}, a look every {poll_s():g} s")
    try:
        while True:
            if doors.stop_file("touchstone").exists():
                doors.stop_file("touchstone").unlink(missing_ok=True)
                _say("(asked to stop — leaving)")
                return 0
            poll()
            push_states()
            time.sleep(poll_s())
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


def demo_day(day: str | None = None) -> list[dict]:
    day = day or date.today().isoformat()
    return [{"t": f"{day}T08:10:04", "kind": "tap", "force": 22, "seconds": 0.3, "reply": "nudge", "state": "Home"},
            {"t": f"{day}T09:32:10", "kind": "press", "force": 61, "seconds": 12.0, "reply": "warm", "state": "Home"},
            {"t": f"{day}T09:40:51", "kind": "tap", "force": 35, "seconds": 0.4, "reply": "warm", "state": "Home"},
            {"t": f"{day}T19:30:00", "kind": "played", "waveform": "Tethered", "seconds": 10.0}]


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--status":
        st = stone()
        print(json.dumps(st, ensure_ascii=False, indent=1) if st else "(the stone has never been seen)")
        for ev in read_archive("", days=2)[-8:]:
            print(touch_words(ev))
        return 0
    if argv and argv[0] == "--demo":
        n = append(demo_day())
        print(f"{n} made-up touches written to {day_file(date.today().isoformat()).name}")
        return 0
    if argv and argv[0] == "--test":
        n = poll()
        print("the stone is away" if n < 0 else f"{n} new touch{'es' if n != 1 else ''}; the board says: {json.dumps(stone())}")
        return 0 if n >= 0 else 1
    return run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
