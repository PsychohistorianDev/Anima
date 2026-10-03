@echo off
cd /d "%~dp0.."
py engine\blackbox.py %*
pause
