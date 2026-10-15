#!/bin/bash
cd "$(dirname "$0")/.."
python3 engine/brain_find.py --run
read -n1 -r -p "(press any key to close)"
