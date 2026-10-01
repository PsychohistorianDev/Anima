#!/bin/bash
cd "$(dirname "$0")/.."
python3 engine/web.py "$@"
read -n1 -r -p "(press any key to close)"
