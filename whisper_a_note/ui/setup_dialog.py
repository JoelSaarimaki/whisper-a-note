"""Recording setup before entering Recording mode (REC-20)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox,
                               QPlainTextEdit, QVBoxLayout)

from ..audio.sources import list_devices
from ..storage import Project, UnreadableFileError
from ..storage.project import default_project_name
from . import languages
from .settings import AppSettings
from .widgets import SoundCheckWidget

NEW_PROJECT = "__new__"
PROJECT_SETTING = "__project__"


@dataclass
class SetupResult:
    project: Project
    recording_name: str           # optional; becomes part of the base name (REC-20)
    recording_context: str
    language: str | None          # override; None together with use_project=True = project setting
    use_project_language: bool
    mic_device: str | None
    system_device: str | None


class RecordingSetupDialog(QDialog):
    def __init__(self, settings: AppSettings, current: Project | None, recording_context: str = "",
                 recording_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("New recording — Whisper A Note")
        self.settings = settings
        self.result_value: SetupResult | None = None
        root = Path(settings.projects_folder)

        self.form = form = QFormLayout()
        self.project_combo = QComboBox()
        for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower(), reverse=True):
            self.project_combo.addItem(folder.name, str(folder))
        self.project_combo.addItem("New project…", NEW_PROJECT)
        if current is not None:
            i = self.project_combo.findData(str(current.folder))
            self.project_combo.setCurrentIndex(max(i, 0))
        else:
            self.project_combo.setCurrentIndex(self.project_combo.count() - 1)
        self.new_name = QLineEdit(default_project_name(""))
        self.new_name.setPlaceholderText("e.g. 2026-10-02 Customer interview")
        form.addRow("Project", self.project_combo)
        form.addRow("Project name", self.new_name)  # shown only for a new project

        # The project context is edited in Review mode; the setup is about this recording.
        self.recording_name = QLineEdit(recording_name)
        self.recording_name.setPlaceholderText("Optional, e.g. Weekly sync")
        self.recording_name.setToolTip("Added to the file names after the date and time")
        self.recording_context = QPlainTextEdit(recording_context)
        self.recording_context.setPlaceholderText("Optional: participants, topics, terms (helps transcription)")
        self.recording_context.setFixedHeight(70)
        form.addRow("Recording name", self.recording_name)
        form.addRow("Recording context", self.recording_context)

        self.language = QComboBox()
        languages.fill_combo(self.language, [("Use the project setting", PROJECT_SETTING), ("Auto-detect", None)],
                             settings.show_all_languages, PROJECT_SETTING)
        form.addRow("Language", self.language)

        devices = list_devices()
        self.mic = QComboBox()
        self.system = QComboBox()
        for combo, names, chosen in ((self.mic, devices["mic"], settings.mic_device),
                                     (self.system, devices["system"], settings.system_device)):
            combo.addItem("System default", None)
            for n in names:
                combo.addItem(n, n)
            i = combo.findData(chosen)
            combo.setCurrentIndex(max(i, 0))
            combo.currentIndexChanged.connect(self._restart_check)
        form.addRow("Microphone", self.mic)
        form.addRow("System audio from", self.system)
        self.check = SoundCheckWidget()
        form.addRow("Sound check", self.check)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        ok = buttons.addButton("Open Recording mode", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)
        self.resize(560, 0)
        self.project_combo.currentIndexChanged.connect(self._project_changed)
        self._project_changed()
        self._restart_check()

    def _project_changed(self) -> None:
        self.form.setRowVisible(self.new_name, self.project_combo.currentData() == NEW_PROJECT)

    def _restart_check(self) -> None:
        self.check.restart(self.mic.currentData(), self.system.currentData())

    def _confirm(self) -> None:
        """A new project is created when the setup is confirmed (REC-20)."""
        data = self.project_combo.currentData()
        try:
            if data == NEW_PROJECT:
                name = self.new_name.text().strip()
                if not name:
                    QMessageBox.warning(self, "Project name", "Please enter a name for the new project.")
                    return
                if (Path(self.settings.projects_folder) / name).exists():
                    QMessageBox.warning(self, "Project name", f"A folder named “{name}” already exists.")
                    return
                project = Project.create(Path(self.settings.projects_folder), name)
            else:
                project = Project(Path(data))
        except (UnreadableFileError, OSError) as e:
            QMessageBox.warning(self, "Cannot save project", str(e))
            return
        lang = self.language.currentData()
        self.check.stop()
        self.result_value = SetupResult(
            project=project, recording_name=self.recording_name.text().strip(), recording_context=self.recording_context.toPlainText(),
            language=None if lang == PROJECT_SETTING else lang, use_project_language=lang == PROJECT_SETTING,
            mic_device=self.mic.currentData(), system_device=self.system.currentData())
        self.accept()

    def done(self, r):
        self.check.stop()
        super().done(r)
