"""Manual notes of one recording, stored in `<base>.notes.json` (SPEC §5.4, §7.2).

Every change is saved immediately (NOTE-08). Faulty entries in the file are ignored and
dropped on the next save (NOTE-05b). If the file was edited on disk since it was loaded,
it is reloaded and the change applied on top (§7.1).
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .jsonfile import FileStamp, read_json, write_json

TIME_SOURCES = ("auto", "manual")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Note:
    id: str
    text: str
    time_ms: int
    time_source: str
    created_at: str
    edited_at: str | None = None

    def sort_key(self):
        return (self.time_ms, datetime.fromisoformat(self.created_at))


def _parse_note(entry, duration_ms: int | None) -> Note | None:
    """Return a Note, or None if the entry is faulty (NOTE-05b)."""
    if not isinstance(entry, dict):
        return None
    try:
        note = Note(
            id=entry["id"], text=entry["text"], time_ms=entry["time_ms"],
            time_source=entry["time_source"], created_at=entry["created_at"],
            edited_at=entry.get("edited_at"),
        )
        if not (isinstance(note.id, str) and note.id and isinstance(note.text, str)):
            return None
        if not isinstance(note.time_ms, int) or isinstance(note.time_ms, bool) or note.time_ms < 0:
            return None
        if duration_ms is not None and note.time_ms > duration_ms:
            return None
        if note.time_source not in TIME_SOURCES:
            return None
        datetime.fromisoformat(note.created_at)
        if note.edited_at is not None:
            datetime.fromisoformat(note.edited_at)
    except (KeyError, TypeError, ValueError):
        return None
    return note


class NotesFile:
    def __init__(self, path: Path, duration_ms: int | None):
        """`duration_ms` is None while recording: then only the lower bound (0) is checked."""
        self.path = path
        self.duration_ms = duration_ms
        self.notes: list[Note] = []
        self.faulty_count = 0
        self.last_deleted: Note | None = None
        self._stamp: FileStamp | None = None
        self.load()

    # --- reading -------------------------------------------------------------------------

    def load(self) -> None:
        """Raises UnreadableFileError if the file exists but cannot be read (NFR-09)."""
        data, stamp = read_json(self.path)
        notes, faulty, seen = [], 0, set()
        entries = (data or {}).get("notes", [])
        if not isinstance(entries, list):
            faulty, entries = 1, []
        for entry in entries:
            note = _parse_note(entry, self.duration_ms)
            if note is None or note.id in seen:
                faulty += 1
                continue
            seen.add(note.id)
            notes.append(note)
        self.notes = sorted(notes, key=Note.sort_key)  # stable: ties keep file order (NOTE-05a)
        self.faulty_count = faulty
        self._stamp = stamp

    def get(self, note_id: str) -> Note:
        for n in self.notes:
            if n.id == note_id:
                return n
        raise KeyError(note_id)

    def set_duration(self, duration_ms: int | None) -> None:
        """Called when the recording ends; re-validates the entries."""
        self.duration_ms = duration_ms
        self.load()

    # --- changes (each one is saved immediately) -----------------------------------------

    def add(self, text: str, time_ms: int, time_source: str = "auto") -> Note:
        self._check_time(time_ms)
        note = Note(id=str(uuid.uuid4()), text=text, time_ms=time_ms,
                    time_source=time_source, created_at=now_iso())
        self._change(lambda notes: notes.append(note))
        return note

    def edit_text(self, note_id: str, text: str) -> Note:
        return self._replace(note_id, text=text, edited_at=now_iso())

    def set_time(self, note_id: str, time_ms: int) -> Note:
        """Manual timestamp change (NOTE-07). Limited to the audio (NOTE-05)."""
        self._check_time(time_ms)
        return self._replace(note_id, time_ms=time_ms, time_source="manual", edited_at=now_iso())

    def delete(self, note_id: str) -> Note:
        """Deleted immediately; the last deleted note can be restored (NOTE-06a)."""
        note = self.get(note_id)
        self._change(lambda notes: notes.remove(next(n for n in notes if n.id == note_id)))
        self.last_deleted = note
        return note

    def restore_last_deleted(self) -> Note | None:
        note = self.last_deleted
        if note is None:
            return None
        if self.duration_ms is not None and note.time_ms > self.duration_ms:
            note = replace(note, time_ms=self.duration_ms)
        self._change(lambda notes: notes.append(note))
        self.last_deleted = None
        return note

    def shift_all(self, offset_ms: int) -> None:
        """Batch shift (NOTE-13); results are limited to the audio."""
        upper = self.duration_ms

        def shift(notes):
            for i, n in enumerate(notes):
                t = max(0, n.time_ms + offset_ms)
                if upper is not None:
                    t = min(t, upper)
                notes[i] = replace(n, time_ms=t, time_source="manual", edited_at=now_iso())
        self._change(shift)

    # --- internals -----------------------------------------------------------------------

    def _check_time(self, time_ms: int) -> None:
        if time_ms < 0 or (self.duration_ms is not None and time_ms > self.duration_ms):
            raise ValueError(f"timestamp {time_ms} ms is outside the audio")

    def _replace(self, note_id: str, **changes) -> Note:
        result = []

        def apply(notes):
            for i, n in enumerate(notes):
                if n.id == note_id:
                    notes[i] = replace(n, **changes)
                    result.append(notes[i])
                    return
            raise KeyError(note_id)
        self._change(apply)
        return result[0]

    def _change(self, apply: Callable[[list[Note]], None]) -> None:
        if FileStamp.of(self.path) != self._stamp:
            self.load()  # edited on disk since loading: apply our change on top (§7.1)
        notes = list(self.notes)
        apply(notes)
        self._stamp = write_json(self.path, {"notes": [asdict(n) for n in notes]})
        self.notes = sorted(notes, key=Note.sort_key)
        self.faulty_count = 0  # faulty entries were dropped by this save (NOTE-05b)
