@echo off
rem Whisper A Note setup for Windows: creates .venv, installs dependencies, downloads the model.
cd /d "%~dp0"
set PY=
py -3.12 -c "" >nul 2>&1 && set PY=py -3.12
if not defined PY py -3.11 -c "" >nul 2>&1 && set PY=py -3.11
if not defined PY set PY=python
%PY% -m venv .venv || goto :error
.venv\Scripts\python -m pip install --disable-pip-version-check -r requirements.txt || goto :error
.venv\Scripts\python -m whisper_a_note --download-models || goto :error
echo.
echo Setup finished. Start the app with run.bat.
pause
exit /b 0
:error
echo.
echo Setup failed. Python 3.11 or 3.12 from python.org is required.
pause
exit /b 1
