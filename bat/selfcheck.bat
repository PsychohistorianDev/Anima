@echo off
cd /d "%~dp0.."
py engine\selfcheck.py %*
pause
