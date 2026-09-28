@echo off
cd /d "%~dp0"
rem The keeper's body, as the watch saw it — Garmin Connect → memory\body\<day>.json (BODY-PLAN.md)
rem   body.bat --login    once: email, password, MFA — tokens cached in memory\garmin\
rem   body.bat --today    pull today and print the section she would see
rem   body.bat --pull     the loop: today and yesterday every BODY_PULL_MIN
rem   body.bat --status   the newest file, the last sync, the log's tail
rem   body.bat --demo     a made-up day, to see the section before any login
rem needs:  py -m pip install garminconnect   (Python 3.12+; if the engine's py is older: py -3.12 engine\body.py)
py engine\body.py %*
pause
