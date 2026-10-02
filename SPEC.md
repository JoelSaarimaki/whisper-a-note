# Whisper A Note — Specification

| | |
|---|---|
| **Status** | Draft v0.6 — all open questions resolved |
| **Date** | 2026-10-02 |

Requirements are identified as `AREA-NN` so they can be referenced in issues and tests. Priority: **P1** = required for the first release (MVP), **P2** = planned follow-up, **P3** = nice to have. Items marked *(proposed)* are suggested additions beyond the user's requests.

---

## 1. Overview

### 1.1 Purpose

**Whisper A Note** is a local, privacy-preserving desktop application for recording and transcribing meetings, interviews and facilitated discussions. It combines three sources of information on a single timeline:

1. **Audio** — recorded from microphone and system audio, or imported.
2. **Automatic transcript** — with speaker diarization and per-word confidence.
3. **Manual notes** — timestamped notes written by the user during or after the meeting.

The result is exported as Markdown that is easy to read and to process further, e.g. with AI tools.

### 1.2 Goals

- **Data safety:** all audio, text and processing stay on the user's machine. No cloud services, no telemetry.
- **Unobtrusive during meetings:** the user is conducting an interview or facilitating; the tool must not demand attention.
- **Trustworthy output:** retain confidence data so the reliability of the transcript can be assessed later.
- **Portable data:** plain files in a plain folder structure, readable without the app.

### 1.3 Non-goals (v1)

- Live / real-time transcription during recording.
- Cloud sync, multi-user collaboration or sharing.
- Built-in AI summarisation (export is designed so external tools can do this).
- Video recording.
- Installers or standalone executables (the app runs from source with pip; see §8.5).

---

## 2. Key decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Native desktop app built with Python + PySide6 (Qt 6)** | Single language and process for UI, audio and ML; supports freely resizable windows and a custom timeline view. A browser UI was rejected as too disruptive during meetings. |
| D2 | **Cross-platform: Windows, macOS, Linux** | System audio capture differs per OS (see §8.3). macOS requires **14.2 or later** (Core Audio process taps). Windows is expected to be the primary development target. |
| D3 | **Two UI modes: compact *Recording mode* and full *Review mode*** | Minimal footprint while the meeting is ongoing; full timeline and tools afterwards. |
| D4 | **Microphone and system audio stored as separate tracks, plus a mixed playback file** | Enables independent muting and re-mixing, and the track source (local vs. remote) can improve speaker diarization. Costs only disk space. |
| D5 | **Transcription runs on demand after recording, never during** | Avoids CPU/GPU load and complexity during the meeting; allows best-quality models. |
| D6 | **Transcription: `faster-whisper`; diarization: `pyannote.audio`** | faster-whisper is a faster, lighter implementation of OpenAI Whisper that provides word timestamps and per-word probabilities (used as confidence). pyannote is the standard open-source diarization toolkit. |

---

## 3. Glossary

| Term | Meaning |
|---|---|
| **Projects folder** | Root directory configured in the app. Contains one subfolder per project. |
| **Project** | A folder representing one meeting/engagement. May contain several recordings. |
| **Recording** | One audio file (recorded or imported) and all files associated with it. |
| **Base name** | The shared file name stem linking a recording's audio, transcript and notes files. |
| **Context text** | Free text describing the meeting (topic, names, jargon) used to guide transcription: one **project context** shared by all recordings (CTX-01), plus an optional **recording context** per recording (CTX-06). |
| **Manual note** | A user-written, timestamped text entry. |
| **Transcript** | Output of transcription + diarization: speaker-attributed segments with words, timestamps and confidence. |
| **Timeline** | Vertical, time-based view combining audio, transcript and notes. |
| **Audio time** | Position in milliseconds relative to the start of a recording's audio. |

---

## 4. User workflow

```
 Review mode: select / create project
            │
            ├──► New recording ──► Recording setup: project, context texts, devices + sound check
            │                         │
            │                         ▼
            │                      Record audio, writing timestamped notes in parallel (Recording mode)
            │                         │
            └──► Import audio file ───┤
                                      ▼
                         Run transcription + diarization on demand
                                      │
                                      ▼
                         Review on timeline: listen, read, edit notes (Review mode)
                                      │
                                      ▼
                         Export to Markdown
```

Context texts are edited in Review mode (and in the recording setup, REC-20) and can be changed at any time; changes affect the next transcription run.

---

## 5. Functional requirements

### 5.1 Projects (PRJ)

| ID | Pri | Requirement |
|---|---|---|
| PRJ-01 | P1 | The user configures a **projects folder** path in settings. The setting persists between sessions. |
| PRJ-02 | P1 | The user can create a **new project**; the app creates a subfolder in the projects folder (name entered by user, default `YYYY-MM-DD <title>`). |
| PRJ-03 | P1 | The user can **open any existing folder** as a project. An empty folder is treated as a new project. |
| PRJ-04 | P1 | A project lists its **recordings** (audio files). Selecting a recording loads its associated transcript and notes, matched by base name (see §7). |
| PRJ-05 | P2 | Recently opened projects are listed for quick access. |
| PRJ-06 | P2 | A recording can be renamed from the app; all associated files are renamed consistently. |
| PRJ-07 | P2 | A recording or a whole project can be **deleted** from the app, after a confirmation. The files are moved to the system **recycle bin / trash**, not deleted permanently. |

### 5.2 Context (CTX)

| ID | Pri | Requirement |
|---|---|---|
| CTX-01 | P1 | Each **project** has **one context text**, shared by all its recordings and editable at any time. |
| CTX-02 | P1 | The context text is passed to Whisper as the initial prompt **and** as `hotwords`, so it guides every 30-second window and not only the start of the recording (faster-whisper's initial prompt is soon pushed out by the previously transcribed text; to be confirmed in Phase 0). Whisper's prompt limit is about 220 tokens: roughly 100–150 words in English, fewer in languages such as Finnish. The UI hints that the text should be **short (about 100 words)** and list key names and terms concisely. |
| CTX-03 | P1 | **Language setting** per project: **Auto-detect**, or a **fixed language** chosen from all languages Whisper supports. A recording can override the project setting before transcription. See §5.6.1. |
| CTX-04 | P2 | **Mixed-language mode:** the user selects a short list of expected languages (e.g. Finnish, Swedish, English), and language is detected per speaker turn. See §5.6.1. |
| CTX-05 | P2 | Optional field for **expected number of speakers** (passed to diarization). |
| CTX-06 | P1 | Each **recording** has an optional **recording context** ("other notes"): free text for things specific to that recording, e.g. its participants, topics, terms, or remarks about the meeting as a whole. It is editable at any time in Review mode and in the recording setup (REC-20), combined with the project context for transcription (project context first; the length hint of CTX-02 applies to the combined text), and included in the export. |

### 5.3 Recording (REC)

| ID | Pri | Requirement |
|---|---|---|
| REC-01 | P1 | Record simultaneously from a selected **microphone** and the **system audio** output. |
| REC-02 | P1 | **Live level meters** (mixer-style, with peak indication) for mic and system audio are shown in **Recording mode**, both before and during recording, so the user can check the input before pressing Start. A source with no signal (e.g. a wrong device) is visible from its meter; there is no separate warning. They are not shown in Review mode. The audio devices are opened only while Recording mode (or a sound check, REC-11) is open, and released otherwise. |
| REC-03 | P1 | **Mute toggles** for mic and system audio are always visible in Recording mode. A muted source records silence (keeps tracks time-aligned). Mutes set before Start apply from the start of the recording. |
| REC-04 | P1 | Controls: **Start** and **End**. There is **no pause**: ending is final, and an ended recording cannot be continued (a new recording is started instead). Elapsed recording time is displayed; it shows audio time, so it matches the note timestamps (it does not advance during system sleep, REC-19). |
| REC-04a | P1 | **Ending with a grace period:** pressing End (or `/end`) does not end the recording at once. For **5 seconds**, Recording mode shows **"Ending recording…"** with a countdown, and a **Cancel** button appears in exactly the place of the End button, so stopping an unintended End needs no mouse movement. During this time, recording continues normally. If cancelled, the recording simply goes on without a gap. If not, the recording ends **at the moment End was pressed**: the audio captured during the grace period is cut from the final result, and its duration ends there. A note submitted during the grace period becomes the closing note (NOTE-02b), stamped at that end point; if ending is cancelled, it stays as a normal note at that time. Closing the app during the grace period completes the ending. |
| REC-05 | P1 | Audio is **written to disk continuously** during recording, so a crash or power loss loses at most a few seconds. |
| REC-06 | P1 | **Mute all** ("off the record"): one toggle that mutes both sources at once, replacing a pause feature. Recording time keeps running, and notes work exactly as when not muted: they get normal timestamps and are exported like any other note. All mute periods (mic, system or both) are stored as **mute intervals** in the recording metadata. While Mute all is on, Recording mode shows a **clear, persistent indicator** (e.g. a "Muted – off the record" banner in the header and the toggle highlighted); there are no reminders or pop-ups. |
| REC-06a | P1 | Fully muted intervals are **skipped by transcription**, which also prevents Whisper from inventing text in long silences (a known failure mode; faster-whisper's voice-activity filter is enabled as well). |
| REC-07 | P1 | When ending completes (REC-04a), the app produces the **mixed playback file** from the two tracks. The tracks come from different devices whose clocks can drift apart slightly over a long recording. This is a **minor concern**: it is checked in passing during Phase 0, and corrected (e.g. by resampling one track) only if it turns out to be noticeable. |
| REC-08 | P1 | Input devices are selectable in the recording setup (REC-20) and in settings; the last choice is remembered. |
| REC-09 | P2 | An **external audio file** (wav, mp3, m4a, flac, ogg) can be imported into a project instead of recording. It is copied into the project folder. |
| REC-11 | P1 | **Sound check** outside Recording mode: in the recording setup (REC-20) and the device settings, the user can open a sound check that shows the level meters for the selected devices. It is opened on demand, not always visible, and releases the devices when closed. |
| REC-12 | P1 | **Recovery of unfinished recordings:** `*.recording.json` is written when recording starts and updated on End. On startup and when opening a project, the app detects recordings left unfinished by a crash or power loss (WAV tracks, no End) and finishes them: determines the duration from the audio, cuts the audio at the End point if End had been pressed (REC-04a), closes any open mute interval at the end of the audio, converts the tracks to FLAC and creates the mixed file. Saved notes are kept. The user is told which recording was recovered. |
| REC-13 | P1 | **Device lost during recording** (e.g. headset unplugged, Bluetooth dropped, default output device changed): recording continues; the affected track records silence, Recording mode shows a clear warning, and the device (or the new default output) is used again automatically when available. The gap is stored as an interval with reason `device_lost` and shown on the timeline like a mute interval. |
| REC-14 | P1 | **A recording always belongs to a project.** Recording mode is entered through the recording setup (REC-20), where the project is chosen or created. |
| REC-15 | P1 | **While recording**, switching to another project or recording is disabled until End, so notes cannot end up in the wrong recording. |
| REC-16 | P1 | **No recording during transcription:** Start is disabled while a transcription is running, with a hint that the job must be interrupted (or stopped) first. |
| REC-17 | P1 | **Closing the app during recording** asks for confirmation ("End recording?"); confirming ends the recording normally. |
| REC-18 | P1 | **Disk space:** before Start, the app warns if free space is low (e.g. below 1 GB). If the disk fills up during recording, the recording ends safely, keeping all audio written so far, with a clear message. |
| REC-19 | P1 | **System sleep during recording** (e.g. lid closed): after wake-up, recording continues from the same audio time; no silence is inserted for the time asleep. The point is stored as a zero-length interval with reason `system_sleep` and shown as a marker on the timeline. |
| REC-20 | P1 | **Recording setup:** a short step before entering Recording mode, opened from Review mode ("New recording"). In one view, the user:<br>• picks the project or creates a new one and sets its name (PRJ-02);<br>• edits the project context and the new recording's context (CTX-01, CTX-06), and optionally its language (CTX-03);<br>• selects the mic and system audio devices and checks them with the sound check (REC-08, REC-11).<br>Confirming opens Recording mode, ready to Start. The recording's files are created on Start; cancelling the setup creates nothing. After End, starting another recording goes through the setup again, pre-filled with the same project and devices.<br>**Leaving without recording:** project changes (a new project, its name, project context edits) are saved when the setup is confirmed, as they belong to the project. Leaving Recording mode before Start (Review button) never creates a recording: no files and no empty entry in the recording list. The recording context and any draft note in the input are kept until the app is closed, and the next "New recording" in that project starts with them filled in. |

### 5.4 Manual notes (NOTE)

| ID | Pri | Requirement |
|---|---|---|
| NOTE-01 | P1 | Notes are entered in a **chat-style input**: type and press Enter to submit. Each note becomes an entry in the note list. |
| NOTE-02 | P1 | Notes can only be added when the selected recording **is being recorded, has been recorded, or has been imported**. |
| NOTE-02a | P1 | **Pre-written notes:** in Recording mode before the recording has started, the user can type in the note input, but **Enter does not submit**: the text stays in the input as a draft, and a hint says that notes can be submitted once recording starts. After Start, Enter submits the draft as usual, with the submission time as its timestamp (NOTE-03). Chat commands such as `/start` (§5.5) still work before recording. |
| NOTE-02b | P1 | **Closing note after End:** in Recording mode, one last note can still be submitted after End. It is timestamped at the **end of the recording** and added to the note list, and its text **stays in the input**. Each further Enter **replaces** that closing note with the current text instead of adding a new one, so the user can refine it. Only the closing note submitted after End is replaced, never other notes. Submitting an empty input does nothing. If the closing note's **timestamp is changed** to an earlier time, or the note is **deleted**, it stops being the closing note: it is no longer replaced (a moved note stays as a normal note), its text is cleared from the input, and the slot at the end is free, so the next Enter adds a new closing note. If its text is edited in the note list, the input shows the edited text. Starting a new recording clears the input. Notes never lie beyond the recording's end (NOTE-05); other notes are added within the duration in Review mode (NOTE-04, TL-09), and longer remarks about the meeting can go into the recording context (CTX-06). The Recording mode header keeps showing the ended recording until Start begins a new one. |
| NOTE-03 | P1 | **During recording**, a note's timestamp is the audio time at the moment of submission. Because recording cannot be paused, every note written during recording gets its own, distinct timestamp. |
| NOTE-04 | P1 | **In Review mode**, notes are added with the note input of the notes column; the timestamp is set manually when submitting and defaults to the current playback position. (The closing note, NOTE-02b, is the only note added in Recording mode outside the recording.) |
| NOTE-05 | P1 | Timestamps always lie **within the audio** (00:00 to the end). Manual timestamps are limited to this range. Notes that concern the whole meeting can be placed at the start or the end. |
| NOTE-05a | P1 | If notes have the **same timestamp** (e.g. set manually or by dragging), they keep their creation order. |
| NOTE-05b | P1 | **Faulty entries:** a source file may contain faulty entries, e.g. after manual editing of the files: notes or transcript segments with timestamps **outside the audio**, or entries that are **otherwise faulty** (missing or malformed fields, invalid values). These are:<br>• **ignored**: hidden from all UI views and excluded from all exports;<br>• **not protected**: the app does not preserve them; they are dropped when the app next rewrites the file;<br>• **indicated**: the recording shows a warning badge in the recording list and the timeline header, e.g. "2 faulty notes are ignored and will be removed on the next save". |
| NOTE-06 | P1 | Notes can be **edited and deleted**, in both Recording mode and Review mode. Editing the text does **not** change the timestamp. The original creation time is retained alongside the edit time. |
| NOTE-06a | P1 | **Delete without confirmation, restore instead:** deleting a note happens immediately, and the **last deleted note can be restored** (e.g. an "Undo" link shown after deleting, and Ctrl+Z / Cmd+Z). It comes back with its original timestamp, text and creation time, as a normal note. Restoring is possible until the app is closed. When working fast, undoing a mistake is easier than confirming every action, and re-typing the note would give it a new timestamp. Only deleting can be undone; text edits are corrected by editing again. |
| NOTE-07 | P1 | A note's **timestamp can be changed** manually, in **Review mode only**; Recording mode does not offer timestamp editing, as it is too easy to get wrong while working fast. Notes are always displayed in timestamp order, so changing a timestamp can reorder the list. |
| NOTE-08 | P1 | Notes are **saved automatically** after every change. |
| NOTE-10 | P2 | On the timeline, notes can be **dragged vertically** to set the timestamp precisely. |
| NOTE-13 | P2 | **Batch shift:** on the timeline, the timestamps of **all manual notes** of a recording can be shifted by the same offset at once (e.g. −5 s), to compensate for notes being submitted after the speech they describe. Shifted timestamps are limited to the audio (NOTE-05); notes that would fall outside it are placed at the start or the end, keeping their order. |

**Notes may overlap with the transcript.** Manual notes are not only observations; they are often the user's own attempt to capture what is being said. Therefore:

- Notes and transcript are **never merged or de-duplicated**; both are kept as independent sources.
- A note has **only one timestamp**: the moment it was submitted (or the time set manually). In the timeline, it is shown next to whatever transcript is at the same time, making it easy to compare the two. Notes are usually submitted a little after the speech they describe; the user can correct this by editing the timestamp (NOTE-07), dragging the note on the timeline (NOTE-10) or shifting all notes at once (NOTE-13).
- In the export, notes are clearly marked as user-written so readers and AI tools can treat them as a second, human source. Where they disagree with a low-confidence transcript passage, the note is often the more reliable one.

### 5.5 Chat commands (CMD) — P2

Messages starting with `/` in the note input are interpreted as commands and are not saved as notes.

| Command | Short | Action |
|---|---|---|
| `/start` | `/s` | Start recording |
| `/end` | — | End recording (with the grace period, REC-04a). No short form, so it cannot be typed by accident. |
| `/mute` | `/m` | Toggle mute all (off the record) |

- Unknown commands show an inline error and are not submitted as notes.
- A message starting with `//` is saved as a note beginning with a single `/`.

### 5.6 Transcription (TRN)

| ID | Pri | Requirement |
|---|---|---|
| TRN-01 | P1 | Transcription is started **manually** per recording. **Only one transcription at a time:** a transcription cannot be started while any recording is being recorded, or while another transcription is **running**. Interrupting a job frees the slot, so a forgotten interrupted job never blocks others; several recordings can have interrupted jobs waiting to be resumed. |
| TRN-02 | P1 | Output: speaker-attributed **segments** with start/end times, and **words** with start/end times and a **confidence** value (0–1). |
| TRN-03 | P1 | Speaker diarization assigns generic labels (`Speaker 1`, `Speaker 2`, …). |
| TRN-04 | P1 | Job controls: **Start, Interrupt, Resume, Stop, Restart** (see job states below). **Restart clears previous results** and therefore asks for confirmation when results exist: they cannot be restored, and re-running can take about as long as the meeting itself. |
| TRN-05 | P1 | Progress is shown (stage and percentage). The job runs in the background; the UI remains usable. |
| TRN-06 | P1 | **Low-confidence words are highlighted moderately** wherever transcript text is shown (timeline, segment details), using the same threshold as the export (§5.8.1). The highlight must not dominate the text: e.g. a subtle dotted underline or a slightly muted text colour, not bold or a strong background. Hovering a highlighted word shows its confidence as a percentage. The highlight can be turned off in settings. |
| TRN-07 | P1 | Model size is selectable in settings (e.g. `small`, `medium`, `large-v3-turbo`, `large-v3`). The app runs on **CPU by default**; an NVIDIA GPU is used automatically when the GPU requirements are installed. |
| TRN-07a | P1 | Before starting, the app shows an **estimated duration** of the transcription for the chosen model on this machine (based on the measured speed of previous runs, or a conservative default). |
| TRN-08 | P2 | **Speakers can be renamed** (e.g. `Speaker 1` → `Anna`); names apply throughout the timeline and export. Restart (TRN-04) clears the names too, because a new diarization may assign the speakers differently. |
| TRN-09 | P2 | Track source (mic vs. system) is used to improve speaker attribution, e.g. the local user is reliably identified from the mic track. |
| TRN-10 | P3 | **Jump to next low-confidence passage** in Review mode, for quickly checking the uncertain parts with verification playback (TL-07). |
| TRN-11 | P1 | **Closing the app during transcription** interrupts the job, so it can be resumed after the next start. |
| TRN-12 | P1 | The **transcript is read-only** in v1: its text cannot be edited in the app. Corrections are written as notes next to it (§5.4). |

**Transcription job states**

```
 idle ──Start──► running ──Interrupt──► interrupted ──Resume──► running
                   │                        │
                   ├──finishes──► done      │
                   └──Stop──────► stopped ◄─┘   (partial results kept, marked incomplete)

 Restart: running / interrupted / stopped / done ──► results cleared ──► running
```

- **Interrupt** pauses the job so it can continue later, also after the app has been closed and restarted (progress is saved per chunk, §8.2).
- **Stop** ends the job; results produced so far are kept and marked incomplete.
- **Restart** (from any state except idle) deletes existing results and starts over.
- **Resume** always continues with the settings saved when the job started (model, language, context texts), so one transcript never mixes two setups. Changes made in the meantime apply only after Restart.

#### 5.6.1 Language handling

**Modes**

| Mode | Behaviour | Pri |
|---|---|---|
| **Fixed** | The user picks one language from Whisper's list; the whole recording is transcribed in it. Most reliable when the language is known. | P1 |
| **Auto-detect** | Whisper detects the language **once**, from the first ~30 seconds, and uses it for the whole recording. The detected language is shown, and the user can switch to Fixed and restart if it is wrong. | P1 |
| **Mixed** | Language is detected **per speaker turn**, restricted to a list of expected languages chosen by the user. | P2 |

The UI explains that Auto-detect does **not** handle language changes: a meeting that starts in English and continues in Finnish would be transcribed entirely as English. In that case Whisper often *translates* the Finnish into English instead of transcribing it, which is easy to miss.

**Mixed-language approach (P2)**

Mixed-language speech is hard for Whisper, because it assumes one language per 30-second window. The approach combines the following ideas:

1. **Diarize first, then transcribe per speaker turn.** In meetings, language changes usually happen at speaker changes (people tend to speak one language each, or switch when someone else answers). Speaker turns from pyannote are therefore natural cut points. Each turn is transcribed separately with its own language.
2. **Restrict detection to the expected languages.** Whisper's language detection returns a probability for every language. Mixed mode picks the most likely language **among the user's list only**. This avoids typical misdetections such as Finnish detected as Estonian, or Swedish as Norwegian.
3. **Handle short turns.** Detection is unreliable on very short turns (under ~3 s, e.g. "yes", "okay"). These inherit the language of the same speaker's surrounding turns, or of the previous turn.
4. **Use the speaker's dominant language as a fallback.** If detection confidence for a turn is low, the language that speaker used most in the recording is used.
5. **Keep the context text language-neutral.** The prompt biases Whisper towards the language it is written in. In Mixed mode, a context text that is mostly names and terms works best. The UI hints at this.
6. **Record the language per segment.** Each transcript segment stores its language and the detection probability. The export marks language changes (e.g. `**[00:12:40] Speaker 2 (sv):**`), so readers and AI tools know which language each passage is in.
7. **Allow manual correction (P3).** In Review mode, the user can change the language of a single segment and re-transcribe just that segment. This uses verification playback (TL-07) to check it.

**Known limitation:** switching language **within a sentence** (e.g. Finnish speech with English terms) cannot be separated this way. Whisper usually transcribes it in the main language and keeps common foreign terms as they are. Listing such terms in the context text helps, and the low-confidence marking (§5.8.1) shows passages that went wrong.

### 5.7 Timeline and playback (TL)

| ID | Pri | Requirement |
|---|---|---|
| TL-01 | P1 | A **vertical timeline** with time running downward and **three columns**: Audio, Transcript, Manual notes. |
| TL-02 | P1 | The **start and end of the audio** are clearly marked. |
| TL-03 | P1 | **Audio playback** with play/pause and seeking. A playhead moves along the timeline; clicking any item seeks to its timestamp. |
| TL-04 | P1 | Transcript segments are shown with speaker label and text, colour-coded per speaker. |
| TL-05 | P1 | **Mute intervals** are shown on the audio column (e.g. greyed out, labelled "muted" / "off the record"). |
| TL-06 | P2 | Optional auto-scroll that keeps the playhead in view during playback. |
| TL-07 | P1 | **Verification playback** without splitting the audio: the single audio file stays intact, and the app manages the playback position. "Play segment" plays one transcript segment and stops at its end; clicking a note plays from its timestamp. |
| TL-07a | P1 | **Pre-roll:** playback started from a segment or note begins a short time earlier. Segments and notes have separate settings: default **2 s** for segments and **5 s** for notes, because notes are submitted after the speech they describe. |
| TL-07b | P2 | **Replay** the current segment with one shortcut, and **loop** a segment while checking a hard-to-hear passage. |
| TL-07c | P2 | **Playback speed** control (e.g. 0.75×–2×). |
| TL-08 | P2 | Zoom in/out on the time axis. |
| TL-09 | P2 | Notes can also be added by clicking a position on the timeline, and edited in place there (see NOTE-10). |

### 5.8 Export (EXP)

| ID | Pri | Requirement |
|---|---|---|
| EXP-01 | P1 | Export a recording to a **single Markdown file** with: metadata header, context texts (project and recording), and a chronological merge of transcript segments and manual notes. A note is placed **after the transcript segment that covers its timestamp**, never inside it; several notes in the same segment follow it in timestamp order. Notes at a time with no transcript (e.g. a muted interval, or before transcription) are placed at their own position in time. |
| EXP-02 | P1 | Export as **separate Markdown files**: transcript, notes, and context. |
| EXP-03 | P1 | The Markdown includes YAML front matter (project, recording, date, duration, speakers, model used, language, confidence marking) so tools can parse it. |
| EXP-04 | P2 | Export all recordings of a project at once. |
| EXP-05 | P1 | Export **per-word confidence as JSON** (`<base>.confidence.json`): every word with start/end time, speaker and confidence, plus segment-level metrics. Included in both single-file and separate-file exports. |
| EXP-06 | P1 | **Low-confidence words are marked in the Markdown** with a text style (italic by default) instead of numbers; exact values live in the JSON. Marking can be turned off. See §5.8.1. |
| EXP-07 | P2 | Each transcript segment in the Markdown can show its **average confidence**, e.g. `[00:00:04] Speaker 1 (avg 91%)`. |
| EXP-08 | P1 | **Exporting again overwrites** the previous export files of that recording without asking. Exports are generated files and are not meant to be edited in place; copy them elsewhere to edit them. |
| EXP-09 | P1 | Exports always go to the project's `exports/` folder; an **Open export folder** button opens it in the system file manager. |

#### 5.8.1 Confidence values

Whisper (via faster-whisper) gives each word a **probability from 0.0 to 1.0**, derived from the model's token probabilities. It also gives segment-level values (`avg_logprob`, `no_speech_prob`). These are **not calibrated confidences**: a 0.9 does not mean the word is correct 90% of the time. They are most useful for spotting words the model was unsure about. Values are stored as 0.0–1.0 and shown as whole percentages in Markdown.

**Division of roles between the two files:**

- The **Markdown** stays readable: words below the threshold (default 70%, configurable) are only **marked**, with no numbers.
- The **JSON** holds the exact values for every word. A reader or AI tool that wants the actual value of a marked word looks it up in the JSON, using the segment timestamp and the word.

**Marker style** (export setting):

| Style | Example | Notes |
|---|---|---|
| Italic (default) | `Thanks for *joining*.` | Renders everywhere, stays readable as plain text, and transcript text otherwise never contains emphasis, so the marker is unambiguous. |
| Code (backticks) | ``Thanks for `joining`.`` | Most visually distinct, easiest to find with a regex; looks a bit technical in rendered form. |
| Off | `Thanks for joining.` | No marking. |

- Bold is not offered: it is visually loud, and it is commonly used for speaker labels and headings in the same file.
- Colour is not offered: Markdown has no colour syntax, and inline HTML (`<span style=…>`) is not rendered by many viewers and adds noise for AI tools.
- **Consecutive** low-confidence words are marked as one span (`*for joining*`), not word by word.
- The YAML front matter states the marker, the threshold and the JSON file name (see example below), so an AI tool reading only the Markdown knows what the marking means and where the values are.

**Confidence JSON (abbreviated)**

```json
{
  "schema_version": 1,
  "recording": "2026-10-02_1400",
  "model": "faster-whisper large-v3",
  "confidence_scale": "0.0-1.0, model word probability (uncalibrated)",
  "segments": [
    {
      "start_ms": 4000, "end_ms": 9800, "speaker": "Speaker 1",
      "text": "Thanks for joining.",
      "avg_word_confidence": 0.70,
      "avg_logprob": -0.21, "no_speech_prob": 0.01,
      "words": [
        { "w": "Thanks",  "start_ms": 4000, "end_ms": 4300, "conf": 0.80 },
        { "w": "for",     "start_ms": 4300, "end_ms": 4450, "conf": 0.90 },
        { "w": "joining", "start_ms": 4450, "end_ms": 4900, "conf": 0.40 }
      ]
    }
  ]
}
```

**Example – combined export (abbreviated)**

```markdown
---
project: 2026-10-02 Customer interview
recording: 2026-10-02_1400
date: 2026-10-02T14:00:12+02:00
duration: "00:47:13"
speakers: [Speaker 1, Speaker 2]
transcription_model: faster-whisper large-v3
language: en
confidence:
  marker: italic
  threshold: 0.70
  note: "Italic words in transcript lines had confidence below the threshold. Per-word values: 2026-10-02_1400.confidence.json"
---

# Customer interview — 2026-10-02 14:00

## Project context
Interview series with ACME about their invoicing workflow. Terms: …

## Recording context
Participants: Anna (ACME), Joel. Follow-up to the September workshop.

## Timeline

**[00:00:04] Speaker 1:** Thanks for *joining*. Could you start by describing…

**[00:00:15] Speaker 2:** Sure. We currently handle invoices…

> **[00:00:31] Note:** "we match every invoice by hand"

> **[00:00:38] Note:** Pain point — manual matching.
```

---

## 6. User interface

The whole UI (both modes and all dialogs) uses a **dark theme**. The window title and About screen show the app name, **Whisper A Note**. The UI is in **English only**; all UI text is kept in one place, so translations could be added later.

**One window at a time:** Recording mode replaces the Review mode window and vice versa; the two are never open side by side.

**Confirm or restore:** during a recording session, when the user works fast, actions happen immediately and mistakes are undone afterwards (e.g. NOTE-06a). Elsewhere, actions that destroy work that cannot be restored ask for confirmation (e.g. Restart, TRN-04; deleting recordings, PRJ-07).

### 6.1 Recording mode (compact)

A small window for use during the meeting. It is a **normal window, not always on top**, so it can be made a bit larger without getting in the way.

- **Freely resizable**, and it remembers its position and size. Default ≈ 360 × 480 px.
- It can be made **narrow** (minimum width ≈ 240 px), so a thin strip at the side of the screen leaves the rest for other work. The layout stays usable at that width: controls wrap or shorten their labels.
- It can be made **as tall as the screen** to show more note history (never by default).
- Layout, top to bottom:
  1. **Header:** project/recording name.
  2. **Note history** (most recent at the bottom, auto-scrolls). Takes up all remaining height.
  3. **Note input**, directly below the note history.
  4. **Control panel**, at the very bottom: elapsed time, start/end button (Cancel during "Ending recording…", REC-04a), **Mute all** toggle, level meters + mute toggles for mic and system.
- The note input sits right below the newest notes, so what was just written stays next to where the user types. The controls are directly below the input, keeping attention and mouse in one place.
- The note input has focus by default; **Enter** submits.
- A short hint recommends **headphones**: without them, the mic also picks up the remote participants from the speakers, which duplicates their speech in the mix and weakens mic-based speaker attribution (TRN-09).
- Notes in the history can be edited and deleted (NOTE-06, NOTE-06a), but not re-timed (NOTE-07).
- Context texts are not edited here; they are set in the recording setup (REC-20) or in Review mode.
- When not recording, a **Review** button returns to Review mode.

```
┌──────────────────────────────┐
│ Customer interview           │
├──────────────────────────────┤
│ 03:12  Pain point: matching  │
│ 08:40  Asks about pricing    │
│ 12:01  Follow up on API      │
├──────────────────────────────┤
│ > Type a note…            ⏎  │
├──────────────────────────────┤
│ ● 12:34  [🔇 Mute all] [■ End]│
│ MIC ▮▮▮▮▮▯▯▯▯ [🔇]           │
│ SYS ▮▮▮▯▯▯▯▯▯ [🔇]           │
└──────────────────────────────┘
```

### 6.2 Review mode (full)

A normal resizable window.

- **Left sidebar:** project selector, list of recordings, context editors (project context and the selected recording's context).
- **Main area:** the three-column vertical timeline (§5.7) with playback controls. The notes column has a **note input** for adding notes at a chosen time (NOTE-04).
- **Toolbar:** transcription controls and progress, export, **New recording**.
- No level meters or mute toggles; the audio devices are not in use. A sound check can be opened on demand (REC-11).
- **New recording** opens the recording setup (REC-20), which leads to Recording mode.

---

## 7. Data model and file layout

All data is stored as plain files in the project folder. No database.

### 7.1 Folder structure

```
<projects folder>/
└── 2026-10-02 Customer interview/
    ├── project.json                          # project metadata + context text
    ├── 2026-10-02_1400.flac                  # mixed playback file (the "audio file")
    ├── 2026-10-02_1400.mic.flac              # microphone track
    ├── 2026-10-02_1400.system.flac           # system audio track
    ├── 2026-10-02_1400.recording.json        # recording metadata, recording context, mute intervals
    ├── 2026-10-02_1400.notes.json            # manual notes
    ├── 2026-10-02_1400.transcript.json       # transcript with words + confidence
    └── exports/
        ├── 2026-10-02_1400.md                # combined export
        └── 2026-10-02_1400.confidence.json   # per-word confidence export
```

- The **base name** (`2026-10-02_1400`) links all files of a recording. Default format `YYYY-MM-DD_HHMM`; imported files keep their original name stem. If the base name is already taken (e.g. two recordings started in the same minute, or an import with the same name stem), a suffix is added: `2026-10-02_1400_2`.
- The audio file listed as a recording is the one without a secondary suffix (`.mic`, `.system`).
- JSON files include a `schema_version` field to allow future migrations.
- During recording, tracks are written as WAV and converted to FLAC when recording ends (or on recovery, REC-12).
- **Safe writes:** JSON files are written to a temporary file in the same folder and then renamed over the original, so a crash during saving never leaves a half-written file.
- **External edits:** before writing a file, the app checks whether it changed on disk since it was loaded (e.g. edited by hand). If so, it reloads the file and applies its own change on top, instead of overwriting the other edit.
- Unreadable files are handled per NFR-09, faulty entries per NOTE-05b.

### 7.2 Key records

**Recording metadata** (`*.recording.json`)

```json
{
  "schema_version": 1,
  "source": "recorded",
  "started_at": "2026-10-02T14:00:12+02:00",
  "duration_ms": 2833000,
  "end_requested_ms": 2833000,
  "sample_rate": 16000,
  "devices": { "mic": "…", "system": "…" },
  "language": null,
  "context": "Participants: Anna (ACME), Joel. Follow-up to the September workshop.",
  "mutes": [
    { "source": "all", "reason": "user", "start_ms": 1203000, "end_ms": 1298000 },
    { "source": "mic", "reason": "device_lost", "start_ms": 1500000, "end_ms": 1504000 }
  ]
}
```

- `duration_ms` is `null` until the recording ends or is recovered (REC-12).
- `end_requested_ms`: audio time at which End was pressed (REC-04a); used to cut the recording, also on recovery. `null` while recording.
- `language`: per-recording language override (CTX-03); `null` = use the project setting.
- `context`: the recording context (CTX-06); empty if not used.
- `mutes.reason`: `user` (mute toggle), `device_lost` (REC-13) or `system_sleep` (REC-19, zero-length).

**Manual note** (in `*.notes.json`)

```json
{
  "id": "uuid",
  "text": "Pain point — manual matching.",
  "time_ms": 31000,
  "time_source": "auto",
  "created_at": "2026-10-02T14:00:43+02:00",
  "edited_at": null
}
```

- `time_ms` is audio time, within 0 to the duration. Entries outside this range (e.g. after manual editing) are faulty and handled per NOTE-05b.
- `time_source`: `auto` (set by the app at submission in Recording mode, including the closing note) or `manual` (set or later changed by the user, e.g. edited, dragged or batch-shifted).

**Transcript** (`*.transcript.json`)

```json
{
  "schema_version": 1,
  "status": "done",
  "model": "faster-whisper large-v3",
  "language_mode": "auto",
  "language": "en",
  "context_used": "…",
  "speakers": { "SPEAKER_00": "Speaker 1", "SPEAKER_01": "Speaker 2" },
  "segments": [
    {
      "start_ms": 4000, "end_ms": 9800, "speaker": "SPEAKER_00",
      "language": "en", "language_prob": 0.98,
      "text": "Thanks for joining.",
      "words": [{ "w": "Thanks", "start_ms": 4000, "end_ms": 4300, "conf": 0.80 }]
    }
  ]
}
```

`status` is one of `running`, `interrupted`, `stopped` (incomplete), `done`. If the app finds `running` while no job is running (e.g. after a crash), it treats the transcript as `interrupted`, so it can be resumed or restarted.

`model`, `language_mode` and `context_used` (the combined project and recording context) are the settings the job started with; Resume uses these (§5.6).

---

## 8. Technical architecture

### 8.1 Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11 or 3.12 (§8.5) |
| UI | PySide6 (Qt 6); timeline built with `QGraphicsView` |
| Audio capture | `sounddevice` (PortAudio) for mic; platform-specific system audio (§8.3) |
| Audio playback | `QtMultimedia` (`QMediaPlayer`) |
| Audio files | `soundfile` (libsndfile) for WAV/FLAC; PyAV (bundled FFmpeg) for importing other formats |
| Transcription | `faster-whisper` (CTranslate2) |
| Diarization | `pyannote.audio` |
| macOS system audio | Swift helper using Core Audio process taps |
| Distribution | Source + pinned `requirements.txt`, installed with `pip` into a virtual environment (§8.5) |
| Dev tooling | `uv` for dependency management and lockfile; exports `requirements.txt` (§8.5) |

### 8.2 Components

```
┌─────────────────────────── UI (Qt main thread) ───────────────────────────┐
│ RecordingSetup  RecordingWindow  ReviewWindow (Timeline, Player)  Settings│
└──────┬──────────────────────┬─────────────────────────────┬───────────────┘
       │                      │                             │
┌──────▼──────┐   ┌───────────▼──────────┐   ┌──────────────▼─────────────┐
│ AudioEngine │   │ ProjectStore         │   │ TranscriptionWorker        │
│ capture,    │   │ files, naming,       │   │ separate process:          │
│ meters,     │   │ notes, autosave      │   │ whisper → diarize → merge  │
│ writers     │   └──────────────────────┘   │ progress via IPC queue     │
└─────────────┘                              └────────────────────────────┘
```

- **Transcription runs in a separate process** so the UI stays responsive, the job can be cancelled cleanly, and ML memory is released afterwards.
- **Pipeline (Fixed / Auto-detect):** (1) Whisper on the mixed file → segments and words with probability; (2) pyannote diarization → speaker turns; (3) assign each word to the speaker turn it overlaps most; regroup into segments on speaker change.
- **Pipeline (Mixed, P2):** (1) pyannote diarization → speaker turns; (2) detect the language per turn, restricted to the expected languages, with the fallbacks of §5.6.1; (3) Whisper transcribes each turn with its language. The diarization step order is the only structural difference, so both pipelines share the same components.
- **Interrupt/resume:** processing in chunks of the audio, saving progress after each chunk.

### 8.3 System audio capture per OS

| OS | Approach | Notes |
|---|---|---|
| Windows | WASAPI loopback (e.g. `PyAudioWPatch` or `soundcard`) | No extra setup needed. |
| macOS | **Core Audio process taps** (macOS **14.2+** only) via a small prebuilt Swift helper | Requires the "System Audio Recording" permission. Highest-risk platform; needs a spike early. |
| Linux | PulseAudio/PipeWire **monitor source** (e.g. `soundcard`) | Generally works without setup. |

If system capture is unavailable, the app still works with mic-only recording and shows a clear message.

**macOS details**

- Core Audio taps are a C-level API that `sounddevice`/PortAudio does not support. A small **Swift command-line helper** creates the tap and streams raw PCM to the Python process over stdout/a pipe. The helper is shipped prebuilt in the repository (DIST-06).
- macOS asks for the "System Audio Recording" and microphone permissions on first use. As the app is not an app bundle, the prompt names the app that launched it (e.g. Terminal), see §8.5.
- macOS versions older than 14.2 are **not supported** (Q10, resolved).

### 8.4 Models and offline use

- **The diarization models are bundled with the app; the default Whisper model is downloaded once during setup** (DIST-04). The user never needs a Hugging Face account or access token.
- **pyannote (bundled, fully offline):** the developer downloads the diarization models once (accepting the Hugging Face gate with their own account) and commits the weight files and pipeline configuration **into the application package** (e.g. `whisper_a_note/models/pyannote/`). The app loads the pipeline from these bundled files only, so diarization never needs a token or network access, not even during setup. This is permitted because the models are released under open licences (MIT / CC-BY-4.0). The Hugging Face gate is an access condition, not a ban on redistribution. Requirements:
  - The model version is chosen in Phase 0 (3.1 pipeline vs. community-1, which needs pyannote.audio 4), by accuracy and CPU speed.
  - Verify the licence of the **exact model versions** bundled.
  - Ship each model's **licence file** next to its weights and include the required **attribution** in the app's About/licences screen (PKG-8).
  - The pipeline configuration refers to the bundled weight files by relative path, never by Hugging Face model ID.
  - The diarization models are small (tens of MB), so they are committed as normal files (not Git LFS, whose files are missing from plain ZIP downloads by default).
  - Updating the models is a deliberate developer step: download the new version, verify licence and results, commit.
- **Whisper:** one default model (`small`, ~0.5 GB) is downloaded during setup. Larger models (`medium` ~1.5 GB, `large-v3-turbo` ~1.6 GB, `large-v3` ~3 GB) are **optional downloads** from settings. These come from public repositories and need no token. Apart from setup, this is the only network use (NFR-01).
- **Audio decoding:** faster-whisper decodes audio via PyAV, which bundles the FFmpeg libraries, so no separate FFmpeg install is needed.
- **CPU first (Q8):** the app is designed and tested for CPU-only machines.
  - `small` is the default: good accuracy for clear meeting audio at a speed that is practical on a laptop CPU.
  - `large-v3-turbo` is the recommended upgrade on CPU: much better accuracy than `small`, at a fraction of the cost of `large-v3`.
  - `large-v3` gives the best accuracy but is slow on CPU (often slower than real time); the settings say so.
  - pyannote diarization also runs on CPU; it is considerably faster than transcription.
  - Actual speeds per model are measured in Phase 0 and used for the default estimates (TRN-07a).
- **GPU acceleration (optional):** NVIDIA CUDA on Windows/Linux via `requirements-gpu.txt`. On macOS, faster-whisper runs on CPU and pyannote can use Apple Silicon (MPS).

### 8.5 Distribution and installation

The app is distributed as **source code with pinned Python dependencies**. There are **no installers or frozen executables** in v1. The user installs Python and the dependencies with `pip`; setup and launch scripts reduce this to a double-click per OS.

**Prerequisites**

| OS | Needs |
|---|---|
| All | **Python 3.11 or 3.12** (the supported range is pinned, as ML libraries often lag behind the newest Python release); `git` optional (a ZIP download also works) |
| Windows | Python from python.org with "Add to PATH" ticked |
| macOS | macOS 14.2+; Python from python.org or Homebrew (the system Python is not used) |
| Linux | `python3-venv`, PortAudio (`libportaudio2`) and Qt runtime libraries (e.g. `libxcb-cursor0`) from the distro's package manager |

**Repository contents for setup**

```
whisper_a_note/         # application package, incl. bundled pyannote models (models/pyannote/)
requirements.txt        # pinned versions, CPU-only PyTorch
requirements-gpu.txt    # optional: NVIDIA CUDA PyTorch (Windows/Linux)
setup.bat / setup.sh    # create .venv, install requirements, download the Whisper model
run.bat / run.sh        # start the app using .venv (no console window on Windows)
bin/macos/              # prebuilt, universal Swift system-audio helper
LICENSE                 # the app's open-source licence: MIT (Q24)
THIRD_PARTY_LICENSES    # licences of dependencies and bundled models (PKG-8)
```

**Manual steps** (what the setup scripts do)

```
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt        # Windows: .venv\Scripts\python
.venv/bin/python -m whisper_a_note --download-models
.venv/bin/python -m whisper_a_note
```

The scripts call the virtual environment's Python directly instead of "activating" it. This avoids the per-shell activation differences and the PowerShell execution-policy error that activation often triggers on Windows.

**Requirements**

| ID | Requirement |
|---|---|
| DIST-01 | All dependencies are **pinned to exact versions** in `requirements.txt`, so every user gets a known-good combination. |
| DIST-02 | PyTorch is installed as the **CPU-only build** by default on all OSes. This keeps the download at roughly 1 GB instead of 3+ GB; on Linux, pip otherwise pulls the CUDA build by default. GPU support is opt-in via `requirements-gpu.txt`. |
| DIST-03 | On startup the app **checks the Python version** and shows a clear message if it is outside the supported range. |
| DIST-04 | Models are **not installed via pip**. The **pyannote models are bundled** in the application package (§8.4). The setup script downloads the default **Whisper** model from its public repository to the local model folder. **No token is needed.** If the Whisper model is missing at startup (e.g. an interrupted download), the app shows a clear message and offers to download it. |
| DIST-05 | **Updating** = download the new version (`git pull` or a new ZIP) and re-run the setup script. |
| DIST-06 | The macOS Swift helper is **shipped prebuilt** in the repository, so users do not need Xcode. |
| DIST-07 | The project stays **ready to be packaged into installers later** (e.g. with PyInstaller) without restructuring. See *Packaging readiness* below. |

**Packaging readiness (DIST-07)**

Installers are out of scope for v1, but the project must not make them hard to add later. The following rules apply from the start:

| # | Rule | Why it matters when packaging |
|---|---|---|
| PKG-1 | The project has a `pyproject.toml` with a single **entry point** (`whisper_a_note.__main__:main`); `requirements.txt` is the pinned lock of it. | Packagers need one well-defined start function. |
| PKG-2 | **Bundled resources** (icons, default config, the macOS helper, the pyannote models) live inside the package and are loaded via `importlib.resources`, never via paths relative to the working directory or `__file__` tricks. | In a frozen app, files sit in a different location than in the repo. |
| PKG-3 | **User data** (settings, logs, downloaded Whisper models) is stored in OS-standard per-user locations (via `platformdirs`), never inside the app's own folder. | Installed app folders are often read-only (e.g. `Program Files`, signed `.app` bundles). |
| PKG-4 | All **paths to models and helper binaries** go through one module (e.g. `whisper_a_note/paths.py`) and are configurable. | Packaging only needs to change one place. |
| PKG-5 | The transcription worker process uses `multiprocessing` with the `spawn` start method and `freeze_support()` in the entry point. | Without these, child processes re-launch the whole app in a frozen build. |
| PKG-6 | **No installing or downloading Python packages at runtime** (no `pip` calls from the app); only model files are downloaded. | A frozen app has no pip and cannot change its own environment. |
| PKG-7 | **No dynamic imports by string** in the app's own code; known dynamic imports in dependencies (e.g. pyannote/Lightning) are listed in one place as they are discovered. | Packagers detect imports statically, and hidden imports are the most common freezing failure. |
| PKG-8 | **Third-party licences** for all dependencies and models are tracked in a `THIRD_PARTY_LICENSES` file and shown in the About screen. | Required when redistributing binaries. |
| PKG-9 | The macOS helper declares the permission usage strings it needs, and they are kept in the repo. | They go into the `Info.plist` of a future `.app` bundle. |

**Verification:** once the MVP is stable, a throwaway PyInstaller build on each OS is attempted (not shipped) to surface packaging blockers early. *(Phase 1 exit criterion, §10.)*

**Development tooling: uv**

Developers manage dependencies with [uv](https://docs.astral.sh/uv/). **End users never need uv**; they install with plain `pip` as described above.

| # | Rule |
|---|---|
| DEV-1 | Dependencies are declared in `pyproject.toml` (standard `[project]` table) and locked in `uv.lock`, which is committed. |
| DEV-2 | PyTorch's CPU and CUDA package sources are configured as uv indexes in `pyproject.toml`, so the CPU/GPU split (DIST-02) is defined in one place. |
| DEV-3 | `requirements.txt` and `requirements-gpu.txt` are **generated** with `uv export` and committed; they are never edited by hand. They must be valid on Windows, macOS and Linux. |
| DEV-4 | CI fails if the committed requirements files do not match `uv.lock`. |
| DEV-5 | Developers create their environment with `uv sync`, and uv manages the Python version (pinned in `.python-version`, within the supported range of DIST-03). |

Poetry and pip-tools were considered. Poetry handles PyTorch's separate package sources poorly and needs a plugin to export `requirements.txt`. pip-tools produces OS-specific lock files, so one file per OS would have to be maintained.

**Platform notes**

- **macOS permissions:** without an app bundle, the microphone and system-audio permission prompts name the app that launched Python (e.g. Terminal), not "Whisper A Note". This works, but users should be told what to expect. No Apple Developer membership or notarization is needed.
- **Windows:** no SmartScreen or code-signing issues, because no executable is distributed.

**First-run setup in the app:** choose the projects folder, choose mic and system audio devices (with the sound check, REC-11), grant OS permissions (macOS), and optionally download a larger Whisper model.

---

## 9. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | **No network access** during normal operation; no telemetry. Network is used only by the setup script (Whisper model download) and by the optional, user-initiated download of larger Whisper models. Libraries that may contact servers on their own (e.g. the Hugging Face Hub) are forced into offline mode (`HF_HUB_OFFLINE=1`) with telemetry disabled. No accounts or access tokens are required. |
| NFR-02 | **Robustness:** recording survives app crashes with at most ~5 s of audio lost; notes are saved on every change. |
| NFR-03 | **Responsiveness:** UI stays interactive during transcription; level meters update ≥ 20 times per second. |
| NFR-04 | **Low footprint while recording:** CPU usage while recording stays low (target < 10% of one core) so it does not disturb video calls. |
| NFR-05 | **Transparency:** all data is human-readable (JSON, Markdown) or standard audio formats; folders can be backed up, moved or deleted with normal file tools. |
| NFR-06 | **Accessibility:** core actions available via keyboard. |
| NFR-07 | **Simple installation:** with Python installed, setup is one script per OS (§8.5); the default setup works offline straight after it completes. |
| NFR-08 | **CPU-only operation:** all features work without a GPU. Transcription on CPU uses int8 quantised models. Target: a 1-hour meeting is transcribed and diarized with the default model in **at most about 1 hour** on a typical recent laptop CPU (to be validated in Phase 0). |
| NFR-09 | **Unreadable files:** if a file exists but cannot be read (e.g. invalid JSON, unsupported `schema_version`, I/O error), the app shows a **clear error** naming the file and the problem. It never treats the file as empty, never creates a new or empty file in its place, and never writes to it. Actions that would write that file are disabled until the file is fixed or removed. Other recordings and projects are unaffected. (Faulty *entries* inside a readable file are handled per NOTE-05b.) |
| NFR-10 | **No encryption by the app:** data is stored unencrypted as plain files (NFR-05). Users who need protection at rest are advised to use the operating system's disk encryption (BitLocker, FileVault, LUKS). |

---

## 10. Release phasing

| Phase | Scope |
|---|---|
| **0 – Spikes** | System audio capture on all three OSes (macOS Core Audio taps helper first), with a quick check of clock drift between the tracks (minor, REC-07); faster-whisper + pyannote pipeline with word confidence on a sample file, loading pyannote from the bundled files without a token or network, choosing the pyannote model version to bundle (e.g. the 3.1 pipeline vs. the newer community-1, by accuracy and CPU speed), and checking that the context text guides the whole recording via `hotwords` (CTX-02); a clean `pip` install on each OS from `requirements.txt`. |
| **1 – MVP** | All P1 requirements: projects, context, recording setup with sound check, dual-track recording with meters, mute and crash recovery, notes with auto/manual timestamps, transcription with job controls and fixed/auto-detected language, low-confidence highlighting, three-column timeline with verification playback, Markdown export with the confidence JSON. **Exit check:** a throwaway PyInstaller build runs on each OS (packaging readiness, §8.5). |
| **2 – Usability** | All P2 requirements, mainly: chat commands, audio import, mixed-language mode, dragging and batch-shifting notes on the timeline, deleting recordings and projects, speaker renaming, replay/loop and playback speed, zoom, project-wide export. |
| **3 – Extras** | P3: jump to the next low-confidence passage (TRN-10), per-segment language correction (§5.6.1), other refinements. |

---

## 11. Questions and decisions

There are currently **no open questions**. New ones are added here as they come up during the spikes and development.

| # | Question | Decision |
|---|---|---|
| Q1 | Is the context text per project or per recording? | One per **project** (CTX-01), plus an optional **recording context** per recording (CTX-06); both are used for transcription. |
| Q2 | Are notes per recording? | Yes. Notes belong to exactly one recording. Moving notes between recordings is not supported in the app (users can edit the files manually). |
| Q3 | What does "sectioned/cut audio" mean? | Dropped. The audio is never split; the app manages the playback position for verification instead (TL-07). |
| Q4 | Can an ended recording be continued? | No. There is no pause either; "Mute all" covers off-the-record moments (REC-04, REC-06). |
| Q5 | Should low-confidence words be visible in the UI? | Yes, with a **moderate highlight** wherever transcript text is shown (TRN-06). |
| Q6 | Which languages must be supported? | Any language Whisper supports, fixed or auto-detected (P1); mixed-language mode with expected languages (P2). See §5.6.1. |
| Q7 | Re-transcribe with another model and compare results? | No comparisons. Restart replaces the results. |
| Q8 | Minimum hardware? | Must work **CPU-only**. GPU is an optional speed-up (§8.4, NFR-08). |
| Q9 | Threshold for low-confidence words? | **70%** for now, configurable; revisit after testing on real recordings. |
| Q10 | Support macOS < 14.2? | No. macOS 14.2+ is required (§8.3). |
| Q11 | Is NVIDIA GPU support needed in v1? | Opt-in via `requirements-gpu.txt`; CPU-only by default. |
| Q12 | Will non-technical users need installers? | Not in v1; the project stays ready for packaging (DIST-07). |
| Q13 | Should faulty entries in source files (out-of-range timestamps, malformed entries) be preserved when the app rewrites the file? | No. They are ignored and indicated, but not protected; the next save drops them (NOTE-05b). |
| Q14 | What if a file exists but cannot be read at all? | Show an error; never replace it with an empty or new file, and never write to it (NFR-09). |
| Q15 | Should manual notes be used to assist Whisper (e.g. as prompt vocabulary)? | No. The context text serves that purpose (CTX-02); users add names and terms to it manually. Notes stay an independent source (§5.4). |
| Q16 | Should notes be reordered by drag & drop in the note list? | No (former NOTE-09, removed). It gave unexpected timestamps and odd edge cases with few notes, and served no real purpose. Timestamps are changed by editing them (NOTE-07) or by dragging on the timeline (NOTE-10). |
| Q17 | Should level meters be always visible? | No. Only Recording mode shows them (REC-02); elsewhere an on-demand sound check is available, e.g. in the recording setup (REC-11, REC-20). This also keeps the microphone closed outside Recording mode. |
| Q18 | Are the pyannote models downloaded or bundled? | **Bundled** in the application package, so diarization is fully offline and needs no download (§8.4, DIST-04). The Whisper model is still downloaded during setup, as it is too large (~0.5 GB and up) to commit. This is fine: the app does not need to work straight after unzipping; the requirement is that users never need keys, accounts or tokens for external services (NFR-01). |
| Q19 | Should notes record when typing started, in addition to when they were submitted? | No (former NOTE-11, removed). It was unreliable when the input was cleared or rewritten, meaningless for pre-written notes, and made manual timestamp edits ambiguous. Notes have one timestamp; corrections are made by editing, dragging on the timeline or a batch shift (NOTE-07, NOTE-10, NOTE-13), and a longer pre-roll for notes helps playback (TL-07a). In the export, a note follows the transcript segment covering its timestamp (EXP-01). |
| Q20 | Can notes be submitted in Recording mode after End? | One **closing note** only: it is placed at the end of the recording, its text stays in the input, and each further submit replaces it (NOTE-02b). Other notes are added within the duration in Review mode. Remarks about the whole meeting can also go into the per-recording context (CTX-06), which helps transcription too. |
| Q21 | Can recording and transcription run at the same time, or several transcriptions? | No. Start is disabled while a transcription is running (REC-16), and only one transcription can be **running** at a time (TRN-01). Interrupting frees the slot, both for recording and for other transcriptions. This keeps CPU free for recording (NFR-04). |
| Q22 | Can an incomplete transcript (stopped or interrupted) be exported? | Yes, without any special marking: the user knows from the job status that the results are incomplete. |
| Q23 | App name and look? | The app is called **Whisper A Note**; the UI uses a dark theme (§6). The Python package is `whisper_a_note`. |
| Q24 | Which open-source licence does the app use? | **MIT**: anyone may use, copy, modify and redistribute the code, also commercially, as long as the copyright and licence notice are kept; there is no warranty. Compatible with PySide6 (LGPL) and the bundled pyannote models (MIT / CC-BY-4.0). |
| Q25 | Should the Recording mode window be hidden from screen sharing? | No. |
| Q26 | Should Recording mode be always on top? | No. It is a normal window that can be resized freely: narrow (a thin strip at the side) or as tall as the screen, never by default (§6.1). |
| Q27 | How are notes written during Mute all handled? | **Like any other note.** Recording, timestamps and notes continue normally while muted. Mute all only silences the audio; notes are never labelled off the record or excluded from exports, because a user who forgot Mute all on may still be writing notes, which are then the only record of what happened. |
| Q28 | Can the transcript be edited? | No (TRN-12). Corrections are written as notes. |
| Q29 | What can be done to notes in Recording mode? | Edit text and delete, with restore of the last deleted note instead of delete confirmations (NOTE-06a). Timestamps are changed in Review mode only (NOTE-07). |
| Q30 | Where are context texts edited? | In Review mode, and in the recording setup before entering Recording mode, together with the project choice and the sound check (REC-20). Not in Recording mode. |
| Q31 | Can recordings and projects be deleted in the app? | Yes, with confirmation, by moving them to the system trash (PRJ-07). |
| Q32 | UI language? | English only (§6). |
| Q33 | Should the app encrypt data? | No (NFR-10). |
| Q34 | Should Restart ask for confirmation? | Yes (TRN-04). "Restore rather than confirm" only applies during a fast-moving recording session; elsewhere, irreversible actions are confirmed (§6). |
| Q35 | Can Recording mode and Review mode be open at the same time? | No, one window at a time (§6). |
| Q36 | Where do exports go? | Always to the project's `exports/` folder, with an "Open export folder" button (EXP-09). |
| Q37 | What can be undone? | Only deleting a note (NOTE-06a); text edits are corrected by editing again. |
| Q38 | What happens when the user leaves Recording mode without recording? | No recording is created. Project changes from the setup are kept; the recording context and draft note are kept until the app closes and pre-filled in the next setup (REC-20). |
| Q39 | How is an accidental End prevented? | With a 5-second **"Ending recording…"** grace period with Cancel in the place of the End button; recording continues meanwhile and is cut at the End point if ending completes (REC-04a). `/end` has no short form. |
| Q40 | Should there be reminders while Mute all is on, or warnings for a silent source? | No. A clear indicator shows Mute all (REC-06), and a silent source is visible from its level meter (REC-02). Former REC-10 removed. |
| Q41 | Which proposed additions are kept? | Kept: expected number of speakers (CTX-05), speaker renaming (TRN-08), mic-based speaker attribution (TRN-09), jump to low-confidence passages (TRN-10). Dropped: faulty-entry list (former NOTE-05c), quote/observation notes (former NOTE-12, and the `kind` field), single-word transcript correction (former TRN-13), global hotkey, per-source mute commands and text after `/start`. |
| Q42 | Sample rate of the stored audio? | **16 kHz** for now: what Whisper uses, small files, clear enough for speech playback. Revisit only if playback proves too muffled. |
| Q43 | Which pyannote model version is bundled? | Decided in **Phase 0**, by accuracy and CPU speed (§8.4). |
