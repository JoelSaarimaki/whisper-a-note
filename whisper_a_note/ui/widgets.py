"""Shared widgets: level meters, the on-demand sound check (REC-02, REC-11) and the note editor."""
from __future__ import annotations

import re
import threading
import time

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QTextCursor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QVBoxLayout, QWidget)

from ..audio.sources import DeviceLost, SoundcardSource
from . import theme


def clock(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def parse_clock(text: str) -> int | None:
    """'mm:ss' or 'h:mm:ss' -> ms."""
    m = re.fullmatch(r"\s*(?:(\d+):)?(\d{1,2}):(\d{2})\s*", text)
    if not m:
        return None
    h, mi, s = int(m[1] or 0), int(m[2]), int(m[3])
    return ((h * 60 + mi) * 60 + s) * 1000 if s < 60 and mi < 60 else None


class NoteDialog(QDialog):
    """Edit a note's text, and its time when duration_ms is given (NOTE-06, NOTE-07).

    The text wraps instead of scrolling sideways.
    """

    def __init__(self, text: str, time_ms: int | None = None, duration_ms: int | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit note")
        self.duration_ms = duration_ms
        self.text = QPlainTextEdit(text)
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.text.setTabChangesFocus(True)
        self.time = QLineEdit(clock(time_ms or 0))
        self.time.setFixedWidth(90)
        self.time_ms = time_ms
        form = QFormLayout()
        if duration_ms is not None:
            form.addRow("Time", self.time)
            form.addRow("", QLabel(f"Between 00:00 and {clock(duration_ms)}", objectName="hint"))
        form.addRow("Text", self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)
        self.resize(420, 220)
        self.text.setFocus()
        self.text.moveCursor(QTextCursor.End)

    def note_text(self) -> str:
        return self.text.toPlainText()

    def _save(self) -> None:
        if self.duration_ms is not None:
            t = parse_clock(self.time.text())
            if t is None or t > self.duration_ms:
                QMessageBox.warning(self, "Timestamp", f"Enter a time between 00:00 and {clock(self.duration_ms)}.")
                return
            self.time_ms = t
        if not self.note_text().strip():
            QMessageBox.warning(self, "Note text", "The note text cannot be empty. Use Delete to remove a note.")
            return
        self.accept()


class LevelMeter(QWidget):
    """Mixer-style meter with peak hold; shows muted and lost states."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(60, 12)
        self.setMaximumHeight(16)
        self.level = 0.0
        self.peak = 0.0
        self._peak_t = 0.0
        self.muted = False
        self.lost = False

    def set_level(self, peak: float, muted: bool = False, lost: bool = False) -> None:
        db = 20 * np.log10(max(peak, 1e-5))
        self.level = min(1.0, max(0.0, (db + 60) / 60))  # -60 dB … 0 dB
        now = time.monotonic()
        if self.level >= self.peak or now - self._peak_t > 1.5:
            self.peak, self._peak_t = self.level, now
        self.muted, self.lost = muted, lost
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillRect(r, QColor(theme.INPUT))
        if self.lost:
            p.setPen(QColor(theme.DANGER))
            p.drawText(r, Qt.AlignCenter, "device lost")
            return
        w = r.width() * self.level
        color = theme.MUTED_TEXT if self.muted else (theme.DANGER if self.level > 0.95 else
                                                     theme.WARN if self.level > 0.8 else theme.OK)
        p.fillRect(QRectF(r.left(), r.top(), w, r.height()), QColor(color))
        x = r.left() + r.width() * self.peak
        p.fillRect(QRectF(x - 1, r.top(), 2, r.height()), QColor(theme.TEXT))
        if self.muted:
            p.setPen(QColor(theme.TEXT))
            p.drawText(r, Qt.AlignCenter, "muted")


class SoundCheck:
    """Opens the devices only while running, and releases them on stop (REC-02, REC-11)."""

    def __init__(self, mic_device: str | None, system_device: str | None):
        self.sources = {"mic": SoundcardSource(mic_device, loopback=False),
                        "system": SoundcardSource(system_device, loopback=True)}
        self.levels = {"mic": (0.0, False), "system": (0.0, False)}  # (peak, lost)
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._run, args=(k,), daemon=True) for k in self.sources]

    def start(self) -> None:
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)

    def _run(self, kind: str) -> None:
        src = self.sources[kind]
        try:
            src.open()
            while not self._stop.is_set():
                block = src.read()
                self.levels[kind] = (float(np.max(np.abs(block))) if len(block) else 0.0, False)
        except DeviceLost:
            self.levels[kind] = (0.0, True)
        finally:
            src.close()


class SoundCheckWidget(QWidget):
    """Meters for the selected devices; runs only while visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.check: SoundCheck | None = None
        self.meters = {"mic": LevelMeter(), "system": LevelMeter()}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        for kind, label in (("mic", "MIC"), ("system", "SYS")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(self.meters[kind], 1)
            lay.addLayout(row)
        self.timer = QTimer(self, interval=50, timeout=self._tick)  # NFR-03: ≥ 20 updates/s

    def restart(self, mic_device: str | None, system_device: str | None) -> None:
        self.stop()
        self.check = SoundCheck(mic_device, system_device)
        self.check.start()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        if self.check:
            self.check.stop()
            self.check = None

    def _tick(self) -> None:
        if self.check:
            for kind, (peak, lost) in self.check.levels.items():
                self.meters[kind].set_level(peak, lost=lost)

    def hideEvent(self, e):
        self.stop()
        super().hideEvent(e)
