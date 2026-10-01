#!/bin/bash
cd "$(dirname "$0")/.."
# the bridge asks to be started again (exit code 75, its /restart) — the loop does it, as bat\telegram.bat's :again
while true; do
    python3 engine/telegram.py
    [ $? -eq 75 ] || break
    echo
    echo "(restarting the bridge on the current engine code...)"
done
read -n1 -r -p "(press any key to close)"
