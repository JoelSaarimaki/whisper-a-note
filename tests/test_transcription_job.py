"""End-to-end job test with real models. Slow (~1-2 min): run with RUN_SLOW=1.

Uses the Phase 0 test dialogue (spikes/test_audio, not committed) and the `small` model
from the default Hugging Face cache.
"""
import os
import shutil
import time
from pathlib import Path

import pytest

from whisper_a_note.storage import Project
from whisper_a_note.transcription.job import TranscriptionJob
from whisper_a_note.transcription.models import is_available

AUDIO = Path(__file__).parent.parent / "spikes" / "test_audio" / "dialogue_short.wav"
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_SLOW") or not AUDIO.exists() or not is_available("small", None),
    reason="slow test: set RUN_SLOW=1 (needs spikes/test_audio and the small model)")


def wait(job, statuses, timeout=600):
    end = time.time() + timeout
    while job.status not in statuses:
        assert time.time() < end, f"timeout, status {job.status}"
        time.sleep(0.5)


def test_full_job_with_interrupt_and_resume(tmp_path):
    project = Project.create(tmp_path, "p")
    base = "dialogue"
    shutil.copy(AUDIO, project.folder / f"{base}.wav")
    job = TranscriptionJob(project, base, None)
    job.start("small", "en", "Kirsikka Logistics, Saarimäki, Procountor, Netvisor")
    while job.state.get("done_chunks", 0) < 1:
        assert job.status == "running", job.state.get("error")
        time.sleep(0.5)
    job.interrupt()
    assert job.status == "interrupted"

    job = TranscriptionJob(project, base, None)  # e.g. after an app restart
    assert job.status == "interrupted" and job.state["done_chunks"] >= 1
    job.resume()
    wait(job, ("done", "interrupted"))
    assert job.status == "done", job.state.get("error")
    segs = job.state["segments"]
    assert len(job.state["speakers"]) == 2 and len(segs) >= 10
    text = " ".join(s["text"] for s in segs)
    assert "Procountor" in text and "Netvisor" in text
    assert all(0 <= w["conf"] <= 1 for s in segs for w in s["words"])
