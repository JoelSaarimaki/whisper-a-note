"""Language choices for transcription (CTX-03, §5.6.1)."""
from __future__ import annotations

# All languages Whisper supports, with English names.
NAMES = {
    "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "as": "Assamese", "az": "Azerbaijani",
    "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian", "bn": "Bengali", "bo": "Tibetan",
    "br": "Breton", "bs": "Bosnian", "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian", "eu": "Basque",
    "fa": "Persian", "fi": "Finnish", "fo": "Faroese", "fr": "French", "gl": "Galician",
    "gu": "Gujarati", "ha": "Hausa", "haw": "Hawaiian", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "ht": "Haitian Creole", "hu": "Hungarian", "hy": "Armenian", "id": "Indonesian",
    "is": "Icelandic", "it": "Italian", "ja": "Japanese", "jw": "Javanese", "ka": "Georgian",
    "kk": "Kazakh", "km": "Khmer", "kn": "Kannada", "ko": "Korean", "la": "Latin",
    "lb": "Luxembourgish", "ln": "Lingala", "lo": "Lao", "lt": "Lithuanian", "lv": "Latvian",
    "mg": "Malagasy", "mi": "Maori", "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian",
    "mr": "Marathi", "ms": "Malay", "mt": "Maltese", "my": "Burmese", "ne": "Nepali", "nl": "Dutch",
    "nn": "Norwegian Nynorsk", "no": "Norwegian", "oc": "Occitan", "pa": "Punjabi", "pl": "Polish",
    "ps": "Pashto", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sa": "Sanskrit",
    "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "sn": "Shona", "so": "Somali",
    "sq": "Albanian", "sr": "Serbian", "su": "Sundanese", "sv": "Swedish", "sw": "Swahili",
    "ta": "Tamil", "te": "Telugu", "tg": "Tajik", "th": "Thai", "tk": "Turkmen", "tl": "Tagalog",
    "tr": "Turkish", "tt": "Tatar", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek",
    "vi": "Vietnamese", "yi": "Yiddish", "yo": "Yoruba", "yue": "Cantonese", "zh": "Chinese",
}


# Shown by default; "Show all languages" in Settings lists all of them (CTX-03a).
COMMON = {
    "ar", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "he", "hi", "hu", "is", "it",
    "ja", "ko", "lt", "lv", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sv", "tr", "uk", "zh",
}


def all_languages() -> list[tuple[str, str]]:
    """(code, name) for every language Whisper supports, sorted by name."""
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES as codes
    except ImportError:
        codes = tuple(NAMES)
    return sorted(((c, NAMES.get(c, c)) for c in codes), key=lambda x: x[1])


def choices(show_all: bool, keep: str | None = None) -> list[tuple[str, str]]:
    """The languages for a list: common ones, or all; `keep` (the current choice) is always included."""
    return [(c, n) for c, n in all_languages() if show_all or c in COMMON or c == keep]


def fill_combo(combo, fixed: list[tuple[str, object]], show_all: bool, current) -> None:
    """Fill a language combo box: fixed entries first (e.g. Auto-detect), then languages."""
    combo.blockSignals(True)
    combo.clear()
    for label, data in fixed:
        combo.addItem(label, data)
    for code, label in choices(show_all, current if isinstance(current, str) else None):
        combo.addItem(label, code)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


def name(code: str | None) -> str:
    return "Auto-detect" if code is None else NAMES.get(code, code)
