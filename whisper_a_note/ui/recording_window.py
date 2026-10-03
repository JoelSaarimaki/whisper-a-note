"""Recording mode: compact window used during the meeting (SPEC §6.1)."""
from __future__ import annotations

import shutil
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..audio.recorder import Recorder
from ..audio.sources import SoundcardSource
from ..storage import NotesFile
from .settings import AppSettings
from .setup_dialog import SetupResult
from .widgets import LevelMeter, NoteDialog, SoundCheck, clock

GRACE_S = 5          # REC-04a
LOW_DISK_BYTES = 1 << 30  # REC-18


class RecordingWindow(QWidget):
    review_requested = Signal()
    cancel_requested = Signal()    # left before Start: nothing is recorded (REC-20)
    new_recording_requested = Signal()
    _finished = Signal(int, str)  # duration, error

    def __init__(self, settings: AppSettings, setup: SetupResult, draft: str = ""):
        super().__init__()
        self.settings, self.setup = settings, setup
        self.project = setup.project
        self.setWindowTitle("Recording — Whisper A Note")
        self.setMinimumWidth(240)  # can be a thin strip (§6.1)
        self.state = "ready"  # ready → recording ⇄ ending → saving → ended
        self.recorder: Recorder | None = None
        self.base: str | None = None
        self.notes: NotesFile | None = None
        self.closing_id: str | None = None
        self.duration_ms: int | None = None
        self.pre_mutes = {"mic": False, "system": False, "all": False}
        self.countdown = 0
        self._shown_events = 0

        self.header = QLabel(self.project.settings.name)
        self.header.setWordWrap(True)
        self.header.setStyleSheet("font-weight: bold;")
        self.banner = QLabel("Muted – off the record")
        self.banner.setObjectName("banner")
        self.banner.hide()
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        self.history = QListWidget()
        self.history.setWordWrap(True)
        self.history.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._menu)
        self.history.itemDoubleClicked.connect(lambda item: self._edit(item.data(Qt.UserRole)))
        self.undo = QPushButton("Note deleted – Undo")
        self.undo.setFlat(True)
        self.undo.hide()
        self.undo.clicked.connect(self._restore)
        self.input = QLineEdit(draft)
        self.input.setPlaceholderText("Type a note…")
        self.input.returnPressed.connect(self._submit)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)

        self.elapsed = QLabel("00:00")
        self.elapsed.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self.start_end = QPushButton("● Start")
        self.start_end.setObjectName("primary")
        self.start_end.clicked.connect(self._start_end_clicked)
        self.mute_all = QPushButton("Mute all")
        self.mute_all.setObjectName("muteAll")
        self.mute_all.setCheckable(True)
        self.mute_all.toggled.connect(lambda on: self._set_mute("all", on))
        self.review = QPushButton("Cancel")  # "Review" once a recording has ended
        self.review.clicked.connect(
            lambda: (self.cancel_requested if self.state == "ready" else self.review_requested).emit())
        self.meters, self.mute_buttons = {}, {}
        rows = []
        for kind, label in (("mic", "MIC"), ("system", "SYS")):
            meter, btn = LevelMeter(), QPushButton("Mute")
            btn.setCheckable(True)
            btn.toggled.connect(lambda on, k=kind: self._set_mute(k, on))
            self.meters[kind], self.mute_buttons[kind] = meter, btn
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(meter, 1)
            row.addWidget(btn)
            rows.append(row)
        headphones = QLabel("Tip: use headphones, so the mic does not pick up the other participants.")
        headphones.setObjectName("hint")
        headphones.setWordWrap(True)

        controls = QHBoxLayout()
        controls.addWidget(self.elapsed)
        controls.addStretch()
        controls.addWidget(self.mute_all)
        controls.addWidget(self.start_end)
        lay = QVBoxLayout(self)
        lay.addWidget(self.header)
        lay.addWidget(self.banner)
        lay.addWidget(self.error)
        lay.addWidget(self.history, 1)
        lay.addWidget(self.undo)
        lay.addWidget(self.input)
        lay.addWidget(self.hint)
        lay.addLayout(controls)
        for row in rows:
            lay.addLayout(row)
        bottom = QHBoxLayout()
        bottom.addWidget(headphones, 1)
        bottom.addWidget(self.review)
        lay.addLayout(bottom)

        QShortcut(QKeySequence.Undo, self, activated=self._restore)
        self.timer = QTimer(self, interval=50, timeout=self._tick)
        self.grace = QTimer(self, interval=1000, timeout=self._grace_tick)
        self._finished.connect(self._on_finished)
        self.check = SoundCheck(setup.mic_device, setup.system_device)
        self.check.start()
        self.timer.start()
        self._update_ui()
        self.input.setFocus()

    # --- recording control ---------------------------------------------------------------

    def _start_end_clicked(self) -> None:
        if self.state == "ready":
            self.start()
        elif self.state == "recording":
            self.request_end()
        elif self.state == "ending":
            self.cancel_end()
        elif self.state == "ended":
            self.new_recording_requested.emit()

    def start(self) -> None:
        free = shutil.disk_usage(self.project.folder).free
        if free < LOW_DISK_BYTES and QMessageBox.question(
                self, "Low disk space", f"Only {free / 1e9:.1f} GB free. Start recording anyway?") != QMessageBox.Yes:
            return
        self.check.stop()
        # recording.json language: null = project setting, "auto" = auto-detect, else a code
        language = None if self.setup.use_project_language else (self.setup.language or "auto")
        self.base = self.project.new_base_name(title=self.setup.recording_name)
        self.recorder = Recorder(
            self.project, self.base,
            SoundcardSource(self.setup.mic_device, loopback=False),
            SoundcardSource(self.setup.system_device, loopback=True),
            context=self.setup.recording_context, language=language)
        self.notes = NotesFile(self.project.path(self.base, "notes.json"), duration_ms=None)
        self.recorder.start(mutes=self.pre_mutes)
        self.state = "recording"
        self.header.setText(f"{self.project.settings.name}\n{self.base}")
        self._update_ui()

    def request_end(self) -> None:
        self.recorder.request_end()
        self.state, self.countdown = "ending", GRACE_S
        self.grace.start()
        self._update_ui()

    def cancel_end(self) -> None:
        self.grace.stop()
        self.recorder.cancel_end()
        self.state = "recording"
        self._update_ui()

    def _grace_tick(self) -> None:
        self.countdown -= 1
        if self.countdown <= 0:
            self.grace.stop()
            self._finish()
        else:
            self._update_ui()

    def _finish(self) -> None:
        self.state = "saving"
        self._update_ui()
        recorder = self.recorder

        def work():  # finalizing a long recording takes a few seconds
            try:
                self._finished.emit(recorder.finish(), "")
            except Exception as e:  # noqa: BLE001 - shown to the user
                self._finished.emit(-1, str(e))
        self._saving = threading.Thread(target=work)
        self._saving.start()

    def _on_finished(self, duration: int, error: str) -> None:
        if error:
            QMessageBox.critical(self, "Saving the recording failed",
                                 f"{error}\n\nThe recorded audio is kept and will be recovered at the next start.")
        self.duration_ms = max(duration, 0)
        self.state = "ended"
        if self.notes:
            self.notes.set_duration(self.duration_ms)
        self._refresh_notes()
        self._update_ui()

    def _set_mute(self, kind: str, on: bool) -> None:
        if self.recorder and self.state in ("recording", "ending"):
            self.recorder.set_mute(kind, on)
        else:
            self.pre_mutes[kind] = on  # applies from the start (REC-03)
        self._update_ui()

    # --- notes ---------------------------------------------------------------------------

    def _submit(self) -> None:
        text = self.input.text()
        if text.startswith("/") and not text.startswith("//"):
            self._command(text.strip().lower())
            return
        if text.startswith("//"):
            text = text[1:]
        if not text.strip():
            return
        if self.state == "ready":
            return  # pre-written draft stays in the input (NOTE-02a)
        if self.state == "recording":
            self.notes.add(text, self.recorder.audio_time_ms())
            self.input.clear()
        elif self.state in ("ending", "ended"):
            self._closing_note(text)
        self._refresh_notes()

    def _closing_note(self, text: str) -> None:
        """One closing note at the end, replaced by each further Enter (NOTE-02b)."""
        end = self.duration_ms if self.state == "ended" else self.recorder.meta_file.meta.end_requested_ms
        note = None
        if self.closing_id:
            try:
                note = self.notes.get(self.closing_id)
            except KeyError:
                note = None
        if note is not None and note.time_ms == end:
            self.notes.edit_text(note.id, text)
        else:
            self.closing_id = self.notes.add(text, end).id
        # the text stays in the input so it can be refined

    def _command(self, cmd: str) -> None:
        """Chat commands (§5.5). /end has no short form."""
        if cmd in ("/start", "/s") and self.state == "ready":
            self.input.clear()
            self.start()
        elif cmd == "/end" and self.state == "recording":
            self.input.clear()
            self.request_end()
        elif cmd in ("/mute", "/m"):
            self.input.clear()
            self.mute_all.toggle()
        else:
            self.hint.setText(f"Unknown or unavailable command: {cmd}")
            self.hint.show()

    def _refresh_notes(self) -> None:
        self.history.clear()
        if not self.notes:
            return
        for n in self.notes.notes:
            item = QListWidgetItem(f"{clock(n.time_ms)}  {n.text}")
            item.setData(Qt.UserRole, n.id)
            self.history.addItem(item)
        self.history.scrollToBottom()

    def _menu(self, pos) -> None:
        item = self.history.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction("Edit text", lambda: self._edit(item.data(Qt.UserRole)))
        menu.addAction("Delete", lambda: self._delete(item.data(Qt.UserRole)))
        menu.exec(self.history.mapToGlobal(pos))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete and self.history.hasFocus() and self.history.currentItem():
            self._delete(self.history.currentItem().data(Qt.UserRole))
        else:
            super().keyPressEvent(e)

    def _edit(self, note_id: str) -> None:
        note = self.notes.get(note_id)
        dialog = NoteDialog(note.text, parent=self)
        if not dialog.exec():
            return
        text = dialog.note_text()
        if text != note.text:
            self.notes.edit_text(note_id, text)
            if note_id == self.closing_id:
                self.input.setText(text)
            self._refresh_notes()

    def _delete(self, note_id: str) -> None:
        """No confirmation; the last deleted note can be restored (NOTE-06a)."""
        self.notes.delete(note_id)
        if note_id == self.closing_id:
            self.closing_id = None
            self.input.clear()
        self.undo.show()
        self._refresh_notes()

    def _restore(self) -> None:
        if self.notes and self.notes.restore_last_deleted():
            self.undo.hide()
            self._refresh_notes()

    # --- display -------------------------------------------------------------------------

    def _tick(self) -> None:
        if self.recorder and self.state in ("recording", "ending"):
            for kind, level in self.recorder.levels().items():
                self.meters[kind].set_level(level.peak, level.muted, level.lost)
            self.elapsed.setText(clock(self.recorder.audio_time_ms()))
            if len(self.recorder.events) > self._shown_events:
                self._shown_events = len(self.recorder.events)
                self.error.setText(self.recorder.events[-1])
                self.error.setVisible("lost" in self.recorder.events[-1])
            if self.recorder.failed and self.state == "recording":
                QMessageBox.critical(self, "Recording stopped", f"Recording stopped: {self.recorder.failed}\n"
                                     "Everything recorded so far is kept.")
                self._finish()
        elif self.state == "ready":
            for kind, (peak, lost) in self.check.levels.items():
                muted = self.pre_mutes["all"] or self.pre_mutes[kind]
                self.meters[kind].set_level(peak, muted, lost)

    def _update_ui(self) -> None:
        s = self.state
        recording = self.recorder is not None and s in ("recording", "ending")
        muted_all = self.recorder.muted_all if recording else self.pre_mutes["all"]
        self.banner.setVisible(muted_all)
        self.start_end.setEnabled(s != "saving")
        self.start_end.setObjectName({"ready": "primary", "recording": "danger", "ending": "primary",
                                      "ended": "primary"}.get(s, "primary"))
        self.start_end.setText({"ready": "● Start", "recording": "■ End", "ending": f"Cancel ({self.countdown})",
                                "saving": "Saving…", "ended": "New recording"}[s])
        self.start_end.style().unpolish(self.start_end)
        self.start_end.style().polish(self.start_end)
        self.review.setEnabled(s in ("ready", "ended"))
        self.review.setText("Cancel" if s == "ready" else "Review")
        self.mute_all.setEnabled(s in ("ready", "recording", "ending"))
        for b in self.mute_buttons.values():
            b.setEnabled(s in ("ready", "recording", "ending"))
        self.hint.setText({
            "ready": "Notes can be submitted once recording starts. You can pre-write one now.",
            "recording": "",
            "ending": f"Ending recording… {self.countdown} s. Press Cancel to keep recording.",
            "saving": "Saving the recording…",
            "ended": "",
        }[s])
        self.hint.setVisible(bool(self.hint.text()))
        if s == "ended":
            self.elapsed.setText(clock(self.duration_ms or 0))
            for m in self.meters.values():
                m.set_level(0.0)

    # --- window --------------------------------------------------------------------------

    def draft(self) -> str:
        """Unsent text, kept when leaving before Start (REC-20)."""
        return self.input.text() if self.state == "ready" else ""

    def closeEvent(self, e):
        if self.state == "recording":
            if QMessageBox.question(self, "End recording?", "A recording is running. End it and close?") \
                    != QMessageBox.Yes:
                e.ignore()
                return
            self.state = "ending"
        if self.state == "ending":  # closing during the grace period completes the ending
            self.grace.stop()
            self.recorder.finish()
        if self.state == "saving":
            self._saving.join()
        self.timer.stop()
        self.check.stop()
        super().closeEvent(e)
