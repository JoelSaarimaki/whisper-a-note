@echo off
rem Starts Whisper A Note without a console window.
cd /d "%~dp0"
start "" .venv\Scripts\pythonw.exe -m whisper_a_note
