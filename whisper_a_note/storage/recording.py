"""Recording metadata in `<base>.recording.json` (SPEC §7.2)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .jsonfile import FileStamp, read_json, write_json

MUTE_SOURCES = ("mic", "system", "all")
MUTE_REASONS = ("user", "device_lost", "system_sleep")


@dataclass(frozen=True)
class Mute:
    source: str
    reason: str
    start_ms: int
    end_ms: int | None  # None while the interval is still open (during recording)


@dataclass(frozen=True)
class RecordingMeta:
    source: str = "recorded"            # or "imported"
    started_at: str | None = None
    duration_ms: int | None = None      # None until the recording ends or is recovered
    end_requested_ms: int | None = None  # REC-04a
    sample_rate: int = 16000
    devices: dict = field(default_factory=dict)
    language: str | None = None         # per-recording override (CTX-03)
    context: str = ""                   # recording context (CTX-06)
    mutes: tuple[Mute, ...] = ()


def _is_ms(v, allow_none=False) -> bool:
    if v is None:
        return allow_none
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _parse_mute(entry) -> Mute | None:
    if not isinstance(entry, dict):
        return None
    m = Mute(entry.get("source"), entry.get("reason", "user"), entry.get("start_ms"), entry.get("end_ms"))
    if m.source not in MUTE_SOURCES or m.reason not in MUTE_REASONS:
        return None
    if not _is_ms(m.start_ms) or not _is_ms(m.end_ms, allow_none=True):
        return None
    if m.end_ms is not None and m.end_ms < m.start_ms:
        return None
    return m


class RecordingFile:
    def __init__(self, path: Path):
        self.path = path
        self.meta = RecordingMeta()
        self.faulty_count = 0
        self._stamp: FileStamp | None = None
        self.load()

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> None:
        """Raises UnreadableFileError if the file exists but cannot be read (NFR-09)."""
        data, self._stamp = read_json(self.path)
        data = data or {}
        mutes, faulty = [], 0
        for entry in data.get("mutes", []) if isinstance(data.get("mutes", []), list) else []:
            m = _parse_mute(entry)
            if m is None:
                faulty += 1
            else:
                mutes.append(m)
        defaults = RecordingMeta()
        def pick(key, ok):
            v = data.get(key, getattr(defaults, key))
            if ok(v):
                return v
            nonlocal faulty
            faulty += 1
            return getattr(defaults, key)
        self.meta = RecordingMeta(
            source=pick("source", lambda v: v in ("recorded", "imported")),
            started_at=pick("started_at", lambda v: v is None or isinstance(v, str)),
            duration_ms=pick("duration_ms", lambda v: _is_ms(v, allow_none=True)),
            end_requested_ms=pick("end_requested_ms", lambda v: _is_ms(v, allow_none=True)),
            sample_rate=pick("sample_rate", lambda v: isinstance(v, int) and v > 0),
            devices=pick("devices", lambda v: isinstance(v, dict)),
            language=pick("language", lambda v: v is None or isinstance(v, str)),
            context=pick("context", lambda v: isinstance(v, str)),
            mutes=tuple(m for m in mutes
                        if data.get("duration_ms") is None or m.start_ms <= data["duration_ms"]),
        )
        self.faulty_count = faulty

    def update(self, **changes) -> RecordingMeta:
        """Change fields and save; reloads first if the file was edited on disk (§7.1)."""
        if FileStamp.of(self.path) != self._stamp:
            self.load()
        self.meta = replace(self.meta, **changes)
        data = asdict(self.meta)
        data["mutes"] = [asdict(m) for m in self.meta.mutes]
        self._stamp = write_json(self.path, data)
        self.faulty_count = 0
        return self.meta
