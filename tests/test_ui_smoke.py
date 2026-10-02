"""UI smoke test without a display: Review mode, notes, export, and a Recording mode session."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QApplication, QMessageBox

from whisper_a_note import paths
from whisper_a_note.storage import NotesFile, Project, RecordingFile
from whisper_a_note.storage.jsonfile import write_json
from tests.test_recorder import FakeSource


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(f"warning shown: {a[1:]}"))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: pytest.fail(f"error shown: {a[1:]}"))
    import whisper_a_note.ui.recording_window as rw
    import whisper_a_note.ui.widgets as widgets
    monkeypatch.setattr(widgets, "SoundcardSource", lambda name, loopback: FakeSource("Loopback" if loopback else "Mic"))
    monkeypatch.setattr(rw, "SoundcardSource", lambda name, loopback: FakeSource("Loopback" if loopback else "Mic"))
    qapp = QApplication.instance() or QApplication([])
    from whisper_a_note.ui import theme
    theme.apply(qapp)
    return qapp


def pump(app, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def make_project(root):
    project = Project.create(root, "2026-10-02 Customer interview")
    base = "2026-10-02_1400"
    sf.write(project.path(base, "flac"), np.zeros(16000 * 20, np.float32), 16000)
    RecordingFile(project.path(base, "recording.json")).update(duration_ms=20_000, context="Participants: Anna")
    w = lambda t, a, b, c: {"w": t, "start_ms": a, "end_ms": b, "conf": c}
    write_json(project.path(base, "transcript.json"), {
        "status": "done", "model": "large-v3-turbo", "language": "en",
        "speakers": {"SPEAKER_00": "Speaker 1"},
        "segments": [{"start_ms": 1000, "end_ms": 5000, "speaker": "SPEAKER_00", "language": "en",
                      "text": "Hello there.", "words": [w("Hello", 1000, 1500, 0.9), w("there.", 1500, 2000, 0.4)]}]})
    NotesFile(project.path(base, "notes.json"), 20_000).add("First note", 3000)
    return project, base


def test_review_mode_notes_and_export(app, tmp_path):
    from whisper_a_note.ui.app import Controller
    project, base = make_project(tmp_path / "projects")
    ctl = Controller(app)
    ctl.settings.projects_folder = str(tmp_path / "projects")
    ctl.show_review(project)
    pump(app)
    review = ctl.review
    assert review.base == base and review.btn["restart"].isVisible() and not review.btn["start"].isVisible()
    assert len(review.timeline.rows) == 1  # one segment row with its note attached
    review.note_input.setText("Added in review")
    review.note_time.setText("00:12")
    review._add_note()
    assert [n.text for n in review.notes.notes] == ["First note", "Added in review"]
    review._note_action("delete", review.notes.notes[0].id)
    review._restore()
    assert len(review.notes.notes) == 2
    review.recording_context.setPlainText("Participants: Anna, Joel")
    review._save_contexts()
    assert RecordingFile(project.path(base, "recording.json")).meta.context == "Participants: Anna, Joel"
    review._export()
    text = (project.folder / "exports" / f"{base}.md").read_text(encoding="utf-8")
    assert "*there.*" in text and "> **[00:00:12] Note:** Added in review" in text
    review.close()


def test_recording_mode_session(app, tmp_path):
    from whisper_a_note.ui.recording_window import RecordingWindow
    from whisper_a_note.ui.settings import AppSettings
    from whisper_a_note.ui.setup_dialog import SetupResult
    project = Project.create(tmp_path, "p")
    setup = SetupResult(project, "Participants: Anna", None, True, None, None)
    win = RecordingWindow(AppSettings(projects_folder=str(tmp_path)), setup, draft="pre-written")
    win.input.returnPressed.emit()  # before Start: stays as a draft (NOTE-02a)
    assert win.input.text() == "pre-written" and win.notes is None
    win.start()
    pump(app, 0.6)
    win.input.returnPressed.emit()  # the draft is submitted after Start
    assert [n.text for n in win.notes.notes] == ["pre-written"] and win.input.text() == ""
    win.mute_all.setChecked(True)
    assert win.banner.isVisibleTo(win)
    pump(app, 0.3)
    win.mute_all.setChecked(False)
    win._start_end_clicked()  # End -> grace period
    assert win.state == "ending" and win.start_end.text().startswith("Cancel")
    win._start_end_clicked()  # Cancel
    assert win.state == "recording"
    pump(app, 0.3)
    win._start_end_clicked()
    for _ in range(5):
        win._grace_tick()
    deadline = time.time() + 10
    while win.state != "ended" and time.time() < deadline:
        pump(app, 0.1)
    assert win.state == "ended" and win.duration_ms > 800
    win.input.setText("Closing thought")
    win.input.returnPressed.emit()
    win.input.setText("Closing thought, refined")
    win.input.returnPressed.emit()
    closing = [n for n in win.notes.notes if n.time_ms == win.duration_ms]
    assert [n.text for n in closing] == ["Closing thought, refined"]
    assert win.input.text() == "Closing thought, refined"
    win._delete(closing[0].id)  # deleting frees the slot and clears the input
    assert win.input.text() == "" and win.closing_id is None
    meta = RecordingFile(project.path(win.base, "recording.json")).meta
    assert meta.context == "Participants: Anna" and any(m.source == "all" for m in meta.mutes)
    win.close()
