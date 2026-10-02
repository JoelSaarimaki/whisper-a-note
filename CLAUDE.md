# CLAUDE.md

Context for Claude Code sessions working on this project.

## Project

**Whisper A Note** (Python package `whisper_a_note`): a local, privacy-preserving desktop app for recording meetings (mic + system audio), writing timestamped manual notes during the meeting, transcribing afterwards with speaker diarization and per-word confidence, reviewing everything on a vertical timeline, and exporting to Markdown/JSON for further use (e.g. by AI tools).

## Files

- `SPEC.md` — **the source of truth.** Requirements with IDs (`REC-04`, `NOTE-05b`, …), priorities (P1 = MVP, P2, P3), architecture, data model, distribution, and a decision log (§11). Keep it up to date when decisions change; add new questions to §11.

## Status

- Spec at Draft v0.7 (2026-10-02). All open questions resolved.
- **MVP in progress (Windows works end to end):** `whisper_a_note/` has `storage/` (JSON files, notes, metadata), `audio/` (recorder, finalize/recovery), `transcription/` (chunked Whisper + pyannote worker processes, job state machine), `export.py`, and `ui/` (PySide6: setup dialog, Recording mode, Review mode with timeline, settings). Tests in `tests/` (`uv run pytest`; `RUN_SLOW=1` for the end-to-end job test). Not done yet: macOS/Linux spikes, P2/P3 features, by-ear capture check, a real-world test by the user.
- Spikes in `spikes/`, results in `spikes/PHASE0_RESULTS.md`. Test models and recordings are gitignored (`spikes/models/`, `spikes/test_audio/`, `audio_test_files_finnish/`).
- **Phase 0 spikes** (SPEC §10):
  1. macOS system audio via Core Audio process taps (Swift helper streaming PCM to Python); clock drift between tracks is only a quick, minor check.
  2. **Done on Windows:** pipeline works offline; `large-v3-turbo` default, context as `hotwords` only (no previous-text conditioning), pyannote community-1, audio passed to pyannote in memory. Windows capture (`soundcard`, mic + loopback) and a clean pip install also work; by-ear test of real speech deferred to the first MVP recording.
  3. Clean `pip install -r requirements.txt` on Windows, macOS and Linux.
- Then: project skeleton (`pyproject.toml`, uv, package layout following PKG-1–9), then the MVP (all P1 requirements).

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

- The user iterates on the design collaboratively: propose a recommendation with brief reasoning, then update `SPEC.md` once they agree.
- Cares about the important Phase 0 questions (hotwords, speed, pyannote, installs), not minor technical details like clock drift.
- Prefers simple solutions over feature-rich ones (e.g. dropped pause, dropped installers, dropped split audio).
- Mark suggestions that go beyond the user's requests as *(proposed)* in the spec.
- UX principle: during a fast-moving recording session, act immediately and offer undo/restore instead of confirmations; elsewhere, confirm irreversible actions (e.g. transcription Restart).
