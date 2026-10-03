"""App settings in the per-user config folder (PKG-3)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from .. import paths
from ..storage.jsonfile import UnreadableFileError, read_json, write_json
from ..transcription.models import DEFAULT_MODEL


@dataclass
class AppSettings:
    projects_folder: str | None = None
    mic_device: str | None = None        # None = system default
    system_device: str | None = None     # output device whose audio is recorded
    model: str = DEFAULT_MODEL
    preroll_segment_s: float = 2.0       # TL-07a
    preroll_note_s: float = 5.0
    confidence_threshold: float = 0.70   # Q9
    highlight_low_confidence: bool = True  # TRN-06
    export_marker: str = "italic"        # §5.8.1
    export_separate: bool = False        # EXP-02: separate Markdown files instead of one
    show_all_languages: bool = False     # CTX-03a: otherwise only common languages are listed
    recent_projects: list = field(default_factory=list)
    measured_rtf: dict = field(default_factory=dict)  # model -> processing time / audio time (TRN-07a)
    recording_geometry: str | None = None
    review_geometry: str | None = None

    # Not saved: set when the settings file exists but cannot be read (NFR-09).
    load_error: str | None = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls) -> AppSettings:
        path = paths.user_config_dir() / "settings.json"
        try:
            data, _ = read_json(path)
        except UnreadableFileError as e:
            s = cls()
            s.load_error = str(e)
            return s
        names = {f.name for f in fields(cls)} - {"load_error"}
        defaults = cls()
        values = {}
        for k, v in (data or {}).items():
            if k in names and (v is None or isinstance(v, type(getattr(defaults, k))) or
                               isinstance(getattr(defaults, k), float) and isinstance(v, int)):
                values[k] = v
        return cls(**values)

    def save(self) -> None:
        if self.load_error:  # never overwrite a file that could not be read
            return
        folder = paths.user_config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("load_error")
        write_json(folder / "settings.json", data)

    def add_recent(self, folder: str) -> None:
        self.recent_projects = [folder] + [p for p in self.recent_projects if p != folder][:9]
