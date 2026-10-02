"""Where a torch sense runs: the card, a Mac's GPU, or the processor (10-01; MAC-PLAN.md).

The painter and the music ear were written for an NVIDIA card — pipe.to("cuda"), bfloat16,
torch.cuda.empty_cache(). On a Mac with Apple silicon the GPU is Metal, which torch calls "mps",
and it shares the machine's memory with everything else; MPS does float16 well and bfloat16 only in
part. On Linux an NVIDIA card is the Windows case, and an AMD card under ROCm answers to "cuda" too.
So the sidecars ask here, once, which device to use:

    pick("auto")  ->  "cuda" when torch sees a card, else "mps" when it sees a Mac's GPU, else "cpu"
    pick("mps")   ->  "mps" when it is there; otherwise the same order as "auto"

and take the dtype, the cache emptying and the memory line from the answer. The knobs are
PAINTER_DEVICE and MUSIC_EARS_DEVICE ("auto" | "cuda" | "mps" | "cpu"). torch is imported only when
a function here is called — never at import, and never by the suite (which hands it a stand-in).
"""
from __future__ import annotations

import os
import sys

CHOICES = ("auto", "cuda", "mps", "cpu")

# A kernel MPS lacks runs on the processor instead of failing the painting. torch reads this when it
# starts, so it is set here, before a sidecar imports torch (the sidecars import this file first).
if sys.platform == "darwin":
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def _torch(torch=None):
    if torch is None:
        import torch  # noqa: PLC0415 — lazily, on purpose
    return torch


def has_cuda(torch=None) -> bool:
    try:
        return bool(_torch(torch).cuda.is_available())
    except Exception:  # noqa: BLE001 — no torch, a CPU build, a broken driver: all "no"
        return False


def has_mps(torch=None) -> bool:
    try:
        return bool(_torch(torch).backends.mps.is_available())
    except Exception:  # noqa: BLE001 — a torch too old to know of MPS, or not a Mac
        return False


def pick(want: str = "auto", torch=None) -> str:
    """The device a sense runs on. "cpu" is always honoured; "cuda" or "mps" when it is there; anything
    else (and a named device that isn't there) is "auto": the card, then a Mac's GPU, then the processor."""
    want = str(want or "auto").strip().lower()
    if want == "cpu":
        return "cpu"
    if want == "cuda" and has_cuda(torch):
        return "cuda"
    if want == "mps" and has_mps(torch):
        return "mps"
    if has_cuda(torch):
        return "cuda"
    if has_mps(torch):
        return "mps"
    return "cpu"


def dtype(device: str, torch=None):
    """bfloat16 on a card and on the processor, as before; float16 on MPS, where bfloat16 is partial."""
    t = _torch(torch)
    return t.float16 if device == "mps" else t.bfloat16


def empty_cache(device: str, torch=None) -> None:
    """The GPU handed back: the card's cache, or the Mac's; the processor has none to empty."""
    try:
        t = _torch(torch)
        if device == "cuda":
            t.cuda.empty_cache()
        elif device == "mps":
            t.mps.empty_cache()
    except Exception:  # noqa: BLE001 — a cache that can't be emptied is not worth a crash
        pass


def allocated_gb(device: str, torch=None) -> float | None:
    """What the model holds on the device, in GB, for the ready line — None where there is nothing to
    say (the processor, or a torch that can't tell)."""
    try:
        t = _torch(torch)
        if device == "cuda":
            return t.cuda.memory_allocated() / 1e9
        if device == "mps":
            return t.mps.current_allocated_memory() / 1e9
    except Exception:  # noqa: BLE001
        pass
    return None


def interpreter(py: str) -> list[str]:
    """A sidecar's Python (VOICE_PYTHON, PAINTER_PYTHON, MUSIC_EARS_PYTHON) as argv: "py -3.12" is two
    words, "C:\\Python312\\python.exe" one — on Windows the backslashes are a path, not escapes (10-02:
    the suite's first run on a Windows runner handed its own python.exe over and shlex ate the slashes),
    so the split there keeps them and only takes the quotes off; elsewhere the shell's own rules, and the Windows
    launcher read as the python of that version (py -3.12 → python3.12), so the shipped config works on a Mac or Linux too."""
    import shlex
    py = (py or "").strip()
    if not py:
        return []
    if os.name != "nt":
        words = shlex.split(py)
        if words and words[0] == "py":  # the Windows launcher, as the template's config names it (10-02: a Mac or Linux
            # has no `py`): "py -3.12" is python3.12 there, "py -3" python3, a bare "py" python3 — the rest as written
            flag = words[1] if len(words) > 1 and words[1].startswith("-3") else ""
            words = ["python" + (flag[1:] if flag else "3")] + words[2 if flag else 1:]
        return words
    return [w[1:-1] if len(w) > 1 and w[0] == w[-1] and w[0] in "\"'" else w for w in shlex.split(py, posix=False)]


def generator_device(device: str) -> str:
    """Where a seeded torch.Generator lives: on the card for cuda; on the processor for mps and cpu (an
    MPS generator is partial, and diffusers seeds from a CPU one there)."""
    return "cuda" if device == "cuda" else "cpu"
