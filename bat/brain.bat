@echo off
cd /d "%~dp0.."
rem the brain's door: llama-server, found on the PATH or in llama\ beside the engine, the model from Ollama's own manifest
rem   (BRAIN_API = "llama" in config.py sends the brain here; py engine\brain_find.py alone prints the command and stops)
py engine\brain_find.py --run
pause
