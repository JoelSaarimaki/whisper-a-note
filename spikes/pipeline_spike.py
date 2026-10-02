"""Phase 0 spike: faster-whisper + pyannote on CPU (SPEC §10).

Measures speed per stage, checks word confidence output, loads pyannote from local
files without a token, and compares ways of passing the context text (CTX-02).

    uv run python spikes/pipeline_spike.py --audio spikes/test_audio/kuulumiset.wav --language fi --context fi

Optional files next to the audio:
    <name>.truth.json      speaker turns -> speaker accuracy
    <name>.reference.txt   reference text -> word error rate (WER)
"""
import argparse
import json
import os
import platform
import re
import time
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
PYANNOTE_DIR = ROOT / "models" / "pyannote"

CONTEXTS = {
    "en": ("Customer interview with Kirsikka Logistics about invoicing. Participants: "
           "Joel Saarimäki, Aino Virtanen, Mikko Lehtonen. Systems and vendors: "
           "Procountor, Netvisor, Rossum, Schenker, ERP, OCR, e-invoice.",
           ["Saarimäki", "Kirsikka", "Procountor", "Virtanen", "Netvisor",
            "Schenker", "Rossum", "Lehtonen", "Aino", "Mikko"]),
    # Realistic context: what a user would know before the meeting, not the content.
    "fi": ("Viikkopalaverin kuulumiskierros. Osallistujat: Joel, Erkka, Jenni, Piia.",
           ["Erkka", "Jenni", "Piia", "Joel"]),
}


def load_pipeline(version: str):
    from pyannote.audio import Pipeline

    if version == "community-1":
        return Pipeline.from_pretrained(PYANNOTE_DIR / "speaker-diarization-community-1")
    # 3.1 refers to its sub-models by Hugging Face ID; point them at the local files instead.
    src = (PYANNOTE_DIR / "speaker-diarization-3.1" / "config.yaml").read_text()
    seg = (PYANNOTE_DIR / "segmentation-3.0" / "pytorch_model.bin").as_posix()
    emb = (PYANNOTE_DIR / "wespeaker-voxceleb-resnet34-LM" / "pytorch_model.bin").as_posix()
    cfg = src.replace("pyannote/segmentation-3.0", seg).replace("pyannote/wespeaker-voxceleb-resnet34-LM", emb)
    local = ROOT / "results" / "pyannote-3.1-local"
    local.mkdir(parents=True, exist_ok=True)
    (local / "config.yaml").write_text(cfg)
    return Pipeline.from_pretrained(local)


def diarize(audio: np.ndarray, version: str, num_speakers):
    import torch

    os.environ["HF_HUB_OFFLINE"] = "1"
    t0 = time.perf_counter()
    pipeline = load_pipeline(version)
    t_load = time.perf_counter() - t0
    t0 = time.perf_counter()
    # In-memory waveform: avoids pyannote's own file decoding (torchcodec needs a system FFmpeg).
    kwargs = {"num_speakers": num_speakers} if num_speakers else {}
    out = pipeline({"waveform": torch.from_numpy(audio)[None], "sample_rate": 16000}, **kwargs)
    t_run = time.perf_counter() - t0
    annotation = getattr(out, "speaker_diarization", out)  # 4.x returns a DiarizeOutput
    turns = [{"start": t.start, "end": t.end, "speaker": spk}
             for t, _, spk in annotation.itertracks(yield_label=True)]
    return turns, t_load, t_run


def transcribe(audio, model_name, language, prompt_mode, context, cond_prev):
    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    t_load = time.perf_counter() - t0
    kwargs = {}
    if prompt_mode in ("initial", "both"):
        kwargs["initial_prompt"] = context
    if prompt_mode in ("hotwords", "both"):
        kwargs["hotwords"] = context
    t0 = time.perf_counter()
    segments, info = model.transcribe(audio, language=language, vad_filter=True, word_timestamps=True,
                                      condition_on_previous_text=cond_prev, **kwargs)
    words = []
    for seg in segments:  # generator: decoding happens here
        for w in seg.words:
            words.append({"w": w.word.strip(), "start": w.start, "end": w.end, "conf": round(w.probability, 3)})
    t_run = time.perf_counter() - t0
    return words, info, t_load, t_run


def assign_speakers(words, turns):
    for w in words:
        best, best_ov = None, 0.0
        for t in turns:
            ov = min(w["end"], t["end"]) - max(w["start"], t["start"])
            if ov > best_ov:
                best, best_ov = t["speaker"], ov
        w["speaker"] = best
    segments = []
    for w in words:
        if segments and segments[-1]["speaker"] == w["speaker"]:
            segments[-1]["words"].append(w)
            segments[-1]["end"] = w["end"]
        else:
            segments.append({"speaker": w["speaker"], "start": w["start"], "end": w["end"], "words": [w]})
    return segments


def speaker_accuracy(words, truth):
    """Share of words whose (majority-mapped) speaker matches the reference turns."""
    def true_spk(t):
        for g in truth:
            if g["start"] - 0.3 <= t <= g["end"] + 0.3:
                return g["speaker"]
    pairs = [(w["speaker"], true_spk((w["start"] + w["end"]) / 2)) for w in words]
    pairs = [p for p in pairs if p[1]]
    mapping = {}
    for spk in {p[0] for p in pairs}:
        votes = [p[1] for p in pairs if p[0] == spk]
        mapping[spk] = max(set(votes), key=votes.count)
    return sum(mapping.get(a) == b for a, b in pairs) / max(len(pairs), 1)


def normalize(text):
    text = unicodedata.normalize("NFC", text.lower())
    return re.sub(r"[^\w\s]", " ", text).split()


def wer(ref, hyp):
    """Word error rate via Levenshtein distance on normalized words."""
    r, h = normalize(ref), normalize(hyp)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / max(len(r), 1)


def term_hits(words, duration, terms):
    """Correctly spelled key terms, split by first and second half of the audio."""
    halves = [[], []]
    for w in words:
        halves[0 if w["start"] < duration / 2 else 1].append(w["w"])
    def count(ws):
        text = " ".join(ws)
        return {t: len(re.findall(re.escape(t), text)) for t in terms}
    return count(halves[0]), count(halves[1])


def max_repeats(words):
    """Longest run of an identical 4-word phrase repeated back to back (hallucination loops)."""
    ws = [w["w"].lower() for w in words]
    best = 1
    for i in range(len(ws) - 8):
        n, j = 1, i + 4
        while ws[j:j + 4] == ws[i:i + 4] and j + 4 <= len(ws):
            n, j = n + 1, j + 4
        best = max(best, n)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--model", default="small")
    ap.add_argument("--language", default="en")
    ap.add_argument("--context", default="en", choices=sorted(CONTEXTS))
    ap.add_argument("--prompt-mode", default="both", choices=["none", "initial", "hotwords", "both"])
    ap.add_argument("--cond-prev", default="on", choices=["on", "off"])
    ap.add_argument("--pyannote", default="community-1", choices=["community-1", "3.1", "skip"])
    ap.add_argument("--num-speakers", type=int, default=0)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    audio, sr = sf.read(args.audio, dtype="float32")
    assert sr == 16000 and audio.ndim == 1, "spike expects 16 kHz mono"
    duration = len(audio) / sr
    base = Path(args.audio).with_suffix("")
    truth = json.loads(Path(f"{base}.truth.json").read_text()) if Path(f"{base}.truth.json").exists() else None
    ref = Path(f"{base}.reference.txt").read_text(encoding="utf-8") if Path(f"{base}.reference.txt").exists() else None
    context, terms = CONTEXTS[args.context]

    words, info, wl, wr = transcribe(audio, args.model, args.language or None, args.prompt_mode,
                                     context, args.cond_prev == "on")
    result = {
        "audio": args.audio, "duration_s": round(duration, 1), "model": args.model,
        "prompt_mode": args.prompt_mode, "cond_prev": args.cond_prev, "language": info.language,
        "cpu": platform.processor(), "cpu_count": os.cpu_count(),
        "whisper_load_s": round(wl, 1), "whisper_run_s": round(wr, 1),
        "whisper_rtf": round(wr / duration, 3), "words": len(words),
        "low_conf_share": round(sum(w["conf"] < 0.7 for w in words) / max(len(words), 1), 3),
        "max_phrase_repeats": max_repeats(words),
    }
    if ref:
        result["wer"] = round(wer(ref, " ".join(w["w"] for w in words)), 3)
    h1, h2 = term_hits(words, duration, terms)
    result["terms_first_half"], result["terms_second_half"] = h1, h2

    if args.pyannote != "skip":
        turns, dl, dr = diarize(audio, args.pyannote, args.num_speakers or None)
        segments = assign_speakers(words, turns)
        result.update({
            "pyannote": args.pyannote, "num_speakers_given": args.num_speakers or None,
            "pyannote_load_s": round(dl, 1), "pyannote_run_s": round(dr, 1),
            "pyannote_rtf": round(dr / duration, 3),
            "speakers_found": len({t["speaker"] for t in turns}), "segments": len(segments),
        })
        if truth:
            result["speaker_word_accuracy"] = round(speaker_accuracy(words, truth), 3)
    else:
        segments = [{"speaker": None, "start": 0, "end": duration, "words": words}]

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    name = f"{base.name}_{args.model}_{args.prompt_mode}_cp-{args.cond_prev}_{args.pyannote}{args.tag}"
    dump = json.dumps({"summary": result, "segments": segments}, indent=1, ensure_ascii=False,
                      default=lambda o: o.item() if hasattr(o, "item") else str(o))
    (out / f"{name}.json").write_text(dump, encoding="utf-8")
    with open(out / f"{name}.txt", "w", encoding="utf-8") as f:
        for s in segments:
            if s["words"]:
                f.write(f"[{s['words'][0]['start']:7.1f}] {s['speaker']}: " + " ".join(
                    f"*{w['w']}*" if w["conf"] < 0.7 else w["w"] for w in s["words"]) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
