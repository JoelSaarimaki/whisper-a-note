"""Dark theme for the whole UI (SPEC §6)."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#1e1f22"
PANEL = "#2b2d31"
INPUT = "#313338"
BORDER = "#3f4147"
TEXT = "#dbdee1"
MUTED_TEXT = "#949ba4"
ACCENT = "#5865f2"
WARN = "#f0b232"
DANGER = "#da373c"
OK = "#23a55a"
LOW_CONF = "#c9a96e"  # moderate highlight for low-confidence words (TRN-06)

SPEAKER_COLORS = ["#5aa9e6", "#e6a05a", "#7bd389", "#d77fd4", "#e6d65a", "#5ae6d1", "#e65a7a", "#a0a0ff"]

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QListWidget {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px;
    selection-background-color: {ACCENT};
}}
QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 10px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED_TEXT}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; }}
QPushButton#danger {{ background: {DANGER}; border: none; }}
QPushButton#muteAll:checked {{ background: {WARN}; color: #000; }}
QLabel#muted {{ color: {MUTED_TEXT}; }}
QLabel#banner {{ background: {WARN}; color: #000; font-weight: bold; padding: 4px; border-radius: 4px; }}
QLabel#error {{ background: {DANGER}; color: #fff; padding: 4px; border-radius: 4px; }}
QLabel#hint {{ color: {MUTED_TEXT}; font-style: italic; }}
QScrollArea, QSplitter {{ border: none; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}
QProgressBar {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 4px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    for role, color in [
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, INPUT),
        (QPalette.AlternateBase, PANEL), (QPalette.Text, TEXT), (QPalette.Button, PANEL),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
        (QPalette.ToolTipBase, PANEL), (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, MUTED_TEXT),
    ]:
        p.setColor(role, QColor(color))
    app.setPalette(p)
    app.setStyleSheet(STYLESHEET)
