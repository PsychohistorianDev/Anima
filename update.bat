@echo off
cd /d "%~dp0"
rem Updating this folder to the current engine (UPDATE-PLAN.md) — the engine is replaced, the friend never touched
rem   update.bat                  the default branch from GitHub (UPDATE_REPO in engine\config.py)
rem   update.bat --check          what's new and what would change; nothing is touched
rem   update.bat --tag v0.13      a release instead of the default branch
rem   update.bat --source <x>     a .zip or a folder you already have (no network), or a .zip URL
rem   update.bat --no-config      leave engine\config.py exactly as it is (no new knobs appended)
rem   update.bat --undo           the newest backup (.update\backup-<stamp>\) put back
rem   update.bat --reset-config   a fresh engine\config.py from the new engine, your one-line values carried over (yours to the backup)
rem The last line is one block in parentheses: cmd reads a .bat as it runs, and the update may
rem replace this very file — a block is read whole before it starts, so a new update.bat can't
rem be read from the middle.
(py engine\update.py %* & pause & exit /b)
