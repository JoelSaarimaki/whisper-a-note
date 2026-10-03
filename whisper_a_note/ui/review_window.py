"""Review mode: projects, recordings, context, transcription, timeline and export (SPEC §6.2)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QVBoxLayout, QWidget)

from .. import paths
from ..audio.finalize import finalize_recording, is_unfinished
from ..export import RecordingExport
from ..storage import NotesFile, Project, RecordingFile, UnreadableFileError
from ..storage.jsonfile import read_json
from ..storage.project import default_project_name
from ..transcription import models
from ..transcription.job import TranscriptionJob, combined_context
from . import languages
from .timeline import Player, Timeline
from .widgets import NoteDialog, clock, parse_clock

# Phase 0 speeds (share of audio length) on a fast laptop, made conservative (TRN-07a).
DEFAULT_RTF = {"large-v3-turbo": 0.26, "large-v3": 0.98, "medium": 0.55, "small": 0.24}
DIARIZE_RTF = 0.32
CONSERVATIVE = 1.6


class ReviewWindow(QMainWindow):
    new_recording_requested = Signal()
    settings_requested = Signal()
    _job_changed = Signal()
    _recovered = Signal(str)

    def __init__(self, app_ctl):
        super().__init__()
        self.ctl = app_ctl
        self.settings = app_ctl.settings
        self.setWindowTitle("Whisper A Note")
        self.project: Project | None = None
        self.base: str | None = None
        self.notes: NotesFile | None = None
        self.meta_file: RecordingFile | None = None
        self.writable = False
        self.job: TranscriptionJob | None = None
        self._job_started = None

        # --- sidebar ---
        self.project_combo = QComboBox()
        self.project_combo.activated.connect(lambda _: self.open_project(Path(self.project_combo.currentData())))
        open_btn = QPushButton("Open folder…")
        open_btn.clicked.connect(self._open_folder)
        new_btn = QPushButton("New project…")
        new_btn.clicked.connect(self._new_project)
        self.project_context = QPlainTextEdit()
        self.project_context.setPlaceholderText("Project context: topic, names, terms (shared by all recordings)")
        self.project_language = QComboBox()
        self.recordings = QListWidget()
        self.recordings.currentItemChanged.connect(lambda cur, _: self.open_recording(cur.data(Qt.UserRole) if cur else None))
        self.recording_context = QPlainTextEdit()
        self.recording_context.setPlaceholderText("Recording context: participants, topics, other notes")
        self.recording_language = QComboBox()
        self.fill_language_lists()
        ctx_hint = QLabel("Keep both context texts short (about 100 words together). Changes apply to the next transcription.")
        ctx_hint.setObjectName("hint")
        ctx_hint.setWordWrap(True)

        side = QWidget()
        side.setMinimumWidth(260)
        sl = QVBoxLayout(side)
        sl.addWidget(QLabel("<b>Project</b>"))
        sl.addWidget(self.project_combo)
        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addWidget(new_btn)
        sl.addLayout(row)
        sl.addWidget(self.project_context, 1)
        sl.addWidget(QLabel("Language"))
        sl.addWidget(self.project_language)
        sl.addWidget(QLabel("<b>Recordings</b>"))
        sl.addWidget(self.recordings, 2)
        sl.addWidget(self.recording_context, 1)
        sl.addWidget(QLabel("Recording language"))
        sl.addWidget(self.recording_language)
        sl.addWidget(ctx_hint)

        # --- toolbar ---
        self.trn_status = QLabel("")
        self.trn_progress = QProgressBar()
        self.trn_progress.setFixedWidth(160)
        self.trn_progress.hide()
        self.btn = {}
        for key, label in (("start", "Transcribe"), ("interrupt", "Interrupt"), ("resume", "Resume"),
                           ("stop", "Stop"), ("restart", "Restart")):
            b = QPushButton(label)
            b.clicked.connect(getattr(self, f"_trn_{key}"))
            self.btn[key] = b
        self.btn["start"].setObjectName("primary")
        export_btn = QPushButton("Export")
        export_btn.setToolTip("Write Markdown and confidence JSON to the project's exports folder")
        export_btn.clicked.connect(self._export)
        new_rec = QPushButton("● New recording")
        new_rec.setObjectName("danger")
        new_rec.clicked.connect(self.new_recording_requested.emit)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.settings_requested.emit)
        self.export_widgets = [export_btn]

        bar = QHBoxLayout()
        bar.addWidget(self.trn_status)
        bar.addWidget(self.trn_progress)
        for b in self.btn.values():
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(export_btn)
        bar.addWidget(new_rec)
        bar.addWidget(settings_btn)

        # --- main area ---
        self.warning = QLabel()
        self.warning.setObjectName("banner")
        self.warning.setWordWrap(True)
        self.warning.hide()
        self.timeline = Timeline()
        self.timeline.play_segment.connect(
            lambda a, b: self.player.play_range(a, b, int(self.settings.preroll_segment_s * 1000)))
        self.timeline.play_note.connect(
            lambda t: self.player.play_range(t, None, int(self.settings.preroll_note_s * 1000)))
        self.timeline.note_action.connect(self._note_action)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Add a note…")
        self.note_input.returnPressed.connect(self._add_note)
        self.note_time = QLineEdit("00:00")
        self.note_time.setFixedWidth(80)
        self.note_time.setToolTip("Timestamp (mm:ss); follows the playback position")
        add = QPushButton("Add note")
        add.clicked.connect(self._add_note)
        self.undo = QPushButton("Note deleted – Undo")
        self.undo.setFlat(True)
        self.undo.hide()
        self.undo.clicked.connect(self._restore)
        self.player = Player()
        self.player.position_changed.connect(self._position)
        note_row = QHBoxLayout()
        note_row.addWidget(self.note_input, 1)
        note_row.addWidget(QLabel("at"))
        note_row.addWidget(self.note_time)
        note_row.addWidget(add)
        note_row.addWidget(self.undo)
        self.note_widgets = [self.note_input, self.note_time, add]

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.addLayout(bar)
        ml.addWidget(self.warning)
        ml.addWidget(self.timeline, 1)
        ml.addLayout(note_row)
        ml.addWidget(self.player)
        split = QSplitter()
        split.addWidget(side)
        split.addWidget(main)
        split.setSizes([300, 900])
        split.setStretchFactor(0, 0)  # the sidebar keeps its width when the window is resized
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        self.setCentralWidget(split)
        self.resize(1250, 800)

        QShortcut(QKeySequence.Undo, self, activated=self._restore)
        self._ctx_timer = QTimer(self, singleShot=True, interval=700, timeout=self._save_contexts)
        self.project_context.textChanged.connect(self._ctx_timer.start)
        self.recording_context.textChanged.connect(self._ctx_timer.start)
        self.project_language.activated.connect(self._save_project_language)
        self.recording_language.activated.connect(self._save_recording_language)
        self._job_changed.connect(self._refresh_job)
        self._recovered.connect(self._on_recovered)
        self._last_progress = 0.0
        self._refresh_projects()
        self._update_controls()

    # --- projects ------------------------------------------------------------------------

    def _refresh_projects(self) -> None:
        root = Path(self.settings.projects_folder)
        self.project_combo.clear()
        folders = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower(), reverse=True)
        extra = [Path(p) for p in self.settings.recent_projects if Path(p).is_dir() and Path(p).parent != root]
        for f in folders + extra:
            self.project_combo.addItem(f.name, str(f))
        if self.project:
            self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(str(self.project.folder))))

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open a project folder", self.settings.projects_folder)
        if folder:
            self.open_project(Path(folder))

    def _new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "New project", "Project name:", text=default_project_name(""))
        name = name.strip()
        if ok and name:
            try:
                project = Project.create(Path(self.settings.projects_folder), name)
            except FileExistsError:
                QMessageBox.warning(self, "New project", f"A folder named “{name}” already exists.")
                return
            self.open_project(project.folder)

    def open_project(self, folder: Path, select: str | None = None) -> None:
        self._save_contexts()
        try:
            self.project = Project(folder)
        except UnreadableFileError as e:
            QMessageBox.critical(self, "Cannot open project", f"{e}\n\nFix or remove the file to open the project.")
            return
        self.settings.add_recent(str(folder))
        self.settings.save()
        self._refresh_projects()
        self.project_context.blockSignals(True)
        self.project_context.setPlainText(self.project.settings.context)
        self.project_context.blockSignals(False)
        self.fill_language_lists()
        self._recover(select)

    def _recover(self, select: str | None) -> None:
        """Finish recordings left unfinished by a crash (REC-12)."""
        project = self.project
        todo = [b for b in project.recordings() if is_unfinished(project, b) and not self.ctl.is_recording(project, b)]
        if not todo:
            self.refresh_recordings(select)
            return
        self.recordings.clear()
        self.timeline.show_message("Recovering unfinished recordings…")

        def work():
            done = []
            for base in todo:
                try:
                    finalize_recording(project, base)
                    done.append(base)
                except Exception as e:  # noqa: BLE001
                    done.append(f"{base} (failed: {e})")
            self._recovered.emit(", ".join(done))
        threading.Thread(target=work, daemon=True).start()
        self._pending_select = select

    def _on_recovered(self, names: str) -> None:
        QMessageBox.information(self, "Recording recovered",
                                f"These recordings were not finished (e.g. after a crash) and have been recovered:\n{names}")
        self.refresh_recordings(getattr(self, "_pending_select", None))

    def refresh_recordings(self, select: str | None = None) -> None:
        select = select or self.base
        self.recordings.blockSignals(True)
        self.recordings.clear()
        for base in reversed(self.project.recordings()):
            item = QListWidgetItem(self._recording_label(base))
            item.setData(Qt.UserRole, base)
            self.recordings.addItem(item)
            if base == select:
                self.recordings.setCurrentItem(item)
        if self.recordings.currentItem() is None and self.recordings.count():
            self.recordings.setCurrentRow(0)  # newest first
        self.recordings.blockSignals(False)
        cur = self.recordings.currentItem()
        self.open_recording(cur.data(Qt.UserRole) if cur else None)

    def _recording_label(self, base: str) -> str:
        job = self.ctl.job(self.project, base, create=False)
        status = job.status if job else self._file_status(base)
        badge = {"done": "", "idle": " · not transcribed", "running": " · transcribing…",
                 "interrupted": " · interrupted", "stopped": " · incomplete", "unreadable": " · ⚠ unreadable file"}
        return base + badge.get(status, "")

    def _file_status(self, base: str) -> str:
        try:
            data, _ = read_json(self.project.path(base, "transcript.json"))
        except UnreadableFileError:
            return "unreadable"
        s = (data or {}).get("status", "idle")
        return "interrupted" if s == "running" else s

    # --- recording -----------------------------------------------------------------------

    def open_recording(self, base: str | None) -> None:
        self._save_contexts()
        self.base, self.notes, self.meta_file, self.writable = base, None, None, False
        self.recording_context.blockSignals(True)
        self.recording_context.clear()
        self.recording_context.blockSignals(False)
        self.undo.hide()
        if base is None:
            self.player.load(None)
            self.timeline.show_message("No recordings yet. Use “New recording” to record a meeting.")
            self._update_controls()
            return
        errors = []
        try:
            self.meta_file = RecordingFile(self.project.path(base, "recording.json"))
        except UnreadableFileError as e:
            errors.append(str(e))
        if self.meta_file is not None:
            duration = self.meta_file.meta.duration_ms
            if duration is None:  # e.g. an imported file without metadata
                duration = self._audio_duration(base)
            try:
                self.notes = NotesFile(self.project.path(base, "notes.json"), duration)
            except UnreadableFileError as e:
                errors.append(str(e))
        try:
            self.job = self.ctl.job(self.project, base)
        except UnreadableFileError as e:
            errors.append(str(e))
            self.job = None
        self.writable = not errors
        if errors:
            self.timeline.show_message("This recording cannot be shown:\n\n" + "\n".join(errors) +
                                       "\n\nFix or remove the file. The app does not change it.")
        else:
            self.recording_context.blockSignals(True)
            self.recording_context.setPlainText(self.meta_file.meta.context)
            self.recording_context.blockSignals(False)
            self.fill_language_lists()
            self.player.load(self.project.audio_path(base))
            self._show_timeline()
        self._update_controls()

    def _audio_duration(self, base: str) -> int | None:
        path = self.project.audio_path(base)
        if path is None:
            return None
        try:
            import soundfile as sf
            info = sf.info(path)
            return int(info.frames * 1000 / info.samplerate)
        except Exception:
            try:
                import av
                with av.open(str(path)) as c:
                    return int(c.duration / 1000) if c.duration else None
            except Exception:
                return None

    def _duration(self) -> int | None:
        if self.meta_file and self.meta_file.meta.duration_ms is not None:
            return self.meta_file.meta.duration_ms
        return self._audio_duration(self.base) if self.base else None

    def _show_timeline(self) -> None:
        if not (self.project and self.base and self.writable):
            return
        state = self.job.state if self.job else {}
        segments = state.get("segments", []) if state.get("status") in ("done", "stopped") else []
        self.timeline.threshold = self.settings.confidence_threshold
        self.timeline.highlight = self.settings.highlight_low_confidence
        self.timeline.set_data(self._duration(), segments, state.get("speakers", {}),
                               self.notes.notes, self.meta_file.meta.mutes)
        faulty = self.notes.faulty_count + self.meta_file.faulty_count
        self.warning.setVisible(faulty > 0)
        self.warning.setText(f"{faulty} faulty {'entry is' if faulty == 1 else 'entries are'} ignored "
                             "and will be removed on the next save.")

    # --- context texts -------------------------------------------------------------------

    def _save_contexts(self) -> None:
        self._ctx_timer.stop()
        try:
            if self.project and self.project_context.toPlainText() != self.project.settings.context:
                self.project.update(context=self.project_context.toPlainText())
            if self.meta_file and self.writable and self.recording_context.toPlainText() != self.meta_file.meta.context:
                self.meta_file.update(context=self.recording_context.toPlainText())
        except (UnreadableFileError, OSError) as e:
            QMessageBox.warning(self, "Cannot save", str(e))

    def fill_language_lists(self) -> None:
        """Common languages, or all of them (setting); the current choice is always listed."""
        show_all = self.settings.show_all_languages
        s = self.project.settings if self.project else None
        project_lang = s.language if s and s.language_mode == "fixed" else None
        languages.fill_combo(self.project_language, [("Auto-detect", None)], show_all, project_lang)
        rec_lang = self.meta_file.meta.language if self.meta_file and self.writable else None
        languages.fill_combo(self.recording_language, [("Use the project setting", None), ("Auto-detect", "auto")],
                             show_all, rec_lang)

    def _save_project_language(self) -> None:
        code = self.project_language.currentData()
        if self.project:
            self.project.update(language_mode="fixed" if code else "auto", language=code)

    def _save_recording_language(self) -> None:
        if self.meta_file and self.writable:
            self.meta_file.update(language=self.recording_language.currentData())

    def _transcription_language(self) -> str | None:
        """Recording override, else the project setting; None = auto-detect (CTX-03)."""
        lang = self.meta_file.meta.language if self.meta_file else None
        if lang == "auto":
            return None
        if lang:
            return lang
        s = self.project.settings
        return s.language if s.language_mode == "fixed" else None

    # --- transcription -------------------------------------------------------------------

    def _ensure_model(self) -> bool:
        name = self.settings.model
        if models.is_available(name, paths.whisper_models_dir()):
            return True
        if QMessageBox.question(self, "Model missing",
                                f"The Whisper model “{name}” is not downloaded yet. Download it now? "
                                "This is a one-time download of about 1.6 GB for the default model.") != QMessageBox.Yes:
            return False
        self.ctl.download_model(name, self)
        return False  # transcription can be started once the download has finished

    def _trn_start(self) -> None:
        if not self._ensure_model():
            return
        duration = self._duration() or 0
        rtf = self.settings_rtf()
        est = duration / 1000 * rtf
        if QMessageBox.question(
                self, "Transcribe", f"Transcribe with {self.settings.model}, "
                f"language: {languages.name(self._transcription_language())}?\n\n"
                f"Estimated time: about {max(1, round(est / 60))} min.") != QMessageBox.Yes:
            return
        self._save_contexts()
        self.job.start(self.settings.model, self._transcription_language(),
                       combined_context(self.project.settings.context, self.meta_file.meta.context))
        self._job_started = (time.monotonic(), duration, self.settings.model)
        self._refresh_job()

    def settings_rtf(self) -> float:
        return self.settings.measured_rtf.get(self.settings.model) or (DEFAULT_RTF.get(self.settings.model, 1.0) + DIARIZE_RTF) * CONSERVATIVE

    def _trn_interrupt(self) -> None:
        self.job.interrupt()
        self._job_started = None
        self._refresh_job()

    def _trn_resume(self) -> None:
        if self._ensure_model():
            self.job.resume()
            self._refresh_job()

    def _trn_stop(self) -> None:
        self.job.stop()
        self._refresh_job()

    def _trn_restart(self) -> None:
        """Confirmation: the results cannot be restored (TRN-04, §6)."""
        if QMessageBox.question(self, "Restart transcription?",
                                "This deletes the current transcript and starts over. It cannot be undone.") \
                != QMessageBox.Yes or not self._ensure_model():
            return
        self._save_contexts()
        self.job.restart(self.settings.model, self._transcription_language(),
                         combined_context(self.project.settings.context, self.meta_file.meta.context))
        self._refresh_job()

    def job_changed(self) -> None:
        """Called from worker monitor threads."""
        self._job_changed.emit()

    def _refresh_job(self) -> None:
        if self.job and self.job.status == "done" and getattr(self, "_job_started", None):
            t0, duration, model = self._job_started
            if duration:
                self.ctl.record_speed(model, (time.monotonic() - t0) / (duration / 1000))
            self._job_started = None
        for i in range(self.recordings.count()):
            item = self.recordings.item(i)
            item.setText(self._recording_label(item.data(Qt.UserRole)))
        if self.job and self.job.status in ("done", "stopped") and self.writable:
            self._show_timeline()
        self._update_controls()

    def _update_controls(self) -> None:
        job = self.job if self.base and self.writable else None
        status = job.status if job else "none"
        other_running = self.ctl.running_job() not in (None, job)
        recording_now = self.ctl.recording_active()
        can_start = job is not None and not other_running and not recording_now
        self.btn["start"].setVisible(status == "idle")
        self.btn["start"].setEnabled(can_start)
        self.btn["interrupt"].setVisible(status == "running")
        self.btn["resume"].setVisible(status == "interrupted")
        self.btn["resume"].setEnabled(can_start)
        self.btn["stop"].setVisible(status in ("running", "interrupted"))
        self.btn["restart"].setVisible(status in ("running", "interrupted", "stopped", "done"))
        self.btn["restart"].setEnabled(status == "running" or can_start)
        for w in self.export_widgets:
            w.setEnabled(bool(self.base and self.writable))
        for w in self.note_widgets:
            w.setEnabled(bool(self.notes is not None and self.writable))
        if job is None:
            self.trn_status.setText("")
            self.trn_progress.hide()
            return
        stage, fraction = job.progress()
        text = {"idle": "Not transcribed", "done": "Transcribed", "stopped": "Transcript incomplete (stopped)",
                "interrupted": "Interrupted", "running": {"preparing": "Preparing…", "transcribing": "Transcribing",
                                                          "diarizing": "Identifying speakers"}.get(stage, stage)}[status]
        if job.state.get("language") and status in ("done", "stopped", "interrupted", "running"):
            text += f" · {languages.name(job.state['language'])}"
        if other_running and status in ("idle", "interrupted"):
            text += " · another transcription is running"
        if recording_now and status in ("idle", "interrupted"):
            text += " · not available while recording"
        if job.state.get("error"):
            text += " · error (see details)"
            self.trn_status.setToolTip(job.state["error"])
        self.trn_status.setText(text)
        self.trn_progress.setVisible(status == "running")
        self.trn_progress.setValue(int(fraction * 100))
        self.trn_progress.setFormat(f"{stage} %p%")

    # --- notes ---------------------------------------------------------------------------

    def _position(self, pos: int) -> None:
        self.timeline.set_playhead(pos)
        if not self.note_time.hasFocus():
            self.note_time.setText(clock(pos))

    def _add_note(self) -> None:
        text = self.note_input.text().strip()
        t = parse_clock(self.note_time.text())
        if not text or self.notes is None:
            return
        duration = self._duration()
        if t is None or (duration is not None and t > duration):
            QMessageBox.warning(self, "Timestamp", f"Enter a time between 00:00 and {clock(duration or 0)}.")
            return
        self.notes.add(text, t, time_source="manual")
        self.note_input.clear()
        self._show_timeline()

    def _note_action(self, action: str, note_id: str) -> None:
        note = self.notes.get(note_id)
        if action == "edit":  # time and text in one dialog
            dialog = NoteDialog(note.text, note.time_ms, self._duration() or 0, self)
            if not dialog.exec():
                return
            if dialog.note_text() != note.text:
                self.notes.edit_text(note_id, dialog.note_text())
            if dialog.time_ms != note.time_ms:
                self.notes.set_time(note_id, dialog.time_ms)
        elif action == "delete":  # no confirmation; restore instead (NOTE-06a)
            self.notes.delete(note_id)
            self.undo.show()
        self._show_timeline()

    def _restore(self) -> None:
        if self.notes and self.notes.restore_last_deleted():
            self.undo.hide()
            self._show_timeline()

    # --- export --------------------------------------------------------------------------

    def _export(self) -> None:
        self._save_contexts()
        try:
            files = RecordingExport(self.project, self.base, self.settings.export_marker,
                                    self.settings.confidence_threshold).write(separate=self.settings.export_separate)
        except (UnreadableFileError, OSError) as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        box = QMessageBox(QMessageBox.Information, "Exported",
                          "Written to the exports folder:\n" + "\n".join(f.name for f in files), parent=self)
        open_btn = box.addButton("Open export folder", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Ok)
        box.setDefaultButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            self._open_exports()

    def _open_exports(self) -> None:
        folder = self.project.folder / "exports"
        folder.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, e):
        self._save_contexts()
        self.player.player.stop()
        super().closeEvent(e)
