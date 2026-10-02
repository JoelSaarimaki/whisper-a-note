"""All app paths in one place (SPEC PKG-3, PKG-4)."""
from pathlib import Path

import platformdirs

APP_NAME = "Whisper A Note"


def user_data_dir() -> Path:
    """Per-user data: downloaded Whisper models, logs."""
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def user_config_dir() -> Path:
    """Per-user settings."""
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def whisper_models_dir() -> Path:
    return user_data_dir() / "models" / "whisper"


def logs_dir() -> Path:
    return user_data_dir() / "logs"
