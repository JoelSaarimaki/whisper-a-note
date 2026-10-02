"""Markdown and confidence JSON export (SPEC §5.8).

Exports always go to the project's `exports/` folder and overwrite earlier exports of the
same recording (EXP-08, EXP-09).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .storage import NotesFile, Project, RecordingFile
from .storage.jsonfile import read_json, write_json
from .transcription.merge import join_words

MARKERS = {"italic": ("*", "*"), "code": ("`", "`"), "off": ("", "")}


def hms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _escape(word: str) -> str:
    """Transcript text must not contain Markdown emphasis of its own (§5.8.1)."""
    return word.replace("\\", "\\\\").replace("*", "\\*").replace("`", "\\`").replace("_", "\\_")


def marked_text(words: list[dict], marker: str, threshold: float) -> str:
    """Low-confidence words marked; consecutive ones as one span."""
    left, right = MARKERS[marker]
    out, span = [], []
    for w in words:
        text = _escape(w["w"])
        if left and w["conf"] < threshold:
            span.append(text)
            continue
        if span:
            out.append(f"{left}{join_words(span)}{right}")
            span = []
        out.append(text)
    if span:
        out.append(f"{left}{join_words(span)}{right}")
    return join_words(out)


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # JSON strings are valid YAML


class RecordingExport:
    def __init__(self, project: Project, base: str, marker: str = "italic", threshold: float = 0.70):
        self.project, self.base, self.marker, self.threshold = project, base, marker, threshold
        self.meta = RecordingFile(project.path(base, "recording.json")).meta
        self.transcript = read_json(project.path(base, "transcript.json"))[0] or {}
        self.notes = NotesFile(project.path(base, "notes.json"), self.meta.duration_ms).notes
        self.speakers = self.transcript.get("speakers", {})

    def speaker(self, label) -> str:
        return self.speakers.get(label, label or "Unknown speaker")

    # --- pieces --------------------------------------------------------------------------

    def front_matter(self) -> str:
        t = self.transcript
        lines = ["---",
                 f"project: {_yaml_str(self.project.settings.name)}",
                 f"recording: {_yaml_str(self.base)}"]
        if self.meta.started_at:
            lines.append(f"date: {self.meta.started_at}")
        if self.meta.duration_ms is not None:
            lines.append(f'duration: "{hms(self.meta.duration_ms)}"')
        if self.speakers:
            lines.append("speakers: [" + ", ".join(_yaml_str(v) for v in self.speakers.values()) + "]")
        if t.get("model"):
            lines.append(f"transcription_model: faster-whisper {t['model']}")
        if t.get("language"):
            lines.append(f"language: {t['language']}")
        if t.get("segments") and self.marker != "off":
            style = "Italic" if self.marker == "italic" else "Code-formatted"
            lines += ["confidence:", f"  marker: {self.marker}", f"  threshold: {self.threshold:.2f}",
                      f"  note: {_yaml_str(f'{style} words in transcript lines had confidence below the threshold. Per-word values: {self.base}.confidence.json')}"]
        lines.append("---")
        return "\n".join(lines)

    def context_md(self, level: str = "##") -> str:
        parts = []
        if self.project.settings.context.strip():
            parts.append(f"{level} Project context\n{self.project.settings.context.strip()}")
        if self.meta.context.strip():
            parts.append(f"{level} Recording context\n{self.meta.context.strip()}")
        return "\n\n".join(parts)

    def segment_md(self, seg: dict) -> str:
        lang = seg.get("language")
        tag = f" ({lang})" if lang and lang != self.transcript.get("language") else ""
        return f"**[{hms(seg['start_ms'])}] {self.speaker(seg['speaker'])}{tag}:** " + \
            marked_text(seg["words"], self.marker, self.threshold)

    @staticmethod
    def note_md(note) -> str:
        return f"> **[{hms(note.time_ms)}] Note:** {note.text}"

    def timeline(self) -> list[str]:
        """A note follows the segment covering its timestamp, never inside it (EXP-01)."""
        segments = self.transcript.get("segments", [])
        notes = list(self.notes)
        blocks = []
        for seg in segments:
            while notes and notes[0].time_ms < seg["start_ms"]:
                blocks.append(self.note_md(notes.pop(0)))
            blocks.append(self.segment_md(seg))
            while notes and notes[0].time_ms <= seg["end_ms"]:
                blocks.append(self.note_md(notes.pop(0)))
        blocks += [self.note_md(n) for n in notes]
        return blocks

    def title(self) -> str:
        date = ""
        if self.meta.started_at:
            date = f" — {datetime.fromisoformat(self.meta.started_at):%Y-%m-%d %H:%M}"
        name = self.project.settings.name
        if len(name) > 11 and name[:10].count("-") == 2 and name[10] == " ":
            name = name[11:]  # "2026-10-02 Customer interview" -> "Customer interview"
        return f"# {name}{date}"

    # --- files ---------------------------------------------------------------------------

    def confidence_json(self) -> dict:
        segs = []
        for seg in self.transcript.get("segments", []):
            confs = [w["conf"] for w in seg["words"]]
            segs.append({
                "start_ms": seg["start_ms"], "end_ms": seg["end_ms"], "speaker": self.speaker(seg["speaker"]),
                "text": seg["text"],
                "avg_word_confidence": round(sum(confs) / len(confs), 3) if confs else None,
                "words": seg["words"],
            })
        return {"recording": self.base, "model": f"faster-whisper {self.transcript.get('model', '')}".strip(),
                "confidence_scale": "0.0-1.0, model word probability (uncalibrated)", "segments": segs}

    def write(self, separate: bool = False) -> list[Path]:
        """EXP-01 (combined) or EXP-02 (separate files), plus the confidence JSON (EXP-05)."""
        out = self.project.folder / "exports"
        out.mkdir(exist_ok=True)
        files: list[Path] = []

        def put(name: str, text: str):
            path = out / name
            path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
            files.append(path)

        if not separate:
            body = [self.front_matter(), "", self.title(), ""]
            ctx = self.context_md()
            if ctx:
                body += [ctx, ""]
            body += ["## Timeline", "", "\n\n".join(self.timeline())]
            put(f"{self.base}.md", "\n".join(body))
        else:
            fm = self.front_matter()
            segments = self.transcript.get("segments", [])
            put(f"{self.base}.transcript.md", "\n".join([fm, "", self.title() + " — transcript", "",
                                                         "\n\n".join(self.segment_md(s) for s in segments)]))
            put(f"{self.base}.notes.md", "\n".join([fm, "", self.title() + " — notes", "",
                                                    "\n\n".join(self.note_md(n) for n in self.notes)]))
            put(f"{self.base}.context.md", "\n".join([self.title() + " — context", "", self.context_md()]))
        if self.transcript.get("segments"):
            path = out / f"{self.base}.confidence.json"
            write_json(path, self.confidence_json())
            files.append(path)
        return files
