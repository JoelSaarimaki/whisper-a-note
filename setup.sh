#!/bin/sh
# Whisper A Note setup for macOS and Linux: creates .venv, installs dependencies, downloads the model.
set -e
cd "$(dirname "$0")"
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
"$PY" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python -m whisper_a_note --download-models
echo "Setup finished. Start the app with ./run.sh"
