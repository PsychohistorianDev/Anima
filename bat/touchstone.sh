#!/bin/bash
cd "$(dirname "$0")/.."
# the stone's keeper: asks the board what it felt, keeps the log, pushes their states (a door; the panel's Stop ends it)
#   bat/touchstone.sh --status   the board's last word and the newest touches
#   bat/touchstone.sh --test     one look at the board, printed
python3 engine/touchstone.py "$@"
read -n1 -r -p "(press any key to close)"
