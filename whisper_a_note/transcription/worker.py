"""Worker processes: one for Whisper, one for pyannote (SPEC §8.2).

They run separately because their thread pools compete when sharing a process (~30%
slower diarization in Phase 0). Each reports through a multiprocessing queue; the parent
process is the only one writing the transcript file.
"""
from __future__ import annotations

import os
import traceback
from importlib import resources

RATE = 16000
PYANNOTE_PIPELINE = "speaker-diarization-community-1"


def _offline() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"  # NFR-01: libraries must not contact servers
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def whisper_worker(audio_path: str, chunks: list[tuple[int, int]] | None, first_chunk: int,
                   settings: dict, models_dir: str | None, queue) -> None:
    """Transcribe chunk by chunk, sending ('chunk', index, words, language, prob) per chunk."""
    try:
        _offline()
        from faster_whisper import WhisperModel, decode_audio

        from .chunks import plan_chunks, speech_regions

        audio = decode_audio(audio_path, sampling_rate=RATE)
        if chunks is None:
            duration_ms = len(audio) * 1000 // RATE
            planned = plan_chunks(speech_regions(audio), duration_ms, settings.get("muted_all", []))
            chunks = [(c.start_ms, c.end_ms) for c in planned]
            queue.put(("plan", chunks, duration_ms))
        cuda = gpu_available()
        model = WhisperModel(settings["model"], device="cuda" if cuda else "cpu",
                             compute_type="float16" if cuda else "int8",
                             download_root=models_dir, local_files_only=True)
        language = settings.get("language")  # None = auto-detect once, on the first chunk
        for i in range(first_chunk, len(chunks)):
            a, b = chunks[i]
            segments, info = model.transcribe(
                audio[a * RATE // 1000: b * RATE // 1000], language=language, vad_filter=True,
                word_timestamps=True, condition_on_previous_text=False,  # CTX-02
                hotwords=settings.get("context_used") or None)
            words = [{"w": w.word.strip(), "start_ms": a + int(w.start * 1000),
                      "end_ms": a + int(w.end * 1000), "conf": round(w.probability, 3)}
                     for s in segments for w in (s.words or []) if w.word.strip()]
            if language is None:
                language = info.language
            queue.put(("chunk", i, words, info.language, round(info.language_probability, 3)))
        queue.put(("whisper_done",))
    except Exception:
        queue.put(("error", "transcription", traceback.format_exc()))


def gpu_available() -> bool:
    """True only with the GPU requirements installed (CUDA build of PyTorch, TRN-07).

    An NVIDIA card alone is not enough: the default CPU install lacks the CUDA libraries.
    """
    import torch
    return torch.cuda.is_available()


def pyannote_path():
    return resources.files("whisper_a_note.models") / "pyannote" / PYANNOTE_PIPELINE


def diarize_worker(audio_path: str, num_speakers: int | None, queue) -> None:
    """Send ('turns', [{start_ms, end_ms, speaker}, …])."""
    try:
        _offline()
        import torch
        from faster_whisper import decode_audio
        from pyannote.audio import Pipeline

        audio = decode_audio(audio_path, sampling_rate=RATE)
        with resources.as_file(pyannote_path()) as path:  # PKG-2
            pipeline = Pipeline.from_pretrained(path)
        if gpu_available():
            pipeline.to(torch.device("cuda"))

        def hook(step_name, step_artifact, file=None, total=None, completed=None):
            if total and completed is not None:
                queue.put(("diarize_progress", step_name, completed / total))

        kwargs = {"num_speakers": num_speakers} if num_speakers else {}
        # In-memory waveform: pyannote never decodes the file itself (no system FFmpeg needed).
        out = pipeline({"waveform": torch.from_numpy(audio)[None], "sample_rate": RATE}, hook=hook, **kwargs)
        annotation = out.speaker_diarization
        turns = [{"start_ms": int(t.start * 1000), "end_ms": int(t.end * 1000), "speaker": spk}
                 for t, _, spk in annotation.itertracks(yield_label=True)]
        queue.put(("turns", turns))
    except Exception:
        queue.put(("error", "diarization", traceback.format_exc()))
