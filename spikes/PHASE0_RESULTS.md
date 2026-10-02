# Phase 0 results: transcription + diarization pipeline (Windows, CPU)

Run on 2026-10-02 with `spikes/run_matrix.sh`; raw output in `spikes/results/` (not committed).

**Machine:** Intel Core Ultra 9 285H (16 cores), 64 GB RAM, CPU only, int8. A fast laptop: expect a typical laptop to be roughly 1.5–2× slower.
**Versions:** faster-whisper 1.2.1, pyannote.audio 4.0.7, torch 2.14.1+cpu, PyAV 15.1 (PyAV 16+ breaks faster-whisper's audio decoding).

**Test audio**
- *Finnish:* a real 4.4-minute check-in round, 4 speakers, colloquial speech. Reference: a manual transcript (spoken forms such as "mökkii", "kattoo", so WER is inflated by spelling differences) and ElevenLabs speaker turns (approximate).
- *English:* a synthetic 8.6-minute two-voice dialogue (Windows TTS), the same 1.7-minute script repeated 5×, full of names and product terms.

RTF = processing time / audio duration (0.5 = a 1-hour meeting takes 30 minutes).

## Whisper models (Finnish)

| Model | Download | RTF | WER | Low-confidence words |
|---|---|---|---|---|
| small | ~0.5 GB | 0.24 | 48% | 42% |
| medium | ~1.5 GB | 0.55 | 40% | 28% |
| large-v3-turbo | ~1.6 GB | 0.36 | 37% | 22% |
| large-v3 | ~3 GB | 0.98 | 33% | 17% |

`large-v3-turbo` is the best balance: clearly better than `small`, faster than `medium`. `large-v3` is too slow on CPU.

## Context text (CTX-02)

English, 8.6 min, `small`: correctly spelled key terms (about 32 possible per half).

| Context passed as | First half | Second half |
|---|---|---|
| none | 9 | 7 |
| initial prompt | 21 | 17 |
| hotwords | 33 | 32 |
| both | 33 | 32 |

`hotwords` keeps the context effective through the whole recording; the initial prompt helps less and fades. Finnish (turbo) WER: none 34%, initial 34%, hotwords 31%, both 37%: **hotwords alone** is best.

`condition_on_previous_text=False` gave the same quality (WER 37.5% vs 37.3%), ran ~25% faster, and removes the cause of repetition loops. No loops appeared in any run.

## Diarization

| Version | Finnish, speakers found | Words with correct speaker | With `num_speakers=4` | English (2 voices) | RTF |
|---|---|---|---|---|---|
| community-1 | **4** (correct) | **92%** | 92% | 100% | 0.45 |
| 3.1 | 3 | 69% | 90% | 100% | 0.44 |

**community-1** finds the right number of speakers without help. Diarization took RTF ~0.45 here because it ran right after faster-whisper in the same process; on its own it takes ~0.32 (see tuning below), about as long as transcription, not "considerably faster" as SPEC §8.4 assumed.

Loading from bundled files works offline with `HF_HUB_OFFLINE=1`. Passing audio as an in-memory waveform avoids pyannote's file decoding (torchcodec), which would otherwise need a system FFmpeg.

## Diarization speed tuning (community-1, Finnish)

~97% of diarization time is computing speaker embeddings. Thread count (6/8/16) and batch sizes (16/32/64) changed speed by only ±5%, which is within noise.

| Variant | RTF | Speakers | Frame accuracy* |
|---|---|---|---|
| default, own process | 0.32 | 4 | 78% |
| default, right after faster-whisper in the same process | 0.42 | 4 | 78% |
| window step 20% (half the windows) | 0.16 | 4 | 77% |
| window step 30% / 50% | 0.11 / 0.07 | 2 | 48% / 45% |

\*Share of reference speech time with the right speaker; stricter than the word-based figure above.

**Decision:** keep the default settings (accuracy first), and run pyannote in its own process, separate from faster-whisper, to avoid thread contention (~30% faster).

## Total time per 1-hour meeting (this machine)

| Setup | RTF | 1-hour meeting |
|---|---|---|
| large-v3-turbo (hotwords, no previous-text conditioning) + community-1 in its own process | ~0.58 | ~35 min |

A typical laptop is expected to take roughly 50–70 minutes.

# Phase 0 results: Windows audio capture and install

## System audio + mic capture (`spikes/capture_spike.py`)

Library: `soundcard` 0.4.6 (WASAPI loopback of the default output device; also supports Linux monitor sources). Both sources were recorded at 48 kHz in 100 ms blocks in two threads, then resampled to 16 kHz with `soxr`.

- **Both sources record together.** A quiet test tone played through the speakers appeared on the system track. It also leaked into the laptop mic, which is why the headphones hint is needed (§6.1).
- **Silence on the system side keeps the tracks aligned.** While nothing plays, loopback delivers digital silence instead of stalling, so both tracks stay the same length.
- **No drift measured:** in a 5-minute recording, both tracks came out at 299.9 s. Both started about 0.25 s after the wall clock, which is startup latency, the same for both.
- **CPU use:** 10% of one core over 5 minutes (target < 10%, NFR-04). This is unoptimised spike code; larger blocks and writing straight to WAV should lower it.
- *Pending:* a test with real speech and a video, judged by ear.

## Clean install with plain pip (Windows)

- `requirements.txt` is generated with `uv export --no-hashes --no-dev --no-emit-project --emit-index-url`. `--emit-index-url` is needed: without it, pip cannot find the CPU builds of PyTorch (`torch==…+cpu`), which only exist on the PyTorch package index.
- Fresh `python -m venv` + `pip install -r requirements.txt`: **succeeded in 132 s**, giving CPU-only PyTorch and a **1.4 GB** environment (plus 1.6 GB for the `large-v3-turbo` model).
- The pipeline spike runs in that environment.
- Not yet done: `requirements-gpu.txt`, and the macOS and Linux installs.
