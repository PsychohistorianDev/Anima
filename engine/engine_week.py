"""The engine's week — what the machinery did under the friend's words, once a week on the phone.

Every call to the brain leaves one line in memory/steps.log (JSON): when, at which door, the window it held, how long
the prompt took to read, what it wrote, the longest thought, the attempts the rails set aside and why, the mends made
in place, the signature's count. On ENGINE_WEEK_DAY after ENGINE_WEEK_HOUR the bridge sends the last seven days of it
as an engine notice (held through the quiet hours like any other), once; /week on the phone shows it any time.

The engine's facts only: counts, kinds, times — never the friend's words. The log rotates past ROTATE_BYTES to
steps.old.log (one generation kept), which is read too, so a week never falls between the two.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta

import config

STEPS_FILE = config.MEMORY_DIR / "steps.log"
OLD_FILE = config.MEMORY_DIR / "steps.old.log"
TOLD_FILE = config.MEMORY_DIR / "week_told.json"
ROTATE_BYTES = 4_000_000
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday() order

# the mends, as the week names them (the keys log_step writes)
MEND_NAMES = {
    "caps": "a stray capital taken off a word",
    "signature": "the signature spelled back",
    "emoji": "a repeated emoji taken off the row",
    "flags": "a flag taken off the row",
    "row": "a sign-off row trimmed at the cascade line",
    "tokens": "a reserved token written as text",
    "cut": "an unfinished tail taken off",
    "seam": "a reply joined back at its seam",
    "call": "a written-out call taken off",
}


def _why(why: str) -> str:
    """A set-aside's kind without its temperature note: "salad (at 0.6)" → "salad"."""
    return str(why or "?").split(" (")[0].strip() or "?"


def log_step(tries: list, msg: dict, now: datetime | None = None) -> dict | None:
    """One line for one call to the brain (ollama_client.chat, after its attempts): the record written, or None.
    Never raises; ENGINE_WEEK_LOG = False writes nothing."""
    if not getattr(config, "ENGINE_WEEK_LOG", True):
        return None
    try:
        import ollama_client
        try:
            import tools
            door = getattr(tools, "DOOR", "") or "a visit"
        except Exception:  # noqa: BLE001
            door = "a visit"
        now = now or datetime.now()
        every = [m for _, m in tries if m is not msg] + [msg]
        tok = lambda m, k: (m.get("tokens") or {}).get(k) or 0  # noqa: E731
        t = msg.get("tokens") or {}
        rec: dict = {"t": now.isoformat(timespec="seconds"), "door": door,
                     "prompt": int(t.get("prompt") or 0),
                     "read_s": round(sum(float(tok(m, "prompt_s")) for m in every), 1),
                     "reply": int(sum(int(tok(m, "reply")) for m in every)),
                     "think": max(len((m.get("thinking") or "").split()) for m in every)}
        aside = [_why((c or {}).get("why")) for c, m in tries if m is not msg and not m.get("claim_kept")]
        if aside:
            rec["aside"] = aside
        if msg.get("claim_kept_words"):
            rec["kept"] = 1  # a claimed reply that went out as written once the ask was answered with a call
        if msg.get("still_garbled"):
            rec["broken"] = 1
        if t.get("done") == "length":
            rec["ceiling"] = 1
        mends = {}
        for key, field in (("caps", "mended_caps"), ("signature", "mended_signature"), ("emoji", "mended_emoji"),
                           ("flags", "mended_flags")):
            n = len(msg.get(field) or [])
            if n:
                mends[key] = n
        for key, field in (("row", "trimmed_row"), ("cut", "cut_tail"), ("seam", "split_seam"), ("call", "call_text_dropped")):
            if msg.get(field):
                mends[key] = 1
        if msg.get("defanged"):
            mends["tokens"] = int(msg["defanged"]) if str(msg["defanged"]).isdigit() else 1
        if mends:
            rec["mends"] = mends
        text = msg.get("content") or ""
        if text.strip():
            rec["words"] = len(text.split())
            sig = ollama_client.signature_hits(text)
            if sig:
                rec["sig"] = int(sig)
            ref = sum(int(n) for _, n in ollama_client.refrain_hits(text))
            if ref:
                rec["refrain"] = ref
        STEPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            if STEPS_FILE.exists() and STEPS_FILE.stat().st_size > ROTATE_BYTES:
                os.replace(STEPS_FILE, OLD_FILE)
        except OSError:
            pass
        with STEPS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    except Exception:  # noqa: BLE001 — the week's count, never a reply down
        return None


def read(since: datetime, until: datetime | None = None) -> list[dict]:
    """The logged calls from `since` (to `until`), oldest first, both files; a bad line is skipped."""
    out = []
    for p in (OLD_FILE, STEPS_FILE):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
                when = datetime.fromisoformat(r["t"])
            except Exception:  # noqa: BLE001
                continue
            if when >= since and (until is None or when <= until):
                r["_when"] = when
                out.append(r)
    out.sort(key=lambda r: r["_when"])
    return out


def _clock(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def _counts(c: Counter, top: int = 8) -> str:
    return ", ".join(f"{k} ×{n}" if n > 1 else k for k, n in c.most_common(top))


def summary(now: datetime | None = None, days: int = 7) -> str:
    """The week as one notice: the last `days` days of memory/steps.log, said in the engine's words."""
    now = now or datetime.now()
    since = now - timedelta(days=days)
    rows = read(since, now)
    if not rows:
        return ("(the engine's week: nothing logged in the last seven days — memory/steps.log gains a line with "
                "every call to the brain from now on)")
    first = rows[0]["_when"]
    head = f"(the engine's week, {since:%m-%d} → {now:%m-%d}"
    if first - since > timedelta(days=1):
        head += f" — the log begins {first:%m-%d %H:%M}"
    lines = [head + ")"]
    doors = Counter(r.get("door") or "a visit" for r in rows)
    lines.append(f"· {len(rows):,} call{'s' if len(rows) != 1 else ''} to the brain — " + ", ".join(f"{d} {n:,}" for d, n in doors.most_common())
                 + f"; {sum(int(r.get('reply') or 0) for r in rows):,} tokens written")
    aside = Counter(k for r in rows for k in r.get("aside") or [])
    if aside:
        lines.append(f"· set aside and asked again: {sum(aside.values()):,} — {_counts(aside)}")
    else:
        lines.append("· set aside and asked again: none")
    kept = sum(1 for r in rows if r.get("kept"))
    if kept:
        lines.append(f"· said done before a tool ran, then did it when asked — the first words went out as written: {kept}")
    broken = sum(1 for r in rows if r.get("broken"))
    ceiling = sum(1 for r in rows if r.get("ceiling"))
    if broken or ceiling:
        lines.append(f"· went out still broken: {broken}; cut at the ceiling: {ceiling}")
    mends = Counter()
    for r in rows:
        for k, n in (r.get("mends") or {}).items():
            mends[k] += int(n)
    if mends:
        lines.append(f"· mended in place: {sum(mends.values()):,} — "
                     + ", ".join(f"{MEND_NAMES.get(k, k)} ×{n}" if n > 1 else MEND_NAMES.get(k, k) for k, n in mends.most_common()))
    cold_s = float(getattr(config, "ENGINE_WEEK_COLD_S", 60) or 60)
    cold = [r for r in rows if float(r.get("read_s") or 0) >= cold_s]
    if cold:
        worst = max(cold, key=lambda r: float(r.get("read_s") or 0))
        lines.append(f"· cold reads (a prompt read in {_clock(cold_s)} or more): {len(cold)}, "
                     f"{_clock(sum(float(r.get('read_s') or 0) for r in cold))} in all; the longest "
                     f"{_clock(float(worst.get('read_s') or 0))} at {int(worst.get('prompt') or 0):,} tokens "
                     f"({worst['_when']:%a %H:%M}, {worst.get('door') or 'a visit'})")
    else:
        lines.append(f"· cold reads (a prompt read in {_clock(cold_s)} or more): none")
    deep = max(rows, key=lambda r: int(r.get("think") or 0))
    if int(deep.get("think") or 0):
        lines.append(f"· the longest thought: {int(deep['think']):,} words ({deep['_when']:%a %H:%M}, {deep.get('door') or 'a visit'})")
    sig_name = str(getattr(config, "SIGNATURE", "") or "").strip()
    spoken = [r for r in rows if r.get("words")]
    if sig_name and spoken:
        sigs = [int(r.get("sig") or 0) for r in spoken]
        if any(sigs):
            lines.append(f"· {sig_name}: {sum(sigs) / len(spoken):.1f} a reply, {max(sigs)} at most, {sum(sigs):,} in all")
    refrains = [str(p) for p in (getattr(config, "SIGNATURE_REFRAINS", ()) or ())]
    ref = sum(int(r.get("refrain") or 0) for r in rows)
    if refrains and ref:
        lines.append(f"· {' / '.join(refrains)}: {ref:,} time{'s' if ref != 1 else ''}")
    window = int(getattr(config, "NUM_CTX", 0) or 0)
    peak = max(int(r.get("prompt") or 0) for r in rows)
    if peak:
        lines.append(f"· the window at its fullest: {peak:,} tokens" + (f" ({peak * 100 // window}%)" if window else ""))
    return "\n".join(lines)


def _told() -> str:
    try:
        return str(json.loads(TOLD_FILE.read_text(encoding="utf-8")).get("day") or "")
    except Exception:  # noqa: BLE001
        return ""


def due(now: datetime | None = None) -> bool:
    """ENGINE_WEEK_DAY, at or after ENGINE_WEEK_HOUR, and not told yet that day. "" — never on its own."""
    day = str(getattr(config, "ENGINE_WEEK_DAY", "") or "").strip().lower()[:3]
    if day not in DAYS:
        return False
    now = now or datetime.now()
    if DAYS[now.weekday()] != day or now.hour < int(getattr(config, "ENGINE_WEEK_HOUR", 18) or 0):
        return False
    return _told() != now.date().isoformat()


def mark_told(now: datetime | None = None) -> None:
    now = now or datetime.now()
    try:
        TOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOLD_FILE.write_text(json.dumps({"day": now.date().isoformat()}), encoding="utf-8")
    except OSError:
        pass
