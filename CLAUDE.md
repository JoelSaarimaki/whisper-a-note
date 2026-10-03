# CLAUDE.md

Context for Claude Code sessions working on this project.

## Project

**Whisper A Note** (Python package `whisper_a_note`): a local, privacy-preserving desktop app for recording meetings (mic + system audio), writing timestamped manual notes during the meeting, transcribing afterwards with speaker diarization and per-word confidence, reviewing everything on a vertical timeline, and exporting to Markdown/JSON for further use (e.g. by AI tools).

## Files

- `SPEC.md` — **the source of truth.** Requirements with IDs (`REC-04`, `NOTE-05b`, …), priorities (P1 = MVP, P2, P3), architecture, data model, distribution, and a decision log (§11). Keep it up to date when decisions change; add new questions to §11.

## Status (end of session, 2026-10-03)

- Spec at Draft v0.8. All open questions resolved.
- **First application test done** (English test meeting in `test_cases/application_test_english/`, UI feedback and screenshots in `test_cases/test_feedback/`). All feedback items are implemented: optional recording name in the setup (part of the base name), no project context in the setup, Cancel instead of Review before Start, shorter Review toolbar (separate-files option in settings, Open export folder in the export message), fixed-width sidebar, one Edit dialog for note time + text, settings in sections, timestamp play buttons in the timeline. Transcription: a punctuation primer now precedes the hotwords (CTX-02a) after one chunk came out without punctuation.
- **Phase 0 done on Windows** (results in `spikes/PHASE0_RESULTS.md`): `large-v3-turbo` default, context as `hotwords` only (no previous-text conditioning), pyannote community-1 bundled in the package, pyannote in its own process with in-memory audio, `soundcard` for mic + WASAPI loopback, clean pip install works.
- **MVP implemented and working on Windows** (all automated tests pass; a Finnish test meeting was transcribed through the app's own job code):
  - `whisper_a_note/storage/` JSON files, notes, metadata · `audio/` recorder, finalize, crash recovery · `transcription/` chunked Whisper + pyannote worker processes, job state machine · `export.py` · `ui/` PySide6 (setup dialog, Recording mode, Review mode with timeline, settings, controller in `app.py`).
  - Run for development: `uv run python -m whisper_a_note`. Users: `setup.bat`/`run.bat` (`setup.sh`/`run.sh`). Do not run `setup.bat` in the dev checkout (it would replace uv's `.venv`).
  - Tests: `uv run pytest`; `RUN_SLOW=1` adds the end-to-end transcription test. UI smoke tests run offscreen with fake audio sources (`tests/test_ui_smoke.py`). For screenshots offscreen, set `QT_QPA_FONTDIR=C:\Windows\Fonts`.
- Gitignored local data: `spikes/models/`, `spikes/test_audio/`, `spikes/results/`, `test_cases/` (test recordings, incl. `test_cases/audio_test_files_finnish/`, a real meeting with colleagues' voices; never commit). The Whisper model is in the app's user data folder (`%LOCALAPPDATA%\Whisper A Note\models`).

## Next steps

1. **Wait for the user's next test round** and fix what they report. The deferred by-ear capture check (levels, mix balance, 16 kHz playback) is still open.
2. Recommended next transcription improvement: mic-based speaker attribution (TRN-09, P2). In the first test, questions came from system audio and answers from the mic, yet diarization split "Start speaking now!" between speakers (SPEC Q50). Discuss with the user before building.
3. P1 gap: REC-19 system-sleep marker is not implemented (recording just continues after wake-up).
4. P2 features not built yet: audio import (REC-09), speaker renaming (TRN-08), dragging notes on the timeline (NOTE-10) and batch shift UI (NOTE-13, storage already supports it), mixed-language mode (CTX-04), expected speaker count (CTX-05), replay/loop and playback speed (TL-07b/c), zoom (TL-08), project-wide export (EXP-04), average confidence in export (EXP-07), deleting recordings/projects (PRJ-07), renaming recordings (PRJ-06), recent projects list UI (PRJ-05). Basic chat commands (/start, /end, /mute) already work.
5. macOS (Core Audio taps Swift helper) and Linux spikes and installs: need those machines and the user.
6. `requirements-gpu.txt` is not generated yet.

## Key decisions (details and rationale in SPEC.md)

- **Stack:** Python 3.11/3.12, PySide6 desktop app. Not a web UI (too disruptive during meetings).
- **UI:** dark theme, English only. Compact *Recording mode* (normal resizable window, not always on top; can be narrow or screen-tall; top to bottom: header, note history, note input, controls), entered through a *recording setup* step (project, context texts, devices + sound check), and full *Review mode* (three-column timeline: audio / transcript / notes).
- **OS:** Windows, macOS **14.2+** (Core Audio taps only, no older fallbacks), Linux.
- **Audio:** separate mic and system tracks plus a mixed playback file. **No pause**: "Mute all" (off the record) instead; ending a recording is final, after a 5 s "Ending recording…" grace period with Cancel.
- **Transcription:** on demand after recording only, never live. faster-whisper + pyannote. **CPU-only must work**; GPU optional. Default model `large-v3-turbo` (accuracy first, speed second); `large-v3` selectable.
- **Languages:** fixed or auto-detect (P1); mixed-language mode with per-speaker-turn detection restricted to expected languages (P2).
- **Context:** one project context plus an optional per-recording context, combined and passed to Whisper as `hotwords`.
- **Concurrency:** no recording while a transcription runs; only one transcription running at a time (interrupting frees the slot).
- **Notes:** per recording; timestamps always within the audio, single timestamp (submission time); submitted in Recording mode between Start and End, plus one replaceable closing note at the end after End (NOTE-02b). Faulty entries in edited files (outside the audio or otherwise invalid) are ignored and flagged, but not protected: the next save drops them.
- **Confidence:** exact per-word values in JSON export; low-confidence words (< 70%) marked in italics in Markdown (legend in YAML front matter) and moderately highlighted in the UI.
- **Distribution:** source + pinned `requirements.txt`, installed with plain pip by users (setup/run scripts). No installers in v1, but code must stay packaging-ready (PKG-1–9).
- **Dev tooling:** uv (`pyproject.toml` + `uv.lock`, `uv export` generates the requirements files). End users never need uv.
- **Models:** no Hugging Face token for users; pyannote weights bundled in the application package for fully offline diarization (check licences, add attribution); the Whisper model is downloaded during setup.
- **Open source** under the MIT licence; no encryption by the app; transcript read-only in v1.

## Working with the user

- Commits: the user allows Claude to commit directly to `main` (end commit messages with the Co-Authored-By line).
- The user iterates on the design collaboratively: propose a recommendation with brief reasoning, then update `SPEC.md` once they agree.
- Cares about the important Phase 0 questions (hotwords, speed, pyannote, installs), not minor technical details like clock drift.
- Prefers simple solutions over feature-rich ones (e.g. dropped pause, dropped installers, dropped split audio).
- Mark suggestions that go beyond the user's requests as *(proposed)* in the spec.
- UX principle: during a fast-moving recording session, act immediately and offer undo/restore instead of confirmations; elsewhere, confirm irreversible actions (e.g. transcription Restart).
