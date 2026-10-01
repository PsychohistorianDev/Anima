#!/bin/bash
cd "$(dirname "$0")/.."
# The keeper's body, as the watch saw it — Garmin Connect → memory/body/<day>.json (BODY-PLAN.md)
#   bat/body.command --login    once: email, password, MFA — tokens cached in memory/garmin/
#   bat/body.command --today    pull today and print the section they would see
#   bat/body.command --pull     the loop: today and yesterday every BODY_PULL_MIN
#   bat/body.command --status   the newest file, the last sync, the log's tail
#   bat/body.command --demo     a made-up day, to see the section before any login
# needs:  python3 -m pip install garminconnect   (Python 3.12+; if the engine's python3 is older: python3.12 engine/body.py)
python3 engine/body.py "$@"
read -n1 -r -p "(press any key to close)"
