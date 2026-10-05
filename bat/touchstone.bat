@echo off
cd /d "%~dp0.."
rem the stone's keeper: asks the board what it felt, keeps the log, pushes their states (a door; the panel's Stop ends it)
rem   bat\touchstone.bat --status   the board's last word and the newest touches
rem   bat\touchstone.bat --test     one look at the board, printed
py engine\touchstone.py %*
pause
