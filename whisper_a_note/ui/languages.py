"""Language choices for transcription (CTX-03, §5.6.1)."""
from __future__ import annotations

NAMES = {
    "en": "English", "fi": "Finnish", "sv": "Swedish", "no": "Norwegian", "da": "Danish",
    "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch", "et": "Estonian", "ru": "Russian", "pl": "Polish", "uk": "Ukrainian",
    "cs": "Czech", "hu": "Hungarian", "is": "Icelandic", "lt": "Lithuanian", "lv": "Latvian",
    "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "tr": "Turkish",
    "hi": "Hindi", "el": "Greek", "he": "Hebrew", "ro": "Romanian", "sk": "Slovak",
}


def all_languages() -> list[tuple[str, str]]:
    """(code, display name) for every language Whisper supports, named ones first."""
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES as codes
    except ImportError:
        codes = tuple(NAMES)
    named = sorted(((c, NAMES[c]) for c in codes if c in NAMES), key=lambda x: x[1])
    other = sorted((c, c) for c in codes if c not in NAMES)
    return named + other


def name(code: str | None) -> str:
    return "Auto-detect" if code is None else NAMES.get(code, code)
