import time

import numpy as np
import soundfile as sf

from whisper_a_note.audio.finalize import finalize_recording, is_unfinished
from whisper_a_note.audio.recorder import Recorder
from whisper_a_note.audio.sources import BLOCK_FRAMES, DEVICE_RATE, DeviceLost
from whisper_a_note.storage import Mute, NotesFile, Project, RecordingFile


class FakeSource:
    """Delivers a tone in real time; can simulate a lost device."""

    def __init__(self, name, amplitude=0.5, lose_after_blocks=None, fail_opens=0):
        self.name, self.amplitude = name, amplitude
        self.lose_after, self.fail_opens = lose_after_blocks, fail_opens
        self.blocks = 0
        self.opened = 0

    def open(self):
        self.opened += 1
        if self.opened > 1 and self.fail_opens > 0:
            self.fail_opens -= 1
            raise DeviceLost("still gone")

    def read(self):
        time.sleep(BLOCK_FRAMES / DEVICE_RATE)
        self.blocks += 1
        if self.lose_after is not None and self.blocks == self.lose_after:
            raise DeviceLost("unplugged")
        t = np.arange(BLOCK_FRAMES) / DEVICE_RATE
        return (self.amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    def close(self):
        pass


def make(tmp_path, **kw):
    project = Project.create(tmp_path, "p")
    base = project.new_base_name()
    mic, system = kw.pop("mic", FakeSource("Mic")), kw.pop("system", FakeSource("Loopback", 0.3))
    return project, base, Recorder(project, base, mic, system, **kw)


def wait_until(rec, ms):
    while rec.audio_time_ms() < ms:
        time.sleep(0.02)


def test_record_mute_and_finish(tmp_path):
    project, base, rec = make(tmp_path, context="Participants: Anna")
    rec.start()
    wait_until(rec, 500)
    rec.set_mute("all", True)
    wait_until(rec, 1000)
    rec.set_mute("all", False)
    wait_until(rec, 1500)
    duration = rec.finish()

    assert 1400 <= duration <= 1800
    for kind in ("flac", "mic.flac", "system.flac"):
        assert project.path(base, kind).exists()
    assert not project.path(base, "mic.wav").exists() and not is_unfinished(project, base)
    meta = RecordingFile(project.path(base, "recording.json")).meta
    assert meta.duration_ms == duration and meta.context == "Participants: Anna"
    assert meta.devices == {"mic": "Mic", "system": "Loopback"}
    (mute,) = meta.mutes
    assert (mute.source, mute.reason) == ("all", "user") and 400 <= mute.start_ms < mute.end_ms <= 1200

    mic, _ = sf.read(project.path(base, "mic.flac"))
    a, b = mute.start_ms * 16 + 1600, mute.end_ms * 16 - 1600  # well inside the muted interval
    assert np.max(np.abs(mic[a:b])) == 0 and np.max(np.abs(mic[:a - 3200])) > 0.4
    mix, _ = sf.read(project.path(base, "flac"))
    assert len(mix) == len(mic) and np.max(np.abs(mix)) <= 1.0


def test_mutes_set_before_start_apply_from_the_start(tmp_path):
    project, base, rec = make(tmp_path)
    rec.start(mutes={"mic": True})
    wait_until(rec, 500)
    rec.finish()
    meta = RecordingFile(project.path(base, "recording.json")).meta
    assert meta.mutes[0].source == "mic" and meta.mutes[0].start_ms == 0
    mic, _ = sf.read(project.path(base, "mic.flac"))
    assert np.max(np.abs(mic)) == 0


def test_end_grace_period_cuts_at_end_point(tmp_path):
    project, base, rec = make(tmp_path)
    rec.start()
    wait_until(rec, 800)
    end = rec.request_end()
    wait_until(rec, end + 600)  # still recording during the grace period
    assert rec.finish() == end


def test_cancelled_end_keeps_recording(tmp_path):
    project, base, rec = make(tmp_path)
    rec.start()
    wait_until(rec, 500)
    rec.request_end()
    rec.cancel_end()
    wait_until(rec, 1200)
    assert rec.finish() >= 1200


def test_device_lost_records_silence_and_interval(tmp_path):
    system = FakeSource("Loopback", lose_after_blocks=5, fail_opens=1)
    project, base, rec = make(tmp_path, system=system)
    rec.start()
    wait_until(rec, 4000)
    duration = rec.finish()
    meta = RecordingFile(project.path(base, "recording.json")).meta
    lost = [m for m in meta.mutes if m.reason == "device_lost"]
    assert len(lost) == 1 and lost[0].source == "system" and lost[0].end_ms > lost[0].start_ms
    assert any("lost" in e for e in rec.events) and any("back" in e for e in rec.events)
    sys_track, _ = sf.read(project.path(base, "system.flac"))
    mic_track, _ = sf.read(project.path(base, "mic.flac"))
    assert len(sys_track) == len(mic_track) and len(sys_track) // 16 == duration


def test_recovery_after_crash(tmp_path):
    project = Project.create(tmp_path, "p")
    base = "2026-10-02_1400"
    meta = RecordingFile(project.path(base, "recording.json"))
    meta.update(started_at="2026-10-02T14:00:00+02:00", mutes=(Mute("all", "user", 500, None),))
    sf.write(project.path(base, "mic.wav"), np.full(16000, 0.1, np.float32), 16000, subtype="PCM_16")
    sf.write(project.path(base, "system.wav"), np.full(12000, 0.1, np.float32), 16000, subtype="PCM_16")
    notes = NotesFile(project.path(base, "notes.json"), duration_ms=None)
    notes.add("written just before the crash", 5000)

    assert project.recordings() == [base] and is_unfinished(project, base)
    assert finalize_recording(project, base) == 1000
    meta = RecordingFile(project.path(base, "recording.json")).meta
    assert meta.duration_ms == 1000 and meta.mutes == (Mute("all", "user", 500, 1000),)
    assert [n.time_ms for n in NotesFile(project.path(base, "notes.json"), 1000).notes] == [1000]
    assert len(sf.read(project.path(base, "system.flac"))[0]) == 16000
