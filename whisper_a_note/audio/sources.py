"""Audio input sources: microphone and system audio (SPEC §8.3).

A source delivers mono float32 blocks at `DEVICE_RATE`. Windows and Linux use `soundcard`
(WASAPI loopback / PulseAudio-PipeWire monitor); macOS will use the Core Audio taps helper.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

DEVICE_RATE = 48000
BLOCK_FRAMES = DEVICE_RATE // 10  # 100 ms


class DeviceLost(Exception):
    """The device disappeared or stopped delivering audio (REC-13)."""


class Source(Protocol):
    name: str

    def open(self) -> None: ...
    def read(self) -> np.ndarray: ...  # one block, mono float32; raises DeviceLost
    def close(self) -> None: ...


class SoundcardSource:
    """Microphone, or loopback of an output device, via `soundcard`."""

    def __init__(self, device_name: str | None, loopback: bool):
        self.device_name = device_name  # None = system default
        self.loopback = loopback
        self._ctx = None
        self._rec = None
        try:
            self.name = self._device().name  # the actual device, also when using the default
        except Exception:
            self.name = device_name or "default"

    def _device(self):
        import soundcard as sc
        if self.loopback:
            speaker = sc.get_speaker(self.device_name) if self.device_name else sc.default_speaker()
            return sc.get_microphone(speaker.name, include_loopback=True)
        return sc.get_microphone(self.device_name) if self.device_name else sc.default_microphone()

    def open(self) -> None:
        try:
            device = self._device()
            self.name = device.name
            self._ctx = device.recorder(samplerate=DEVICE_RATE, channels=1, blocksize=BLOCK_FRAMES)
            self._rec = self._ctx.__enter__()
        except Exception as e:  # soundcard raises various errors for missing devices
            self._ctx = self._rec = None
            raise DeviceLost(str(e)) from e

    def read(self) -> np.ndarray:
        if self._rec is None:
            raise DeviceLost("not open")
        try:
            data = self._rec.record(numframes=BLOCK_FRAMES)
        except Exception as e:
            raise DeviceLost(str(e)) from e
        return np.ascontiguousarray(data[:, 0], dtype=np.float32)

    def close(self) -> None:
        if self._ctx is not None:
            try:
                self._ctx.__exit__(None, None, None)
            except Exception:
                pass
        self._ctx = self._rec = None


def list_devices() -> dict[str, list[str]]:
    """Names for the device selection (REC-08)."""
    import soundcard as sc
    return {
        "mic": [m.name for m in sc.all_microphones(include_loopback=False)],
        "system": [s.name for s in sc.all_speakers()],
    }
