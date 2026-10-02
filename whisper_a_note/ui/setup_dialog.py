"""Recording setup before entering Recording mode (REC-20)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout)

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
    recording_context: str
    language: str | None          # override; None together with use_project=True = project setting
    use_project_language: bool
    mic_device: str | None
    system_device: str | None


class RecordingSetupDialog(QDialog):
    def __init__(self, settings: AppSettings, current: Project | None, recording_context: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("New recording — Whisper A Note")
        self.settings = settings
        self.result_value: SetupResult | None = None
        root = Path(settings.projects_folder)

        form = QFormLayout()
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
        self.new_name.setPlaceholderText("Project name, e.g. 2026-10-02 Customer interview")
        form.addRow("Project", self.project_combo)
        form.addRow("New project name", self.new_name)

        self.project_context = QPlainTextEdit()
        self.project_context.setPlaceholderText("Shared by all recordings of the project: topic, names, terms")
        self.project_context.setFixedHeight(70)
        self.recording_context = QPlainTextEdit(recording_context)
        self.recording_context.setPlaceholderText("This recording only: participants, topics, other notes")
        self.recording_context.setFixedHeight(70)
        hint = QLabel("Keep the context texts short (about 100 words together): names and terms help most.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("Project context", self.project_context)
        form.addRow("Recording context", self.recording_context)
        form.addRow("", hint)

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
        self.resize(560, 640)
        self.project_combo.currentIndexChanged.connect(self._project_changed)
        self._project_changed()
        self._restart_check()

    def _project_changed(self) -> None:
        data = self.project_combo.currentData()
        self.new_name.setEnabled(data == NEW_PROJECT)
        if data != NEW_PROJECT:
            try:
                self.project_context.setPlainText(Project(Path(data)).settings.context)
            except UnreadableFileError as e:
                QMessageBox.warning(self, "Cannot read project", str(e))
        else:
            self.project_context.clear()

    def _restart_check(self) -> None:
        self.check.restart(self.mic.currentData(), self.system.currentData())

    def _confirm(self) -> None:
        """Project changes are saved when the setup is confirmed (REC-20)."""
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
            if project.settings.context != self.project_context.toPlainText():
                project.update(context=self.project_context.toPlainText())
        except (UnreadableFileError, OSError) as e:
            QMessageBox.warning(self, "Cannot save project", str(e))
            return
        lang = self.language.currentData()
        self.check.stop()
        self.result_value = SetupResult(
            project=project, recording_context=self.recording_context.toPlainText(),
            language=None if lang == PROJECT_SETTING else lang, use_project_language=lang == PROJECT_SETTING,
            mic_device=self.mic.currentData(), system_device=self.system.currentData())
        self.accept()

    def done(self, r):
        self.check.stop()
        super().done(r)
