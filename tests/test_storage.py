import json
import os
from datetime import datetime

import pytest

from whisper_a_note.storage import NotesFile, Project, RecordingFile, UnreadableFileError
from whisper_a_note.storage.recording import Mute


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def bump_mtime(path):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def note_entry(**kw):
    entry = {"id": "a", "text": "x", "time_ms": 1000, "time_source": "auto",
             "created_at": "2026-10-02T14:00:00+02:00", "edited_at": None}
    entry.update(kw)
    return entry


# --- unreadable files (NFR-09) ---------------------------------------------------------

@pytest.mark.parametrize("content, problem", [
    ("{not json", "not valid JSON"),
    ("[1, 2]", "JSON object"),
    ('{"notes": []}', "schema_version"),
    ('{"schema_version": 99, "notes": []}', "newer"),
])
def test_unreadable_file_raises_and_is_not_overwritten(tmp_path, content, problem):
    path = tmp_path / "r.notes.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(UnreadableFileError, match=problem):
        NotesFile(path, duration_ms=10_000)
    assert path.read_text(encoding="utf-8") == content


def test_missing_file_is_empty_and_not_created_until_a_change(tmp_path):
    path = tmp_path / "r.notes.json"
    notes = NotesFile(path, duration_ms=10_000)
    assert notes.notes == [] and not path.exists()
    notes.add("hello", 500)
    assert path.exists()


# --- notes -----------------------------------------------------------------------------

def test_notes_saved_on_every_change_and_sorted(tmp_path):
    path = tmp_path / "r.notes.json"
    notes = NotesFile(path, duration_ms=60_000)
    b = notes.add("second", 20_000)
    a = notes.add("first", 10_000)
    assert [n.text for n in notes.notes] == ["first", "second"]
    notes.edit_text(a.id, "first!")
    notes.set_time(b.id, 5_000)
    reloaded = NotesFile(path, duration_ms=60_000)
    assert [(n.text, n.time_ms, n.time_source) for n in reloaded.notes] == [
        ("second", 5_000, "manual"), ("first!", 10_000, "auto")]
    assert reloaded.get(a.id).edited_at is not None


def test_same_timestamp_keeps_creation_order(tmp_path):
    notes = NotesFile(tmp_path / "r.notes.json", duration_ms=60_000)
    for t in ("one", "two", "three"):
        notes.add(t, 0)
    assert [n.text for n in notes.notes] == ["one", "two", "three"]


def test_timestamps_limited_to_audio(tmp_path):
    notes = NotesFile(tmp_path / "r.notes.json", duration_ms=60_000)
    with pytest.raises(ValueError):
        notes.add("late", 60_001)
    n = notes.add("ok", 60_000)
    with pytest.raises(ValueError):
        notes.set_time(n.id, -1)


def test_no_upper_limit_while_recording(tmp_path):
    notes = NotesFile(tmp_path / "r.notes.json", duration_ms=None)
    notes.add("during recording", 10_000_000)


def test_delete_and_restore_last_deleted(tmp_path):
    path = tmp_path / "r.notes.json"
    notes = NotesFile(path, duration_ms=60_000)
    n = notes.add("oops", 3_000)
    notes.delete(n.id)
    assert notes.notes == []
    restored = notes.restore_last_deleted()
    assert restored == n and NotesFile(path, 60_000).notes == [n]
    assert notes.restore_last_deleted() is None


def test_faulty_entries_ignored_and_dropped_on_next_save(tmp_path):
    path = tmp_path / "r.notes.json"
    write(path, {"schema_version": 1, "notes": [
        note_entry(id="ok"),
        note_entry(id="late", time_ms=99_999),
        note_entry(id="neg", time_ms=-5),
        note_entry(id="bad-source", time_source="guess"),
        {"id": "missing-fields"},
        note_entry(id="ok"),  # duplicate id
        "not an object",
    ]})
    notes = NotesFile(path, duration_ms=60_000)
    assert [n.id for n in notes.notes] == ["ok"] and notes.faulty_count == 6
    notes.add("new", 2_000)
    saved = json.loads(path.read_text(encoding="utf-8"))["notes"]
    assert sorted(e["id"] for e in saved if e["id"] == "ok") == ["ok"] and len(saved) == 2
    assert notes.faulty_count == 0


def test_external_edit_is_reloaded_not_overwritten(tmp_path):
    path = tmp_path / "r.notes.json"
    notes = NotesFile(path, duration_ms=60_000)
    notes.add("from app", 1_000)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["notes"].append(note_entry(id="by-hand", text="edited by hand", time_ms=2_000))
    write(path, data)
    bump_mtime(path)
    notes.add("from app again", 3_000)
    texts = [n.text for n in NotesFile(path, 60_000).notes]
    assert texts == ["from app", "edited by hand", "from app again"]


def test_batch_shift_clamps_and_keeps_order(tmp_path):
    notes = NotesFile(tmp_path / "r.notes.json", duration_ms=60_000)
    for t, ms in (("a", 1_000), ("b", 3_000), ("c", 59_000)):
        notes.add(t, ms)
    notes.shift_all(-2_000)
    assert [(n.text, n.time_ms) for n in notes.notes] == [("a", 0), ("b", 1_000), ("c", 57_000)]
    notes.shift_all(+10_000)
    assert [(n.text, n.time_ms) for n in notes.notes] == [("a", 10_000), ("b", 11_000), ("c", 60_000)]


# --- recording metadata ----------------------------------------------------------------

def test_recording_meta_roundtrip_and_faulty_mutes(tmp_path):
    path = tmp_path / "r.recording.json"
    rec = RecordingFile(path)
    rec.update(started_at="2026-10-02T14:00:12+02:00", context="Participants: Anna",
               mutes=(Mute("all", "user", 1_000, 2_000),))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mutes"].append({"source": "everything", "start_ms": 5})
    write(path, data)
    again = RecordingFile(path)
    assert again.meta.context == "Participants: Anna"
    assert again.meta.mutes == (Mute("all", "user", 1_000, 2_000),) and again.faulty_count == 1


# --- projects --------------------------------------------------------------------------

def test_project_create_and_recordings(tmp_path):
    project = Project.create(tmp_path, "2026-10-02 Customer interview")
    assert Project(project.folder).settings.name == "2026-10-02 Customer interview"
    for name in ("2026-10-02_1400.flac", "2026-10-02_1400.mic.flac", "2026-10-02_1400.system.flac",
                 "interview.mp3", "2026-10-02_1500.recording.json", "notes.txt"):
        (project.folder / name).write_bytes(b"")
    assert project.recordings() == ["2026-10-02_1400", "2026-10-02_1500", "interview"]


def test_new_base_name_adds_suffix_when_taken(tmp_path):
    project = Project.create(tmp_path, "p")
    t = datetime(2026, 10, 2, 14, 0)
    assert project.new_base_name(t) == "2026-10-02_1400"
    (project.folder / "2026-10-02_1400.recording.json").write_bytes(b"")
    assert project.new_base_name(t) == "2026-10-02_1400_2"
    (project.folder / "2026-10-02_1400_2.mic.wav").write_bytes(b"")
    assert project.new_base_name(t) == "2026-10-02_1400_3"
