"""Phase 0: try pyannote community-1 speed settings on CPU (threads, batch sizes).

    uv run python spikes/pyannote_tuning.py spikes/test_audio/kuulumiset.wav
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
audio, sr = sf.read(sys.argv[1], dtype="float32")
waveform = {"waveform": torch.from_numpy(audio)[None], "sample_rate": sr}
duration = len(audio) / sr


class StepTimer:
    """pyannote hook: records when each pipeline step is first and last reported."""
    def __init__(self):
        self.t0, self.steps = time.perf_counter(), {}

    def __call__(self, step_name, step_artifact, file=None, total=None, completed=None):
        now = time.perf_counter() - self.t0
        first, _ = self.steps.get(step_name, (now, now))
        self.steps[step_name] = (first, now)


variants = [
    {"threads": 16, "seg_bs": 32, "emb_bs": 32},   # defaults
    {"threads": 6, "seg_bs": 32, "emb_bs": 32},    # performance cores only
    {"threads": 8, "seg_bs": 32, "emb_bs": 32},
    {"threads": 16, "seg_bs": 64, "emb_bs": 64},
    {"threads": 8, "seg_bs": 64, "emb_bs": 64},
    {"threads": 8, "seg_bs": 16, "emb_bs": 16},
]
pipeline = Pipeline.from_pretrained(ROOT / "models" / "pyannote" / "speaker-diarization-community-1")
results = []
for v in variants:
    torch.set_num_threads(v["threads"])
    pipeline.segmentation_batch_size = v["seg_bs"]
    pipeline.embedding_batch_size = v["emb_bs"]
    hook = StepTimer()
    t0 = time.perf_counter()
    out = pipeline(waveform, hook=hook)
    run = time.perf_counter() - t0
    n = len(out.speaker_diarization.labels())
    steps = {k: round(b - a, 1) for k, (a, b) in hook.steps.items()}
    results.append({**v, "run_s": round(run, 1), "rtf": round(run / duration, 3), "speakers": n, "steps": steps})
    print(json.dumps(results[-1]), flush=True)
(ROOT / "results" / "pyannote_tuning.json").write_text(json.dumps(results, indent=1))
