import json
from datetime import datetime, timezone
from types import SimpleNamespace

from jukebox.history import PlayHistory


def make(tmp_path, limit=50):
    stamps = iter(datetime(2026, 11, 18, 17, m, tzinfo=timezone.utc) for m in range(0, 60))
    return PlayHistory(tmp_path / "history.json", limit=limit, now=lambda: next(stamps))


def test_records_a_new_track(tmp_path):
    h = make(tmp_path)
    assert h.record("Bibi & Tina", "Folge 1") is True
    entry = h.last()[-1]
    assert entry["title"] == "Bibi & Tina" and entry["artist"] == "Folge 1"
    assert entry["time"] == "2026-11-18T17:00:00+00:00"


def test_same_track_again_is_not_a_new_entry(tmp_path):
    h = make(tmp_path)
    h.record("Song", "Band")
    assert h.record("Song", "Band") is False
    assert len(h.last()) == 1


def test_same_title_by_other_artist_is_new(tmp_path):
    h = make(tmp_path)
    h.record("Song", "A")
    assert h.record("Song", "B") is True


def test_back_to_an_earlier_track_is_new(tmp_path):
    h = make(tmp_path)
    h.record("A")
    h.record("B")
    assert h.record("A") is True
    assert [e["title"] for e in h.last()] == ["A", "B", "A"]


def test_empty_title_is_ignored(tmp_path):
    h = make(tmp_path)
    assert h.record("  ") is False
    assert h.last() == []


def test_keeps_only_the_newest_entries(tmp_path):
    h = make(tmp_path, limit=3)
    for i in range(5):
        h.record(f"T{i}")
    assert [e["title"] for e in h.last(10)] == ["T2", "T3", "T4"]


def test_persisted_and_reloaded(tmp_path):
    h = make(tmp_path)
    h.record("A", "x", uri="spotify:track:1")
    h.record("B")
    stored = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [e["title"] for e in stored] == ["A", "B"]
    assert stored[0]["uri"] == "spotify:track:1"

    again = make(tmp_path)
    assert [e["title"] for e in again.last()] == ["A", "B"]


def test_unreadable_file_starts_empty(tmp_path):
    (tmp_path / "history.json").write_text("{broken", encoding="utf-8")
    assert make(tmp_path).last() == []


class FakeBus:
    def __init__(self):
        self.handlers = {}

    def subscribe(self, name, handler):
        self.handlers.setdefault(name, []).append(handler)

    def fire(self, name, **data):
        for handler in self.handlers.get(name, []):
            handler(SimpleNamespace(name=name, data=data))


def test_track_events_feed_the_history(tmp_path):
    h = make(tmp_path)
    bus = FakeBus()
    h.bind(bus)
    bus.fire("track", title="Song", artist="Band", cover_url="x")
    bus.fire("track", title="Song", artist="Band", cover_url="x")  # poller repeats it
    bus.fire("track", title="Next", artist="", uri="file:/x.mp3")
    assert [e["title"] for e in h.last()] == ["Song", "Next"]
