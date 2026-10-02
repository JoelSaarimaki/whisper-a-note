"""Concatenate the TTS dialogue parts into test files with a ground-truth speaker list."""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf

parts = sorted(Path("spikes/test_audio/parts").glob("*.wav"))
gap = np.zeros(int(16000 * 0.7), dtype=np.float32)
for repeats, name in [(1, "dialogue_short"), (int(sys.argv[1]) if len(sys.argv) > 1 else 5, "dialogue_long")]:
    audio, truth, t = [], [], 0.0
    for _ in range(repeats):
        for p in parts:
            x, sr = sf.read(p, dtype="float32"); assert sr == 16000
            truth.append({"start": round(t, 2), "end": round(t + len(x) / sr, 2), "speaker": p.stem.split("_")[1]})
            audio += [x, gap]; t += (len(x) + len(gap)) / sr
    sf.write(f"spikes/test_audio/{name}.wav", np.concatenate(audio), 16000)
    json.dump(truth, open(f"spikes/test_audio/{name}.truth.json", "w"), indent=1)
    print(name, f"{t/60:.1f} min")
