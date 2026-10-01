#!/bin/bash
cd "$(dirname "$0")/.."
# Updating this folder to the current engine (UPDATE-PLAN.md) — the engine is replaced, the friend never touched
#   bat/update.sh                  the default branch from GitHub (UPDATE_REPO in engine/config.py)
#   bat/update.sh --check          what's new and what would change; nothing is touched
#   bat/update.sh --tag v0.13      a release instead of the default branch
#   bat/update.sh --source <x>     a .zip or a folder you already have (no network), or a .zip URL
#   bat/update.sh --no-config      leave engine/config.py exactly as it is (no new knobs appended)
#   bat/update.sh --undo           the newest backup (.update/backup-<stamp>/) put back
#   bat/update.sh --reset-config   a fresh engine/config.py from the new engine, your one-line values carried over (yours to the backup)
# The last line is one block in braces: bash reads a script as it runs, and the update may
# replace this very file — a block is read whole before it starts, and the exit inside it
# ends the script before anything after the block is read, so a new one can't be read from the middle.
{ python3 engine/update.py "$@"; read -n1 -r -p "(press any key to close)"; exit; }
