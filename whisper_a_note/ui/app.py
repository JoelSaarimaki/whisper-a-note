"""Application controller: one window at a time, jobs, drafts, first run (SPEC §6)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

from .. import paths
from ..storage import Project
from ..transcription import models
from ..transcription.job import TranscriptionJob
from . import theme
from .recording_window import RecordingWindow
from .review_window import ReviewWindow
from .settings import AppSettings
from .settings_dialog import SettingsDialog
from .setup_dialog import RecordingSetupDialog


class Controller(QObject):
    _download_done = Signal(str, str)  # model, error

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = AppSettings.load()
        self.jobs: dict[tuple[str, str], TranscriptionJob] = {}
        self.drafts: dict[str, tuple[str, str]] = {}  # project folder -> (recording context, note draft)
        self.review: ReviewWindow | None = None
        self.recording: RecordingWindow | None = None
        self._download_done.connect(self._on_download_done)
        self._progress = None
        app.aboutToQuit.connect(self._quit)

    # --- start-up ------------------------------------------------------------------------

    def start(self) -> None:
        if self.settings.load_error:
            QMessageBox.warning(None, "Settings not readable",
                                f"{self.settings.load_error}\n\nDefault settings are used and the file is not changed.")
        if not self.settings.projects_folder or not Path(self.settings.projects_folder).is_dir():
            default = Path.home() / "Documents" / "Whisper A Note"
            QMessageBox.information(None, "Welcome to Whisper A Note",
                                    "Choose a folder for your projects. Each project is a subfolder in it.")
            folder = QFileDialog.getExistingDirectory(None, "Projects folder", str(default.parent))
            if not folder:
                default.mkdir(parents=True, exist_ok=True)
                folder = str(default)
            self.settings.projects_folder = folder
            self.settings.save()
        self.show_review()

    # --- windows (one at a time) ---------------------------------------------------------

    def show_review(self, project: Project | None = None, select: str | None = None) -> None:
        if self.recording is not None:
            folder, draft = str(self.recording.project.folder), self.recording.draft()
            if self.recording.state == "ready":  # left without recording: keep context and draft (REC-20)
                self.drafts[folder] = (self.recording.setup.recording_context, draft)
            else:
                self.drafts.pop(folder, None)
            self.settings.recording_geometry = bytes(self.recording.saveGeometry().toBase64()).decode()
            rec, self.recording = self.recording, None
            rec.close()
        if self.review is None:
            self.review = ReviewWindow(self)
            self.review.new_recording_requested.connect(self.new_recording)
            self.review.settings_requested.connect(self.open_settings)
            self._restore_geometry(self.review, self.settings.review_geometry)
        target = project or (Project(Path(self.settings.recent_projects[0]))
                             if self.settings.recent_projects and Path(self.settings.recent_projects[0]).is_dir() else None)
        if target is not None:
            self.review.open_project(target.folder, select)
        self.settings.save()
        self.review.show()

    def new_recording(self) -> None:
        parent = self.recording or self.review
        current = self.recording.project if self.recording else (self.review.project if self.review else None)
        context, draft = self.drafts.get(str(current.folder), ("", "")) if current else ("", "")
        dialog = RecordingSetupDialog(self.settings, current, context, parent)
        if dialog.exec() != RecordingSetupDialog.Accepted:
            return
        setup = dialog.result_value
        self.settings.mic_device, self.settings.system_device = setup.mic_device, setup.system_device
        context, draft = self.drafts.pop(str(setup.project.folder), (setup.recording_context, draft))
        if self.recording is not None:
            self.recording.close()
        if self.review is not None:
            self.settings.review_geometry = bytes(self.review.saveGeometry().toBase64()).decode()
            self.review.hide()  # one window at a time
        self.settings.save()
        self.recording = RecordingWindow(self.settings, setup, draft)
        self.recording.review_requested.connect(
            lambda: self.show_review(self.recording.project, self.recording.base))
        self.recording.new_recording_requested.connect(self.new_recording)
        self._restore_geometry(self.recording, self.settings.recording_geometry, (360, 480))
        self.recording.show()

    @staticmethod
    def _restore_geometry(window, data: str | None, default=None) -> None:
        if data:
            window.restoreGeometry(QByteArray.fromBase64(data.encode()))
        elif default:
            window.resize(*default)

    def open_settings(self) -> None:
        old = self.settings.projects_folder
        if SettingsDialog(self.settings, self.download_model, self.review).exec() and self.review:
            if self.settings.projects_folder != old:
                self.review._refresh_projects()
            self.review._show_timeline()

    # --- state shared by windows ---------------------------------------------------------

    def recording_active(self) -> bool:
        return self.recording is not None and self.recording.state in ("recording", "ending", "saving")

    def is_recording(self, project: Project, base: str) -> bool:
        return self.recording_active() and self.recording.project.folder == project.folder \
            and self.recording.base == base

    def job(self, project: Project, base: str, create: bool = True) -> TranscriptionJob | None:
        key = (str(project.folder), base)
        if key not in self.jobs:
            if not create:
                return None
            self.jobs[key] = TranscriptionJob(project, base, paths.whisper_models_dir(),
                                              on_change=lambda: self.review and self.review.job_changed())
        return self.jobs[key]

    def running_job(self) -> TranscriptionJob | None:
        return next((j for j in self.jobs.values() if j.is_running), None)

    def record_speed(self, model: str, rtf: float) -> None:
        self.settings.measured_rtf[model] = round(rtf, 3)
        self.settings.save()

    # --- model download (DIST-04) --------------------------------------------------------

    def download_model(self, name: str, parent) -> None:
        self._progress = QProgressDialog(f"Downloading the Whisper model “{name}”…", None, 0, 0, parent)
        self._progress.setWindowTitle("Downloading")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.show()
        self._download_parent = parent

        def work():
            try:
                models.download(name, paths.whisper_models_dir())
                self._download_done.emit(name, "")
            except Exception as e:  # noqa: BLE001
                self._download_done.emit(name, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_download_done(self, name: str, error: str) -> None:
        self._progress.close()
        if error:
            QMessageBox.warning(self._download_parent, "Download failed", f"Could not download {name}:\n{error}")
        else:
            QMessageBox.information(self._download_parent, "Download finished", f"The model “{name}” is ready.")
        if hasattr(self._download_parent, "refresh_model_state"):
            self._download_parent.refresh_model_state()

    def _quit(self) -> None:
        for job in self.jobs.values():
            job.close()  # running jobs are interrupted and can be resumed later (TRN-11)
        self.settings.save()


def run() -> int:
    # NFR-01: the UI process only downloads models on request; the worker processes run offline.
    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    theme.apply(app)
    ctl = Controller(app)
    ctl.start()
    return app.exec()
