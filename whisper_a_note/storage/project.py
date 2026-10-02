"""A project folder and its recordings (SPEC §5.1, §7.1)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from .jsonfile import FileStamp, read_json, write_json

AUDIO_EXTENSIONS = (".flac", ".wav", ".mp3", ".m4a", ".ogg")
TRACK_SUFFIXES = (".mic", ".system")  # secondary suffixes of the separate tracks
LANGUAGE_MODES = ("auto", "fixed")


@dataclass(frozen=True)
class ProjectSettings:
    name: str
    context: str = ""
    language_mode: str = "auto"
    language: str | None = None  # used when language_mode == "fixed"


def default_project_name(title: str, today: datetime | None = None) -> str:
    """PRJ-02 default: `YYYY-MM-DD <title>`."""
    return f"{(today or datetime.now()):%Y-%m-%d} {title}".strip()


class Project:
    FILE = "project.json"

    def __init__(self, folder: Path):
        """Open an existing folder; an empty or new folder is a new project (PRJ-03)."""
        self.folder = folder
        self._stamp: FileStamp | None = None
        self.settings = ProjectSettings(name=folder.name)
        self.load()

    @classmethod
    def create(cls, projects_folder: Path, name: str) -> Project:
        folder = projects_folder / name
        folder.mkdir(parents=True, exist_ok=False)
        project = cls(folder)
        project.update(name=name)
        return project

    def load(self) -> None:
        """Raises UnreadableFileError if project.json exists but cannot be read (NFR-09)."""
        data, self._stamp = read_json(self.folder / self.FILE)
        data = data or {}
        def text(key, default):
            v = data.get(key, default)
            return v if isinstance(v, str) else default
        mode = data.get("language_mode", "auto")
        self.settings = ProjectSettings(
            name=text("name", self.folder.name),
            context=text("context", ""),
            language_mode=mode if mode in LANGUAGE_MODES else "auto",
            language=data.get("language") if isinstance(data.get("language"), str) else None,
        )

    def update(self, **changes) -> ProjectSettings:
        path = self.folder / self.FILE
        if FileStamp.of(path) != self._stamp:
            self.load()
        self.settings = replace(self.settings, **changes)
        self._stamp = write_json(path, asdict(self.settings))
        return self.settings

    # --- recordings ----------------------------------------------------------------------

    def recordings(self) -> list[str]:
        """Base names of the project's recordings, sorted.

        A recording is an audio file without a track suffix (`.mic`, `.system`), or a
        `*.recording.json` whose audio is not finished yet (to be recovered, REC-12).
        """
        names = set()
        for p in self.folder.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() in AUDIO_EXTENSIONS:
                stem = Path(p.stem)
                if stem.suffix.lower() not in TRACK_SUFFIXES:
                    names.add(p.stem)
            elif p.name.endswith(".recording.json"):
                names.add(p.name[: -len(".recording.json")])
        return sorted(names)

    def new_base_name(self, started: datetime | None = None, stem: str | None = None) -> str:
        """`YYYY-MM-DD_HHMM` (or an imported file's stem), with `_2`, `_3`… if taken."""
        base = stem or f"{(started or datetime.now()):%Y-%m-%d_%H%M}"
        candidate, n = base, 2
        while self._taken(candidate):
            candidate, n = f"{base}_{n}", n + 1
        return candidate

    def _taken(self, base: str) -> bool:
        return any(p.name.startswith(base + ".") for p in self.folder.iterdir())

    def path(self, base: str, kind: str) -> Path:
        """File of a recording, e.g. path(base, 'notes.json') or path(base, 'mic.wav')."""
        return self.folder / f"{base}.{kind}"
