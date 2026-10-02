"""Entry point: `python -m whisper_a_note` (PKG-1)."""
import argparse
import multiprocessing
import sys

SUPPORTED_PYTHON = ((3, 11), (3, 12))


def check_python() -> None:
    """DIST-03: clear message instead of obscure import errors."""
    if not (SUPPORTED_PYTHON[0] <= sys.version_info[:2] <= SUPPORTED_PYTHON[1]):
        lo, hi = (".".join(map(str, v)) for v in SUPPORTED_PYTHON)
        sys.exit(f"Whisper A Note needs Python {lo} to {hi}; this is Python {sys.version.split()[0]}.")


def main() -> None:
    multiprocessing.freeze_support()  # PKG-5
    check_python()
    parser = argparse.ArgumentParser(prog="whisper_a_note")
    parser.add_argument("--download-models", action="store_true",
                        help="download the default Whisper model (used by the setup scripts)")
    args = parser.parse_args()

    if args.download_models:
        from . import paths
        from .transcription import models
        print(f"Downloading Whisper model {models.DEFAULT_MODEL} (~1.6 GB) ...")
        models.download(models.DEFAULT_MODEL, paths.whisper_models_dir())
        print("Done.")
        return
    print("Whisper A Note: the user interface is not implemented yet.")


if __name__ == "__main__":
    main()
