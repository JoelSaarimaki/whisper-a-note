#!/bin/sh
cd "$(dirname "$0")"
exec .venv/bin/python -m whisper_a_note "$@"
