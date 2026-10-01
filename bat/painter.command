#!/bin/bash
cd "$(dirname "$0")/.."
# uses the engine's Python; if the painter lives in another one, run e.g.:  python3.12 engine/painter.py
#   bat/painter.command --test "a violet bloom"   paints once and exits
python3 engine/painter.py "$@"
read -n1 -r -p "(press any key to close)"
