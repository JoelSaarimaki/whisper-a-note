"""Decode the Finnish test meeting to 16 kHz mono and build reference files.

- <name>.wav            16 kHz mono (decoded with PyAV, as the app would)
- <name>.truth.json     speaker turns from the ElevenLabs transcript (approximate ground truth)
- <name>.reference.txt  manual transcript text without speaker names (for word error rate)
"""
import json, re
from pathlib import Path
import soundfile as sf
from faster_whisper import decode_audio

src = Path("audio_test_files_finnish")
out = Path("spikes/test_audio")
name = "kuulumiset"
audio = decode_audio(str(src / "kuulumiset_testi.mp3"), sampling_rate=16000)
sf.write(out / f"{name}.wav", audio, 16000)

def secs(ts):
    h, m, s = ts.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

turns = []
text = (src / "kuulumiset_testi_elevenlabs.txt").read_text(encoding="utf-8")
for m in re.finditer(r"(\d\d:\d\d:\d\d,\d+) --> (\d\d:\d\d:\d\d,\d+) \[(Speaker \d)\]", text):
    turns.append({"start": secs(m[1]), "end": secs(m[2]), "speaker": m[3]})
json.dump(turns, open(out / f"{name}.truth.json", "w"), indent=1)

manual = (src / "kuulumiset_testi_manual.txt").read_text(encoding="utf-8")
ref = " ".join(line.split(":", 1)[1] for line in manual.splitlines() if ":" in line)
(out / f"{name}.reference.txt").write_text(ref, encoding="utf-8")
print(f"{len(audio)/16000:.1f} s, {len(turns)} turns, {len({t['speaker'] for t in turns})} speakers, {len(ref.split())} reference words")
