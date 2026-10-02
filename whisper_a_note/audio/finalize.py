"""Finishing a recording: on End (REC-07) and when recovering after a crash (REC-12).

Reads the WAV tracks, aligns their lengths, cuts at the End point (REC-04a), writes the
FLAC tracks and the mixed playback file, and records the duration.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import soundfile as sf

from ..storage import NotesFile, Project, RecordingFile

STORE_RATE = 16000  # Q42


def _read(path) -> np.ndarray:
    if not path.exists():
        return np.zeros(0, np.float32)
    data, rate = sf.read(path, dtype="float32", always_2d=False)
    assert rate == STORE_RATE, f"{path.name}: unexpected sample rate {rate}"
    return data


def is_unfinished(project: Project, base: str) -> bool:
    """WAV tracks left behind without a finished recording (crash or power loss)."""
    has_wav = any(project.path(base, f"{k}.wav").exists() for k in ("mic", "system"))
    return has_wav and not project.path(base, "flac").exists()


def finalize_recording(project: Project, base: str) -> int:
    """Returns the duration in ms. Safe to call again if it was interrupted."""
    meta_file = RecordingFile(project.path(base, "recording.json"))
    meta = meta_file.meta
    tracks = {k: _read(project.path(base, f"{k}.wav")) for k in ("mic", "system")}
    n = max(len(t) for t in tracks.values())
    if meta.end_requested_ms is not None:
        n = min(n, meta.end_requested_ms * STORE_RATE // 1000)
    tracks = {k: np.pad(t[:n], (0, n - len(t[:n]))) for k, t in tracks.items()}
    duration_ms = n * 1000 // STORE_RATE

    mix = tracks["mic"] + tracks["system"]
    peak = float(np.max(np.abs(mix))) if n else 0.0
    if peak > 0.99:
        mix *= 0.99 / peak
    for k, t in tracks.items():
        sf.write(project.path(base, f"{k}.flac"), t, STORE_RATE, subtype="PCM_16")
    sf.write(project.path(base, "flac"), mix, STORE_RATE, subtype="PCM_16")  # written last: marks "finished"

    mutes = tuple(
        replace(m, end_ms=duration_ms if m.end_ms is None else min(m.end_ms, duration_ms))
        for m in meta.mutes if m.start_ms <= duration_ms)
    meta_file.update(duration_ms=duration_ms, mutes=mutes)

    # Notes written during the grace period or just before a crash must not be lost:
    # place them at the end instead of letting them become faulty (NOTE-05).
    notes = NotesFile(project.path(base, "notes.json"), duration_ms=None)
    for note in list(notes.notes):
        if note.time_ms > duration_ms:
            notes.set_time(note.id, duration_ms)

    for k in ("mic", "system"):
        project.path(base, f"{k}.wav").unlink(missing_ok=True)
    return duration_ms
