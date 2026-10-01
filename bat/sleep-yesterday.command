#!/bin/bash
cd "$(dirname "$0")/.."
python3 engine/consolidate.py yesterday
read -n1 -r -p "(press any key to close)"
