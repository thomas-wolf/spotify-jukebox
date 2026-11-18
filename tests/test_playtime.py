import json
from datetime import date

from jukebox.playtime import KEEP_DAYS, Playtime


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Day:
    def __init__(self, value: date) -> None:
        self.value = value

    def __call__(self) -> date:
        return self.value


def make(tmp_path, day=date(2026, 11, 18)):
    clock, today = Clock(), Day(day)
    return Playtime(tmp_path / "playtime.json", clock=clock, today=today), clock, today


def test_counts_minutes_between_start_and_stop(tmp_path):
    pt, clock, _ = make(tmp_path)
    pt.start()
    clock.now += 90
    pt.stop()
    assert pt.minutes() == 1.5


def test_pause_and_resume_add_up(tmp_path):
    pt, clock, _ = make(tmp_path)
    pt.start()
    clock.now += 60
    pt.stop()
    clock.now += 600  # paused, not counted
    pt.start()
    clock.now += 120
    pt.stop()
    assert pt.minutes() == 3.0


def test_start_while_running_does_not_reset(tmp_path):
    pt, clock, _ = make(tmp_path)
    pt.start()
    clock.now += 30
    pt.start()  # e.g. a second "playing" event for the next track
    clock.now += 30
    pt.stop()
    assert pt.minutes() == 1.0


def test_running_session_counts_in_today(tmp_path):
    pt, clock, _ = make(tmp_path)
    pt.start()
    clock.now += 30
    assert pt.minutes() == 0.5


def test_stop_without_start_is_harmless(tmp_path):
    pt, _, _ = make(tmp_path)
    pt.stop()
    assert pt.minutes() == 0.0


def test_persisted_and_reloaded(tmp_path):
    pt, clock, _ = make(tmp_path)
    pt.start()
    clock.now += 120
    pt.stop()
    stored = json.loads((tmp_path / "playtime.json").read_text(encoding="utf-8"))
    assert stored == {"2026-11-18": 120.0}

    again, _, _ = make(tmp_path)
    assert again.minutes() == 2.0


def test_unreadable_file_starts_empty(tmp_path):
    (tmp_path / "playtime.json").write_text("not json", encoding="utf-8")
    pt, _, _ = make(tmp_path)
    assert pt.minutes() == 0.0


def test_old_days_are_dropped(tmp_path):
    pt, clock, today = make(tmp_path, day=date(2026, 1, 1))
    pt.start()
    clock.now += 60
    pt.stop()
    for offset in range(1, KEEP_DAYS + 1):
        today.value = date(2026, 1, 1 + offset)
        pt.start()
        clock.now += 60
        pt.stop()
    stored = json.loads((tmp_path / "playtime.json").read_text(encoding="utf-8"))
    assert len(stored) == KEEP_DAYS
    assert "2026-01-01" not in stored


class FakeBus:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def subscribe(self, name, handler):
        self.handlers.setdefault(name, []).append(handler)

    def fire(self, name):
        for handler in self.handlers.get(name, []):
            handler(None)


def test_bus_events_drive_the_counter(tmp_path):
    pt, clock, _ = make(tmp_path)
    bus = FakeBus()
    pt.bind(bus)
    bus.fire("playing")
    clock.now += 60
    bus.fire("paused")
    clock.now += 60
    bus.fire("playing")
    clock.now += 60
    bus.fire("stopped")
    assert pt.minutes() == 2.0
