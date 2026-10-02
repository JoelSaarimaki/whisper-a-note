"""Dual-track recording engine (SPEC §5.3).

Each source runs in its own thread: read a 100 ms block, apply mute, resample to 16 kHz,
append to `<base>.mic.wav` / `<base>.system.wav` and flush, so a crash loses at most one
block (REC-05; flushing also keeps the WAV header valid). Audio time is the length of the
mic track, so note timestamps, mutes and the elapsed-time display all use the same clock.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from ..storage import Mute, Project, RecordingFile
from .finalize import STORE_RATE, finalize_recording
from .sources import BLOCK_FRAMES, DEVICE_RATE, DeviceLost, Source

TRACKS = ("mic", "system")
RECONNECT_INTERVAL_S = 1.0


@dataclass
class Level:
    peak: float = 0.0      # last block, 0..1 (input level, also while muted)
    muted: bool = False
    lost: bool = False     # device lost (REC-13)


class _Track(threading.Thread):
    def __init__(self, recorder: Recorder, kind: str, source: Source, path: Path):
        super().__init__(name=f"rec-{kind}", daemon=True)
        self.recorder, self.kind, self.source = recorder, kind, source
        self.writer = sf.SoundFile(path, "w", STORE_RATE, 1, subtype="PCM_16")
        self.resampler = soxr.ResampleStream(DEVICE_RATE, STORE_RATE, 1, dtype="float32")
        self.frames = 0
        self.level = Level()
        self.error: Exception | None = None

    def run(self) -> None:
        rec = self.recorder
        lost, next_retry = False, 0.0
        try:
            self._open_or_lose()
        except DeviceLost:
            lost = True
        try:
            while not rec._stop.is_set():
                if lost:
                    block = np.zeros(BLOCK_FRAMES, np.float32)
                    time.sleep(BLOCK_FRAMES / DEVICE_RATE)  # keep time running with silence
                    if time.monotonic() >= next_retry:
                        next_retry = time.monotonic() + RECONNECT_INTERVAL_S
                        try:
                            self.source.open()
                            lost = False
                            rec._device_restored(self.kind)
                        except DeviceLost:
                            pass
                else:
                    try:
                        block = self.source.read()
                    except DeviceLost:
                        self.source.close()
                        lost, next_retry = True, time.monotonic() + RECONNECT_INTERVAL_S
                        rec._device_lost(self.kind)
                        continue
                muted = rec.is_muted(self.kind)
                self.level = Level(float(np.max(np.abs(block))) if len(block) else 0.0, muted, lost)
                if muted:
                    block = np.zeros_like(block)
                out = self.resampler.resample_chunk(block)
                if len(out):
                    self.writer.write(out)
                    self.writer.flush()
                    self.frames += len(out)
        except Exception as e:  # e.g. disk full (REC-18): stop safely, keep what was written
            self.error = e
            rec._stop.set()
        finally:
            self.source.close()
            self.writer.close()

    def _open_or_lose(self) -> None:
        try:
            self.source.open()
        except DeviceLost:
            self.recorder._device_lost(self.kind)
            raise


class Recorder:
    """One recording session: Start … End (REC-04, REC-04a)."""

    def __init__(self, project: Project, base: str, mic: Source, system: Source,
                 context: str = "", language: str | None = None):
        self.project, self.base = project, base
        self.meta_file = RecordingFile(project.path(base, "recording.json"))
        self._sources = {"mic": mic, "system": system}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._mute = {"mic": False, "system": False, "all": False}
        self._mutes: list[Mute] = []
        self._open: dict[tuple[str, str], int] = {}  # (source, reason) -> start_ms
        self._tracks: dict[str, _Track] = {}
        self._context, self._language = context, language
        self.events: list[str] = []  # human-readable warnings for the UI, e.g. device lost

    # --- control -------------------------------------------------------------------------

    def start(self, mutes: dict[str, bool] | None = None) -> None:
        """Mutes set before Start apply from the start (REC-03)."""
        self.meta_file.update(
            source="recorded", started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            duration_ms=None, end_requested_ms=None, sample_rate=STORE_RATE,
            devices={k: s.name for k, s in self._sources.items()},
            context=self._context, language=self._language, mutes=())
        for kind, on in (mutes or {}).items():
            if on:
                self.set_mute(kind, True)
        for kind in TRACKS:
            self._tracks[kind] = _Track(self, kind, self._sources[kind], self.project.path(self.base, f"{kind}.wav"))
        for t in self._tracks.values():
            t.start()

    def audio_time_ms(self) -> int:
        t = self._tracks.get("mic")
        return t.frames * 1000 // STORE_RATE if t else 0

    def levels(self) -> dict[str, Level]:
        return {k: t.level for k, t in self._tracks.items()}

    @property
    def failed(self) -> Exception | None:
        """Set if recording stopped by itself (e.g. disk full)."""
        return next((t.error for t in self._tracks.values() if t.error), None)

    @property
    def muted_all(self) -> bool:
        return self._mute["all"]

    def is_muted(self, kind: str) -> bool:
        return self._mute["all"] or self._mute[kind]

    def set_mute(self, kind: str, on: bool) -> None:
        """kind: 'mic', 'system' or 'all' (Mute all, REC-06)."""
        with self._lock:
            if self._mute[kind] == on:
                return
            self._mute[kind] = on
            if on:
                self._open_interval(kind, "user")
            else:
                self._close_interval(kind, "user")

    def request_end(self) -> int:
        """End pressed: the grace period starts; recording continues (REC-04a)."""
        end = self.audio_time_ms()
        with self._lock:
            self.meta_file.update(end_requested_ms=end)
        return end

    def cancel_end(self) -> None:
        with self._lock:
            self.meta_file.update(end_requested_ms=None)

    def finish(self) -> int:
        """Stop capturing and finalize; returns the duration in ms."""
        self._stop.set()
        for t in self._tracks.values():
            t.join()
        with self._lock:
            end = self.audio_time_ms()
            for key in list(self._open):
                self._close_interval(*key, at=end)
        return finalize_recording(self.project, self.base)

    # --- intervals (mutes and lost devices) ----------------------------------------------

    def _device_lost(self, kind: str) -> None:
        with self._lock:
            self._open_interval(kind, "device_lost")
        self.events.append(f"{'Microphone' if kind == 'mic' else 'System audio'} lost: recording silence until it returns")

    def _device_restored(self, kind: str) -> None:
        with self._lock:
            self._close_interval(kind, "device_lost")
        self.events.append(f"{'Microphone' if kind == 'mic' else 'System audio'} is back")

    def _open_interval(self, source: str, reason: str) -> None:
        self._open[(source, reason)] = self.audio_time_ms()
        self._save_mutes()

    def _close_interval(self, source: str, reason: str, at: int | None = None) -> None:
        start = self._open.pop((source, reason), None)
        if start is not None:
            self._mutes.append(Mute(source, reason, start, self.audio_time_ms() if at is None else at))
            self._save_mutes()

    def _save_mutes(self) -> None:
        open_ = [Mute(s, r, start, None) for (s, r), start in self._open.items()]
        self.meta_file.update(mutes=tuple(sorted(self._mutes + open_, key=lambda m: m.start_ms)))
