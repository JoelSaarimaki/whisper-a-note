import json

from whisper_a_note.export import RecordingExport, marked_text
from whisper_a_note.storage import NotesFile, Project, RecordingFile
from whisper_a_note.storage.jsonfile import write_json


def w(text, a, b, conf=0.9):
    return {"w": text, "start_ms": a, "end_ms": b, "conf": conf}


def test_marking_spans_and_escaping():
    words = [w("Thanks", 0, 1, 0.8), w("for", 1, 2, 0.4), w("joining.", 2, 3, 0.5), w("a*b", 3, 4)]
    assert marked_text(words, "italic", 0.7) == r"Thanks *for joining.* a\*b"
    assert marked_text(words, "code", 0.7) == r"Thanks `for joining.` a\*b"
    assert marked_text(words, "off", 0.7) == r"Thanks for joining. a\*b"


def setup(tmp_path):
    project = Project.create(tmp_path, "2026-10-02 Customer interview")
    project.update(context="Interview series with ACME.")
    base = "2026-10-02_1400"
    RecordingFile(project.path(base, "recording.json")).update(
        started_at="2026-10-02T14:00:12+02:00", duration_ms=60_000, context="Participants: Anna, Joel.")
    write_json(project.path(base, "transcript.json"), {
        "status": "done", "model": "large-v3-turbo", "language": "en",
        "speakers": {"SPEAKER_00": "Speaker 1", "SPEAKER_01": "Speaker 2"},
        "segments": [
            {"start_ms": 4000, "end_ms": 9800, "speaker": "SPEAKER_00", "language": "en", "text": "Thanks for joining.",
             "words": [w("Thanks", 4000, 4300, 0.8), w("for", 4300, 4450, 0.9), w("joining.", 4450, 4900, 0.4)]},
            {"start_ms": 15000, "end_ms": 40000, "speaker": "SPEAKER_01", "language": "en", "text": "Sure.",
             "words": [w("Sure.", 15000, 15500)]},
        ]})
    notes = NotesFile(project.path(base, "notes.json"), 60_000)
    notes.add("Before anything", 1000)
    notes.add("Pain point", 38_000)        # inside segment 2 -> after it
    notes.add("Inside the first", 5000)    # inside segment 1 -> after it
    notes.add("Closing thought", 60_000)
    return project, base


def test_combined_export(tmp_path):
    project, base = setup(tmp_path)
    (md, conf) = RecordingExport(project, base).write()
    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\nproject: \"2026-10-02 Customer interview\"\nrecording: \"2026-10-02_1400\"")
    assert 'duration: "00:01:00"' in text and "language: en" in text and "marker: italic" in text
    assert "# Customer interview — 2026-10-02 14:00" in text
    assert "## Project context\nInterview series with ACME." in text
    assert "## Recording context\nParticipants: Anna, Joel." in text
    timeline = text.split("## Timeline\n\n")[1].split("\n\n")
    assert timeline == [
        "> **[00:00:01] Note:** Before anything",
        "**[00:00:04] Speaker 1:** Thanks for *joining.*",
        "> **[00:00:05] Note:** Inside the first",
        "**[00:00:15] Speaker 2:** Sure.",
        "> **[00:00:38] Note:** Pain point",
        "> **[00:01:00] Note:** Closing thought\n",
    ]
    data = json.loads(conf.read_text(encoding="utf-8"))
    assert data["segments"][0]["speaker"] == "Speaker 1" and data["segments"][0]["avg_word_confidence"] == 0.7


def test_separate_export_and_overwrite(tmp_path):
    project, base = setup(tmp_path)
    files = RecordingExport(project, base).write(separate=True)
    assert sorted(f.name for f in files) == [f"{base}.confidence.json", f"{base}.context.md",
                                            f"{base}.notes.md", f"{base}.transcript.md"]
    again = RecordingExport(project, base, marker="off").write(separate=True)
    assert "*joining.*" not in (project.folder / "exports" / f"{base}.transcript.md").read_text(encoding="utf-8")
    assert len(again) == 4


def test_export_without_transcript(tmp_path):
    project = Project.create(tmp_path, "p")
    base = "r"
    RecordingFile(project.path(base, "recording.json")).update(duration_ms=10_000)
    NotesFile(project.path(base, "notes.json"), 10_000).add("only notes", 2000)
    (md,) = RecordingExport(project, base).write()
    text = md.read_text(encoding="utf-8")
    assert "> **[00:00:02] Note:** only notes" in text and "confidence:" not in text
