"""Settings dialog."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from .. import paths
from ..transcription import models
from .settings import AppSettings

MODEL_NOTES = {
    "large-v3-turbo": "default: accurate and reasonably fast (~1.6 GB)",
    "large-v3": "most accurate, about 3× slower on CPU (~3 GB)",
    "medium": "for slower machines (~1.5 GB)",
    "small": "fastest, clearly less accurate (~0.5 GB)",
}


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, download, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings — Whisper A Note")
        self.settings, self.download = settings, download
        form = QFormLayout()

        self.folder = QLineEdit(settings.projects_folder or "")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        box = QWidget()
        box.setLayout(row)
        form.addRow("Projects folder", box)

        self.model = QComboBox()
        for name in models.MODELS:
            self.model.addItem(f"{name} — {MODEL_NOTES[name]}", name)
        self.model.setCurrentIndex(max(0, self.model.findData(settings.model)))
        self.model_state = QLabel()
        self.model_state.setObjectName("hint")
        self.dl = QPushButton("Download")
        self.dl.clicked.connect(lambda: self.download(self.model.currentData(), self))
        self.model.currentIndexChanged.connect(self.refresh_model_state)
        mrow = QHBoxLayout()
        mrow.addWidget(self.model_state, 1)
        mrow.addWidget(self.dl)
        mbox = QWidget()
        mbox.setLayout(mrow)
        form.addRow("Whisper model", self.model)
        form.addRow("", mbox)

        self.pre_seg = QDoubleSpinBox(minimum=0, maximum=30, singleStep=0.5, value=settings.preroll_segment_s, suffix=" s")
        self.pre_note = QDoubleSpinBox(minimum=0, maximum=60, singleStep=0.5, value=settings.preroll_note_s, suffix=" s")
        form.addRow("Pre-roll for segments", self.pre_seg)
        form.addRow("Pre-roll for notes", self.pre_note)

        self.threshold = QDoubleSpinBox(minimum=1, maximum=99, singleStep=5, decimals=0,
                                        value=settings.confidence_threshold * 100, suffix=" %")
        self.highlight = QCheckBox("Highlight low-confidence words in the timeline")
        self.highlight.setChecked(settings.highlight_low_confidence)
        self.marker = QComboBox()
        for key, label in (("italic", "Italic (default)"), ("code", "Code (backticks)"), ("off", "Off")):
            self.marker.addItem(label, key)
        self.marker.setCurrentIndex(max(0, self.marker.findData(settings.export_marker)))
        form.addRow("Low-confidence threshold", self.threshold)
        form.addRow("", self.highlight)
        form.addRow("Marking in Markdown export", self.marker)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)
        self.refresh_model_state()
        self.resize(560, 0)

    def refresh_model_state(self) -> None:
        ok = models.is_available(self.model.currentData(), paths.whisper_models_dir())
        self.model_state.setText("Downloaded" if ok else "Not downloaded yet")
        self.dl.setVisible(not ok)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Projects folder", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _save(self) -> None:
        s = self.settings
        s.projects_folder = self.folder.text().strip() or s.projects_folder
        s.model = self.model.currentData()
        s.preroll_segment_s, s.preroll_note_s = self.pre_seg.value(), self.pre_note.value()
        s.confidence_threshold = round(self.threshold.value() / 100, 2)
        s.highlight_low_confidence = self.highlight.isChecked()
        s.export_marker = self.marker.currentData()
        s.save()
        self.accept()
