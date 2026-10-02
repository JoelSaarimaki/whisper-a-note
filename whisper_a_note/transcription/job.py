"""A transcription job for one recording: Start, Interrupt, Resume, Stop, Restart (TRN-04).

State lives in `<base>.transcript.json`. While the job runs, the file also holds the chunk
plan and the words transcribed so far, so an interrupted job resumes where it stopped,
also after the app was closed (TRN-11). Resume always uses the settings saved when the
job started (§5.6).
"""
from __future__ import annotations

import multiprocessing
import queue as queue_mod
import threading
from pathlib import Path
from typing import Callable

from ..storage import Project, RecordingFile
from ..storage.jsonfile import FileStamp, read_json, write_json
from .merge import assign_speakers, build_segments, speaker_labels
from .worker import diarize_worker, whisper_worker

STAGES = ("transcribing", "diarizing")


class JobError(Exception):
    pass


def combined_context(project_context: str, recording_context: str) -> str:
    """Project context first, then the recording context (CTX-06)."""
    return "\n".join(t.strip() for t in (project_context, recording_context) if t.strip())


class TranscriptionJob:
    def __init__(self, project: Project, base: str, models_dir: Path | None,
                 on_change: Callable[[], None] | None = None):
        self.project, self.base = project, base
        self.path = project.path(base, "transcript.json")
        self.models_dir = models_dir
        self.on_change = on_change or (lambda: None)
        self._lock = threading.RLock()
        self._proc = None
        self._generation = 0
        self.state: dict = {}
        self._stamp: FileStamp | None = None
        self.load()

    # --- state ---------------------------------------------------------------------------

    def load(self) -> None:
        data, self._stamp = read_json(self.path)  # raises UnreadableFileError (NFR-09)
        self.state = data or {}
        if self.state.get("status") == "running" and self._proc is None:
            self.state["status"] = "interrupted"  # left running by a crash (§7.2)

    @property
    def status(self) -> str:
        return self.state.get("status", "idle")

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def progress(self) -> tuple[str, float]:
        """(stage, 0..1) for the UI (TRN-05)."""
        s = self.state
        if s.get("status") == "done":
            return "done", 1.0
        if s.get("stage") == "diarizing":
            return "diarizing", s.get("diarize_fraction", 0.0)
        chunks = s.get("chunks")
        if not chunks:
            return "preparing", 0.0
        total = sum(b - a for a, b in chunks) or 1
        done = sum(b - a for a, b in chunks[: s.get("done_chunks", 0)])
        return "transcribing", done / total

    # --- controls ------------------------------------------------------------------------

    def start(self, model: str, language: str | None, context: str, num_speakers: int | None = None) -> None:
        """language None = auto-detect once (§5.6.1)."""
        with self._lock:
            if self.status not in ("idle",):
                raise JobError(f"cannot start: job is {self.status}")
            meta = RecordingFile(self.project.path(self.base, "recording.json")).meta
            self.state = {
                "status": "running", "stage": "transcribing", "error": None,
                "model": model, "language_mode": "auto" if language is None else "fixed",
                "language": language, "context_used": context, "num_speakers": num_speakers,
                "muted_all": [[m.start_ms, m.end_ms] for m in meta.mutes
                              if m.source == "all" and m.end_ms is not None],
                "chunks": None, "done_chunks": 0, "words": [], "speakers": {}, "segments": [],
            }
            self._save()
            self._launch()

    def interrupt(self) -> None:
        with self._lock:
            if self.status != "running":
                return
            self._kill()
            self.state["status"] = "interrupted"
            self._save()

    def resume(self) -> None:
        with self._lock:
            if self.status != "interrupted":
                raise JobError(f"cannot resume: job is {self.status}")
            self.state.update(status="running", error=None)
            self._save()
            self._launch()

    def stop(self) -> None:
        """End the job; results so far are kept and marked incomplete."""
        with self._lock:
            if self.status not in ("running", "interrupted"):
                return
            self._kill()
            if self.state.get("words"):
                words = [{**w, "speaker": None} for w in self.state["words"]]
                self.state["segments"] = build_segments(words, self.state.get("language"), None)
            self._finish("stopped")

    def restart(self, model: str, language: str | None, context: str, num_speakers: int | None = None) -> None:
        """Clears previous results (the UI asks for confirmation first, TRN-04)."""
        with self._lock:
            self._kill()
            self.state = {}
            self.start(model, language, context, num_speakers)

    def close(self) -> None:
        """App closing: a running job is interrupted so it can be resumed later (TRN-11)."""
        self.interrupt()

    # --- processes -----------------------------------------------------------------------

    def _audio_path(self) -> str:
        path = self.project.audio_path(self.base)
        if path is None:
            raise JobError("the recording has no audio file")
        return str(path)

    def _launch(self) -> None:
        ctx = multiprocessing.get_context("spawn")  # PKG-5
        q = ctx.Queue()
        if self.state["stage"] == "transcribing":
            args = (self._audio_path(), self.state["chunks"], self.state["done_chunks"],
                    {k: self.state[k] for k in ("model", "language", "context_used", "muted_all")},
                    str(self.models_dir) if self.models_dir else None, q)
            target = whisper_worker
        else:
            self.state["diarize_fraction"] = 0.0
            args, target = (self._audio_path(), self.state.get("num_speakers"), q), diarize_worker
        self._generation += 1
        self._proc = ctx.Process(target=target, args=args, daemon=True)
        self._proc.start()
        threading.Thread(target=self._monitor, args=(self._proc, q, self._generation), daemon=True).start()

    def _kill(self) -> None:
        self._generation += 1  # the old monitor thread stops handling messages
        if self._proc is not None and self._proc.is_alive():
            self._proc.kill()
            self._proc.join(timeout=5)
        self._proc = None

    def _monitor(self, proc, q, generation) -> None:
        while True:
            try:
                msg = q.get(timeout=0.5)
            except queue_mod.Empty:
                if self._generation != generation:
                    return
                if not proc.is_alive():
                    msg = ("error", "worker", f"worker process exited unexpectedly (code {proc.exitcode})")
                else:
                    continue
            with self._lock:
                if self._generation != generation:
                    return
                done = self._handle(msg)
            self.on_change()
            if done:
                return

    def _handle(self, msg) -> bool:
        """Apply one worker message; returns True when this worker is finished."""
        kind, s = msg[0], self.state
        if kind == "plan":
            s["chunks"], s["duration_ms"] = msg[1], msg[2]
        elif kind == "chunk":
            _, i, words, language, prob = msg
            s["words"] = [w for w in s["words"] if w["start_ms"] < s["chunks"][i][0]] + words
            s["done_chunks"] = i + 1
            if s.get("language") is None:
                s["language"], s["language_prob"] = language, prob
        elif kind == "whisper_done":
            s["stage"] = "diarizing"
            self._save()
            self._launch()
            return True
        elif kind == "diarize_progress":
            s["diarize_fraction"] = msg[2]
            return False  # not worth a file write
        elif kind == "turns":
            words = assign_speakers(s["words"], msg[1])
            labels = speaker_labels(words)
            s["speakers"] = labels
            s["segments"] = build_segments(words, s.get("language"), s.get("language_prob"))
            self._proc = None
            self._finish("done")
            return True
        elif kind == "error":
            self._proc = None
            s.update(status="interrupted", error=f"{msg[1]} failed:\n{msg[2]}")
            self._save()
            return True
        self._save()
        return False

    def _finish(self, status: str) -> None:
        for key in ("chunks", "done_chunks", "words", "muted_all", "diarize_fraction", "stage"):
            self.state.pop(key, None)
        self.state["status"] = status
        self._save()

    def _save(self) -> None:
        self._stamp = write_json(self.path, self.state)
