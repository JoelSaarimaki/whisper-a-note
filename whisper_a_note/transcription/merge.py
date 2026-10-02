"""Combining Whisper words with pyannote speaker turns into segments (SPEC §8.2, TRN-02/03)."""
from __future__ import annotations

SEGMENT_GAP_MS = 2000  # a pause this long starts a new segment, even for the same speaker


def assign_speakers(words: list[dict], turns: list[dict]) -> list[dict]:
    """Give each word the speaker of the turn it overlaps most (nearest turn if none)."""
    out = []
    for w in words:
        best, best_ov = None, 0
        for t in turns:
            ov = min(w["end_ms"], t["end_ms"]) - max(w["start_ms"], t["start_ms"])
            if ov > best_ov:
                best, best_ov = t["speaker"], ov
        if best is None and turns:
            mid = (w["start_ms"] + w["end_ms"]) / 2
            best = min(turns, key=lambda t: min(abs(mid - t["start_ms"]), abs(mid - t["end_ms"])))["speaker"]
        out.append({**w, "speaker": best})
    return out


def speaker_labels(words: list[dict]) -> dict[str, str]:
    """pyannote labels -> generic names in order of first appearance: Speaker 1, Speaker 2, …"""
    labels: dict[str, str] = {}
    for w in words:
        if w["speaker"] is not None and w["speaker"] not in labels:
            labels[w["speaker"]] = f"Speaker {len(labels) + 1}"
    return labels


def build_segments(words: list[dict], language: str | None, language_prob: float | None) -> list[dict]:
    """Group consecutive words of the same speaker; a long pause also starts a new segment."""
    segments: list[dict] = []
    for w in words:
        last = segments[-1] if segments else None
        if last and last["speaker"] == w["speaker"] and w["start_ms"] - last["end_ms"] < SEGMENT_GAP_MS:
            last["words"].append(_word(w))
            last["end_ms"] = w["end_ms"]
        else:
            segments.append({"start_ms": w["start_ms"], "end_ms": w["end_ms"], "speaker": w["speaker"],
                             "language": language, "language_prob": language_prob, "words": [_word(w)]})
    for s in segments:
        s["text"] = join_words([x["w"] for x in s["words"]])
    return segments


def join_words(words: list[str]) -> str:
    text = " ".join(words)
    for p in (" ,", " .", " ?", " !", " :", " ;"):
        text = text.replace(p, p[1])
    return text


def _word(w: dict) -> dict:
    return {"w": w["w"], "start_ms": w["start_ms"], "end_ms": w["end_ms"], "conf": w["conf"]}
