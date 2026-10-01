#!/bin/bash
cd "$(dirname "$0")/.."
python3 engine/heartbeat.py --reverie
read -n1 -r -p "(press any key to close)"
