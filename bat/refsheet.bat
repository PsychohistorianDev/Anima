@echo off
cd /d "%~dp0.."
py engine\refsheet.py %*
pause
