from whisper_a_note.transcription.chunks import Chunk, plan_chunks
from whisper_a_note.transcription.merge import assign_speakers, build_segments, speaker_labels


def test_chunks_group_speech_and_cut_in_pauses():
    regions = [(1000, 20000), (21000, 50000), (52000, 90000), (91000, 95000)]
    chunks = plan_chunks(regions, 100_000, muted_all=[], max_chunk_ms=60_000)
    assert chunks == [Chunk(600, 50400), Chunk(51600, 95400)]
    assert all(c.end_ms - c.start_ms <= 60_000 for c in chunks)


def test_chunks_skip_fully_muted_intervals():
    chunks = plan_chunks([(0, 30000)], 30_000, muted_all=[(10_000, 20_000)])
    assert chunks == [Chunk(0, 10_000), Chunk(20_000, 30_000)]


def test_long_region_is_split():
    chunks = plan_chunks([(0, 150_000)], 150_000, muted_all=[], max_chunk_ms=60_000)
    assert len(chunks) == 3 and chunks[0].start_ms == 0 and chunks[-1].end_ms == 150_000


def w(text, a, b, conf=0.9):
    return {"w": text, "start_ms": a, "end_ms": b, "conf": conf}


def test_assign_and_build_segments():
    words = [w("Hello", 0, 400), w("there.", 400, 900), w("Hi!", 1200, 1500), w("Later", 9000, 9400)]
    turns = [{"start_ms": 0, "end_ms": 1000, "speaker": "SPEAKER_01"},
             {"start_ms": 1100, "end_ms": 1600, "speaker": "SPEAKER_00"}]
    words = assign_speakers(words, turns)
    assert [x["speaker"] for x in words] == ["SPEAKER_01", "SPEAKER_01", "SPEAKER_00", "SPEAKER_00"]
    assert speaker_labels(words) == {"SPEAKER_01": "Speaker 1", "SPEAKER_00": "Speaker 2"}
    segs = build_segments(words, "en", 0.98)
    assert [(s["speaker"], s["text"]) for s in segs] == [
        ("SPEAKER_01", "Hello there."), ("SPEAKER_00", "Hi!"), ("SPEAKER_00", "Later")]
