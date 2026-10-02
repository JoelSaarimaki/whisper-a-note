"""Phase 0: pyannote speed levers that matter (embeddings dominate the run time).

1. Segmentation window step: fewer, less-overlapping windows -> fewer embeddings.
2. Thread contention: diarizing in the same process right after faster-whisper.

    uv run python spikes/pyannote_tuning2.py spikes/test_audio/kuulumiset.wav
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
import soundfile as sf
import torch
from pyannote.audio import Pipeline

ROOT = Path(__file__).resolve().parent
path = Path(sys.argv[1])
audio, sr = sf.read(path, dtype="float32")
waveform = {"waveform": torch.from_numpy(audio)[None], "sample_rate": sr}
duration = len(audio) / sr
truth = json.loads(path.with_suffix(".truth.json").read_text())


def frame_accuracy(annotation, step=0.1):
    """Share of reference speech frames whose (majority-mapped) predicted speaker is right."""
    pred = [(t.start, t.end, s) for t, _, s in annotation.itertracks(yield_label=True)]
    pairs = []
    for g in truth:
        t = g["start"]
        while t < g["end"]:
            hits = [s for a, b, s in pred if a <= t < b]
            pairs.append((hits[0] if hits else None, g["speaker"]))
            t += step
    mapping = {}
    for spk in {p for p, _ in pairs if p}:
        votes = [r for p, r in pairs if p == spk]
        mapping[spk] = max(set(votes), key=votes.count)
    return sum(mapping.get(p) == r for p, r in pairs) / len(pairs)


def run(pipeline, label):
    t0 = time.perf_counter()
    out = pipeline(waveform)
    dt = time.perf_counter() - t0
    ann = out.speaker_diarization
    r = {"variant": label, "run_s": round(dt, 1), "rtf": round(dt / duration, 3),
         "speakers": len(ann.labels()), "frame_accuracy": round(frame_accuracy(ann), 3)}
    print(json.dumps(r), flush=True)
    return r


results = []
pipeline = Pipeline.from_pretrained(ROOT / "models" / "pyannote" / "speaker-diarization-community-1")
window = pipeline._segmentation.duration
for frac in (0.1, 0.2, 0.3, 0.5):  # 0.1 = default (90% overlap)
    pipeline._segmentation.step = frac * window
    results.append(run(pipeline, f"step {frac:.0%} of {window:.0f}s window"))
pipeline._segmentation.step = 0.1 * window

from faster_whisper import WhisperModel
model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
segs, _ = model.transcribe(audio, language="fi", vad_filter=True, word_timestamps=True,
                           condition_on_previous_text=False)
list(segs)
results.append(run(pipeline, "default step, after faster-whisper in same process"))
(ROOT / "results" / "pyannote_tuning2.json").write_text(json.dumps(results, indent=1))
