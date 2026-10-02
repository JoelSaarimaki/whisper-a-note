# Third-party licences

Whisper A Note is MIT-licensed (see `LICENSE`). It bundles or downloads the following
models, and depends on the libraries below. This list is kept up to date as
dependencies change (SPEC PKG-8) and is shown in the app's About screen.

## Bundled models

| Model | Licence | Location |
|---|---|---|
| pyannote speaker-diarization-community-1 | CC BY 4.0 | `whisper_a_note/models/pyannote/speaker-diarization-community-1/` (see its `LICENSE.md`) |

## Downloaded during setup

| Model | Licence | Source |
|---|---|---|
| Whisper large-v3-turbo (CTranslate2 conversion) | MIT | https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo |

## Main libraries

| Library | Licence |
|---|---|
| faster-whisper, CTranslate2 | MIT |
| pyannote.audio | MIT |
| PyTorch, torchaudio | BSD-3-Clause |
| PyAV (bundles FFmpeg libraries) | BSD-3-Clause (FFmpeg: LGPL-2.1+) |
| soundfile (bundles libsndfile) | BSD-3-Clause (libsndfile: LGPL-2.1+) |
| soundcard | BSD-3-Clause |
| soxr (python-soxr) | LGPL-2.1+ |
| NumPy | BSD-3-Clause |
| platformdirs | MIT |

The full list of pinned dependencies is in `requirements.txt`.
