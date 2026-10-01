#!/bin/bash
cd "$(dirname "$0")/.."
# uses the engine's Python; if the ear lives in another one, run e.g.:  python3.12 engine/music_ears.py
python3 engine/music_ears.py "$@"
read -n1 -r -p "(press any key to close)"
