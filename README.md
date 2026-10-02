# Whisper A Note

Record meetings (microphone + system audio), write timestamped notes while you talk, then
transcribe locally with speaker detection and per-word confidence. Review everything on a
timeline and export to Markdown for further use, e.g. with AI tools.

Everything runs on your own computer: no cloud services, no accounts, no API keys.

> Status: early MVP. Windows works; macOS (14.2+) and Linux are planned but not tested yet.
> See `SPEC.md` for the full specification.

## Install

1. Install **Python 3.11 or 3.12** from [python.org](https://www.python.org/downloads/)
   (Windows: tick "Add python.exe to PATH").
2. Download this repository (`git clone` or "Download ZIP").
3. Run the setup script once:
   - Windows: double-click `setup.bat`
   - macOS / Linux: `./setup.sh`

   It creates a `.venv` folder, installs the dependencies (~1.4 GB, CPU only) and downloads
   the Whisper model (~1.6 GB).
4. Start the app: `run.bat` (Windows) or `./run.sh`.

Tip: use headphones while recording, so the microphone does not pick up the other participants.

## Development

Developers use [uv](https://docs.astral.sh/uv/): `uv sync`, then `uv run python -m whisper_a_note`.
Tests: `uv run pytest` (slow end-to-end test: `RUN_SLOW=1 uv run pytest`).
After changing dependencies, regenerate `requirements.txt`:

```
uv export --no-hashes --no-dev --no-emit-project --emit-index-url --format requirements-txt -o requirements.txt
```

## Licence

MIT, see `LICENSE`. Bundled and downloaded models and the main libraries are listed in
`THIRD_PARTY_LICENSES.md`.
