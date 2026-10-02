"""Phase 0 spike: record mic + system audio (WASAPI loopback) at the same time (REC-01).

Checks: both sources deliver audio, how loopback behaves while nothing is playing
(time alignment), CPU use while recording (NFR-04), and writes 16 kHz tracks + a mix.

    uv run python spikes/capture_spike.py --seconds 30
    uv run python spikes/capture_spike.py --seconds 15 --test-tone   # plays a quiet tone at 5-10 s
"""
import argparse
import json
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import soundcard as sc
import soundfile as sf
import soxr

RATE = 48000          # device rate; tracks are stored at 16 kHz (Q42)
BLOCK = RATE // 10    # 100 ms per read
OUT = Path(__file__).resolve().parent / "results" / "capture"


def capture(device, name, stop, store):
    chunks, reads = [], []
    with device.recorder(samplerate=RATE, channels=1, blocksize=BLOCK) as rec:
        t0 = time.perf_counter()
        while not stop.is_set():
            data = rec.record(numframes=BLOCK)
            chunks.append(data[:, 0].astype(np.float32))
            reads.append((round(time.perf_counter() - t0, 3), len(data)))
    store[name] = (np.concatenate(chunks) if chunks else np.zeros(0, np.float32), reads)


def tone(stop_at):
    t = np.arange(int(RATE * 5)) / RATE
    wave = (0.05 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    time.sleep(stop_at)
    sc.default_speaker().play(wave, samplerate=RATE)


def per_second_rms(x):
    n = len(x) // RATE
    return [round(float(np.sqrt(np.mean(x[i * RATE:(i + 1) * RATE] ** 2))), 4) for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--test-tone", action="store_true")
    args = ap.parse_args()

    mic = sc.default_microphone()
    loop = sc.get_microphone(sc.default_speaker().name, include_loopback=True)
    print("mic:", mic.name, "| system:", loop.name, flush=True)

    stop, store = threading.Event(), {}
    threads = [threading.Thread(target=capture, args=(mic, "mic", stop, store)),
               threading.Thread(target=capture, args=(loop, "system", stop, store))]
    if args.test_tone:
        threading.Thread(target=tone, args=(5,), daemon=True).start()
    proc = psutil.Process()
    proc.cpu_percent()
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    print(f"Recording {args.seconds:.0f} s ...", flush=True)
    time.sleep(args.seconds)
    stop.set()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    cpu = proc.cpu_percent()  # % of one core, averaged since the first call

    OUT.mkdir(parents=True, exist_ok=True)
    tracks, report = {}, {"wall_s": round(wall, 2), "cpu_percent_of_one_core": round(cpu, 1)}
    for name, (x, reads) in store.items():
        report[name] = {
            "captured_s": round(len(x) / RATE, 2),
            "missing_s": round(wall - len(x) / RATE, 2),
            "longest_read_gap_s": round(max(b[0] - a[0] for a, b in zip(reads, reads[1:])), 3) if len(reads) > 1 else None,
            "rms_per_second": per_second_rms(x),
        }
        tracks[name] = soxr.resample(x, RATE, 16000)
        sf.write(OUT / f"{name}.wav", tracks[name], 16000)
    n = max(len(t) for t in tracks.values())
    mix = sum(np.pad(t, (0, n - len(t))) for t in tracks.values())
    sf.write(OUT / "mixed.wav", np.clip(mix, -1, 1), 16000)
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
