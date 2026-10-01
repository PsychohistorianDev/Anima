#!/bin/bash
cd "$(dirname "$0")"
# The panel: one door with the others behind it (PANEL-PLAN.md) - http://127.0.0.1:8764 in your browser
python3 engine/panel.py
read -n1 -r -p "(press any key to close)"
