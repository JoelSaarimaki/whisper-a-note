"""Splitting a recording into chunks for transcription (SPEC §8.2, REC-06a).

Chunks are cut in pauses between speech (found with faster-whisper's voice-activity
detector), so no word is split. Fully muted intervals are left out. Progress is saved
after each chunk, so Interrupt loses at most one chunk of work.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

RATE = 16000
MAX_CHUNK_S = 60.0
PAD_S = 0.4  # context kept around speech so word edges are not clipped


@dataclass(frozen=True)
class Chunk:
    start_ms: int
    end_ms: int


def speech_regions(audio: np.ndarray) -> list[tuple[int, int]]:
    """Speech as (start_ms, end_ms) pairs."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    regions = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500))
    return [(r["start"] * 1000 // RATE, r["end"] * 1000 // RATE) for r in regions]


def plan_chunks(regions: list[tuple[int, int]], duration_ms: int,
                muted_all: list[tuple[int, int]], max_chunk_ms: int = int(MAX_CHUNK_S * 1000)) -> list[Chunk]:
    """Group speech regions into chunks of at most ~max_chunk_ms, cut between regions."""
    def outside_mutes(a, b):
        parts = [(a, b)]
        for ma, mb in muted_all:
            parts = [p for x, y in parts for p in ((x, min(y, ma)), (max(x, mb), y)) if p[1] > p[0]]
        return parts

    pad = int(PAD_S * 1000)
    speech = [p for a, b in regions for p in outside_mutes(max(0, a - pad), min(duration_ms, b + pad))]
    chunks: list[Chunk] = []
    for a, b in sorted(speech):
        if chunks and b - chunks[-1].start_ms <= max_chunk_ms and a <= chunks[-1].end_ms + 2000:
            chunks[-1] = Chunk(chunks[-1].start_ms, max(b, chunks[-1].end_ms))
        elif chunks and a < chunks[-1].end_ms:  # overlap after padding: continue where the last ended
            chunks.append(Chunk(chunks[-1].end_ms, b))
        else:
            chunks.append(Chunk(a, b))
    # A single region longer than the limit is split into equal parts.
    result = []
    for c in chunks:
        n = max(1, -(-(c.end_ms - c.start_ms) // max_chunk_ms))
        step = (c.end_ms - c.start_ms) / n
        result += [Chunk(int(c.start_ms + i * step), int(c.start_ms + (i + 1) * step)) for i in range(n)]
    return result
