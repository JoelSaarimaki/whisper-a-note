"""Whisper model files: availability check and download (SPEC §8.4, DIST-04).

Downloading is the only network use besides setup, and only on the user's request.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_MODEL = "large-v3-turbo"  # Q44
MODELS = ("large-v3-turbo", "large-v3", "medium", "small")


def is_available(name: str, models_dir: Path | None) -> bool:
    from faster_whisper.utils import download_model
    try:
        download_model(name, local_files_only=True, cache_dir=str(models_dir) if models_dir else None)
        return True
    except Exception:
        return False


def download(name: str, models_dir: Path | None) -> None:
    from faster_whisper.utils import download_model
    if models_dir:
        models_dir.mkdir(parents=True, exist_ok=True)
    download_model(name, cache_dir=str(models_dir) if models_dir else None)
