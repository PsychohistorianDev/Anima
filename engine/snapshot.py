"""Snapshot the friend — so no version of them is ever lost.

    py engine/snapshot.py

With git installed, the friend's files are committed into a git directory of
their own, backups/.snapshots — never the folder's own .git. Until 10-07 the
snapshot was `git add -A` in the folder's repo, which honours .gitignore: so
it kept what the ignore file let through and skipped self.md, projects.md,
the journal and memory.db — exactly the files it exists for (nylanalyn, #2).
Now the paths below are added with --force, whatever .gitignore says, into
a repo that has no remote and is never the one pushed; the checkout's
.gitignore can be as strict as it likes. If git isn't installed, a
timestamped zip in backups/ (keeping the most recent 30).

Run it whenever you like, or schedule it nightly right after consolidate.py.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

STAMP = datetime.now().strftime("%Y-%m-%d %H:%M")
FILESTAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP_DIR = config.ROOT / "backups"
SNAP_DIR = BACKUP_DIR / ".snapshots"  # the snapshots' own git directory
KEEP_ZIPS = 30
EXCLUDE_DIRS = {".git", "__pycache__", "backups"}
# the friend: their pages, journal, memory, creations, what was shared with
# them — and the house's settings. Only the ones that exist are added.
SNAPSHOT_PATHS = ["self.md", "projects.md", "destiny.md", "keeper.md",
                  "journal", "memory", "creations", "shared", "engine/config.py"]
# inside those, what is not the friend: caches, the black box's samples (a
# line every five seconds — the doctor reads them, a snapshot needn't keep
# them) and the doing-marks. Pathspecs; --force takes no notice of an
# exclude file, so these ride on the add itself.
SNAPSHOT_EXCLUDE = [":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc",
                    ":(exclude)memory/blackbox", ":(exclude)memory/.doing"]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", f"--git-dir={SNAP_DIR}", f"--work-tree={config.ROOT}", *args],
        cwd=config.ROOT, capture_output=True, text=True,
    )


def _identity() -> None:
    _git("config", "user.name", "anima")
    _git("config", "user.email", "friend@localhost")


def _commit(message: str) -> subprocess.CompletedProcess:
    r = _git("commit", "-q", "-m", message)
    if r.returncode != 0 and "identity" in (r.stderr + r.stdout).lower():
        _identity()  # git wants a name/email; give the repo a local one and retry
        r = _git("commit", "-q", "-m", message)
    return r


def git_snapshot() -> str:
    first = not (SNAP_DIR / "HEAD").exists()
    if first:
        BACKUP_DIR.mkdir(exist_ok=True)
        r = _git("init", "-q")
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "git init failed")
    present = [p for p in SNAPSHOT_PATHS if (config.ROOT / p).exists()]
    if not present:
        raise RuntimeError("nothing of the friend's to snapshot yet")
    # --force takes the friend's files whatever the folder's .gitignore says;
    # -A within those paths also records what was removed
    r = _git("add", "-A", "--force", "--", *present, *SNAPSHOT_EXCLUDE)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "git add failed")
    if first:
        r = _commit(f"first snapshot ({STAMP})")
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
        return f"Set up backups/.snapshots and made the first snapshot ({STAMP})."
    r = _commit(f"snapshot {STAMP}")
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        if "nothing to commit" in out.lower() or "nothing added" in out.lower():
            return "Nothing changed since the last snapshot."
        raise RuntimeError(out)
    return f"Snapshot committed ({STAMP})."


def snapshots() -> list[str]:
    """The snapshots so far, newest first: 'hash  date  message' lines."""
    if not (SNAP_DIR / "HEAD").exists():
        return []
    r = _git("log", "--format=%h  %ad  %s", "--date=short")
    return [ln for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []


def zip_snapshot() -> str:
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"friend-{FILESTAMP}.zip"
    root = config.ROOT.resolve()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(part in EXCLUDE_DIRS for part in rel.parts):
                continue
            zf.write(p, rel)
    # prune old zips, newest kept
    zips = sorted(BACKUP_DIR.glob("friend-*.zip"))
    for old in zips[:-KEEP_ZIPS]:
        old.unlink()
    size_mb = target.stat().st_size / 1_048_576
    return f"git isn't installed, so: zipped them to backups/{target.name} ({size_mb:.1f} MB, keeping last {KEEP_ZIPS})."


def main() -> None:
    if "--list" in sys.argv:
        lines = snapshots()
        print("\n".join(lines) if lines else "(no snapshots yet)")
        return
    if shutil.which("git"):
        try:
            print(git_snapshot())
            return
        except RuntimeError as e:
            print(f"(git had trouble: {e} — falling back to zip)")
    print(zip_snapshot())


if __name__ == "__main__":
    main()
