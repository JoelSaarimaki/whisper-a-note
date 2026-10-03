"""The three-column vertical timeline with playback (SPEC §5.7).

Rows run downward in time: Audio (time, markers, mutes) | Transcript | Manual notes.
A note is shown in the row of the transcript segment that covers its timestamp.
Playback starts from the timestamp buttons only, so hovering the text shows nothing
but the confidence of highlighted words.
"""
from __future__ import annotations

import html

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QScrollArea, QSlider, QToolTip, QVBoxLayout, QWidget)

from . import theme
from .widgets import clock


class Player(QWidget):
    """Playback with play/pause and seeking; plays segments with pre-roll (TL-03, TL-07)."""
    position_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self._stop_at: int | None = None
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("00:00 / 00:00")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.play_btn)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.time)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.positionChanged.connect(self._position)
        self.player.playbackStateChanged.connect(
            lambda s: self.play_btn.setText("⏸" if s == QMediaPlayer.PlayingState else "▶"))

    def load(self, path) -> None:
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)) if path else QUrl())

    def position(self) -> int:
        return self.player.position()

    def toggle(self) -> None:
        self._stop_at = None
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play_range(self, start_ms: int, end_ms: int | None, preroll_ms: int) -> None:
        self._stop_at = end_ms
        self.player.setPosition(max(0, start_ms - preroll_ms))
        self.player.play()

    def _position(self, pos: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.time.setText(f"{clock(pos)} / {clock(self.player.duration())}")
        if self._stop_at is not None and pos >= self._stop_at:
            self._stop_at = None
            self.player.pause()
        self.position_changed.emit(pos)


class NoteLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(e)


def time_button(ms: int, tooltip: str) -> QPushButton:
    b = QPushButton(f"▶ {clock(ms)}")
    b.setObjectName("timeButton")
    b.setCursor(Qt.PointingHandCursor)
    b.setToolTip(tooltip)
    return b


class Timeline(QScrollArea):
    play_segment = Signal(int, int)     # start, end
    play_note = Signal(int)             # timestamp
    note_action = Signal(str, str)      # action ("edit", "delete"), note id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.rows: list[tuple[int, int, QWidget]] = []  # (start, end, row frame) for the playhead
        self._current: QWidget | None = None
        self.threshold = 0.70
        self.highlight = True
        self.show_message("Select a recording.")

    def show_message(self, text: str) -> None:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setObjectName("muted")
        self.setWidget(label)
        self.rows = []

    def set_data(self, duration_ms: int | None, segments: list[dict], speakers: dict, notes, mutes) -> None:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        grid.setVerticalSpacing(2)
        for col, title in enumerate(("Audio", "Transcript", "Manual notes")):
            h = QLabel(title)
            h.setStyleSheet("font-weight: bold;")
            grid.addWidget(h, 0, col)
        colors = {label: theme.SPEAKER_COLORS[i % len(theme.SPEAKER_COLORS)] for i, label in enumerate(speakers)}

        # Rows: (time, kind, payload)
        items = [(0, 0, "start", None)]
        pending = list(notes)
        for seg in segments:
            while pending and pending[0].time_ms < seg["start_ms"]:
                n = pending.pop(0)
                items.append((n.time_ms, 2, "note", [n]))
            attached = []
            while pending and pending[0].time_ms <= seg["end_ms"]:
                attached.append(pending.pop(0))
            items.append((seg["start_ms"], 1, "segment", (seg, attached)))
        items += [(n.time_ms, 2, "note", [n]) for n in pending]
        items += [(m.start_ms, 0, "mute", m) for m in mutes]
        if duration_ms is not None:
            items.append((duration_ms, 3, "end", None))
        items.sort(key=lambda x: (x[0], x[1]))

        self.rows = []
        r = 1
        for t, _, kind, payload in items:
            frame = QFrame()
            frame.setObjectName("row")
            row = QGridLayout(frame)
            row.setContentsMargins(4, 3, 4, 3)
            if kind in ("start", "end"):
                label = QLabel(f"{'Start' if kind == 'start' else 'End'} of audio · {clock(t)}")
                label.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold;")
                grid.addWidget(label, r, 0, 1, 3)
                r += 1
                continue
            if kind == "mute":
                reason = {"user": "muted / off the record", "device_lost": f"{payload.source} device lost",
                          "system_sleep": "computer asleep"}[payload.reason]
                span = f"{clock(payload.start_ms)}–{clock(payload.end_ms)}" if payload.end_ms != payload.start_ms \
                    else clock(payload.start_ms)
                label = QLabel(f"⏸ {span}\n{payload.source if payload.reason == 'user' else ''} {reason}".strip())
                label.setStyleSheet(f"color: {theme.MUTED_TEXT}; background: {theme.PANEL}; padding: 3px;")
                grid.addWidget(label, r, 0, 1, 3)
                r += 1
                continue
            if kind == "segment":
                seg, attached = payload
                play = time_button(t, "Play this segment")
                play.clicked.connect(lambda _=False, s=seg: self.play_segment.emit(s["start_ms"], s["end_ms"]))
                row.addWidget(play, 0, 0, Qt.AlignTop)
                row.addWidget(self._segment_widget(seg, speakers, colors), 0, 1)
                row.addWidget(self._notes_widget(attached), 0, 2)
                self.rows.append((seg["start_ms"], seg["end_ms"], frame))
            else:  # the note has its own play button
                row.addWidget(QWidget(), 0, 1)
                row.addWidget(self._notes_widget(payload), 0, 2)
                self.rows.append((t, t + 1000, frame))
            row.setColumnStretch(1, 3)
            row.setColumnStretch(2, 2)
            row.setColumnMinimumWidth(0, 70)
            grid.addWidget(frame, r, 0, 1, 3)
            r += 1
        grid.setRowStretch(r, 1)
        self.setWidget(container)
        self._current = None

    def _segment_widget(self, seg, speakers, colors) -> QWidget:
        name = speakers.get(seg["speaker"], seg["speaker"] or "Unknown speaker")
        parts = []
        for w in seg["words"]:
            text = html.escape(w["w"])
            if self.highlight and w["conf"] < self.threshold:
                # moderate highlight: dotted underline + muted warm colour, never bold (TRN-06)
                parts.append(f'<a href="c:{w["conf"]}" style="color:{theme.LOW_CONF}; '
                             f'text-decoration: none; border-bottom: 1px dotted;">'
                             f'<span style="text-decoration: underline dotted;">{text}</span></a>')
            else:
                parts.append(text)
        label = QLabel(f'<span style="color:{colors.get(seg["speaker"], theme.TEXT)}; font-weight:bold;">'
                       f'{html.escape(name)}</span><br>' + " ".join(parts))
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.linkHovered.connect(lambda href: QToolTip.showText(
            label.cursor().pos(), f"Confidence {float(href[2:]) * 100:.0f}%") if href else QToolTip.hideText())
        return label

    def _notes_widget(self, notes) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        for n in notes:
            frame = QFrame()
            frame.setObjectName("note")
            frame.setStyleSheet(f"QFrame#note {{ background: {theme.PANEL}; border-left: 3px solid {theme.ACCENT}; }}"
                                f"QFrame#note QLabel {{ background: transparent; }}")
            row = QHBoxLayout(frame)
            row.setContentsMargins(2, 3, 3, 3)
            play = time_button(n.time_ms, "Play from this note")
            play.clicked.connect(lambda _=False, t=n.time_ms: self.play_note.emit(t))
            label = NoteLabel(html.escape(n.text))
            label.setWordWrap(True)
            label.setToolTip("Double-click or right-click to edit")
            label.double_clicked.connect(lambda n=n: self.note_action.emit("edit", n.id))
            frame.setContextMenuPolicy(Qt.CustomContextMenu)
            frame.customContextMenuRequested.connect(lambda pos, n=n, f=frame: self._note_menu(n, f, pos))
            row.addWidget(play, 0, Qt.AlignTop)
            row.addWidget(label, 1)
            lay.addWidget(frame)
        lay.addStretch()
        return box

    def _note_menu(self, note, label, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: self.note_action.emit("edit", note.id))
        menu.addAction("Delete", lambda: self.note_action.emit("delete", note.id))
        menu.exec(label.mapToGlobal(pos))

    def set_playhead(self, pos: int) -> None:
        """Highlight the row being played."""
        current = next((f for a, b, f in self.rows if a <= pos < b), None)
        if current is self._current:
            return
        if self._current is not None:
            self._current.setStyleSheet("")
        if current is not None:
            current.setStyleSheet(f"QFrame#row {{ background: {theme.INPUT}; border-radius: 4px; }}")
        self._current = current
