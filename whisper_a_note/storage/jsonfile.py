"""Safe reading and writing of the app's JSON files (SPEC §7.1, NFR-09).

- Unreadable files raise `UnreadableFileError`; the app never treats them as empty or
  overwrites them.
- Writes go to a temporary file in the same folder and are renamed over the original.
- A file changed on disk since it was loaded is detected before writing, so callers can
  reload and re-apply their change instead of overwriting the other edit.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class UnreadableFileError(Exception):
    """A file exists but cannot be read. Writing to it is not allowed (NFR-09)."""

    def __init__(self, path: Path, problem: str):
        super().__init__(f"{path.name}: {problem}")
        self.path = path
        self.problem = problem


@dataclass(frozen=True)
class FileStamp:
    """What the file looked like when it was loaded, to detect external edits."""
    mtime_ns: int
    size: int

    @classmethod
    def of(cls, path: Path) -> FileStamp | None:
        try:
            st = path.stat()
        except FileNotFoundError:
            return None
        return cls(st.st_mtime_ns, st.st_size)


def read_json(path: Path) -> tuple[dict[str, Any] | None, FileStamp | None]:
    """Return (data, stamp); (None, None) if the file does not exist."""
    stamp = FileStamp.of(path)
    if stamp is None:
        return None, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise UnreadableFileError(path, f"cannot be read ({e.strerror or e})") from e
    except UnicodeDecodeError as e:
        raise UnreadableFileError(path, "is not valid UTF-8 text") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise UnreadableFileError(path, f"is not valid JSON (line {e.lineno}: {e.msg})") from e
    if not isinstance(data, dict):
        raise UnreadableFileError(path, "does not contain a JSON object")
    version = data.get("schema_version")
    if not isinstance(version, int) or version < 1:
        raise UnreadableFileError(path, "has no valid schema_version")
    if version > SCHEMA_VERSION:
        raise UnreadableFileError(path, f"uses schema_version {version}, newer than this app supports")
    return data, stamp


def write_json(path: Path, data: dict[str, Any]) -> FileStamp:
    """Write atomically: temporary file in the same folder, then rename over the original."""
    data = {"schema_version": SCHEMA_VERSION, **{k: v for k, v in data.items() if k != "schema_version"}}
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    stamp = FileStamp.of(path)
    assert stamp is not None
    return stamp
