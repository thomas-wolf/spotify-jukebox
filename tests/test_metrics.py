import json
import urllib.request
from datetime import date

import pytest

from fakes import FakePlayer
from jukebox import __version__
from jukebox.app import App
from jukebox.config import Card, load_config
from jukebox.events import EventBus
from jukebox.metrics import SOLOIST_BUILD_LIFETIME_DAYS, build_metrics, read_sync_status, soloist_lifetime
from jukebox.players import PlayerRouter
from jukebox.sync import SyncResult, sync_status_path, write_sync_status
from jukebox.web import Web


@pytest.fixture
def app(tmp_path):
    cfg = load_config(None)
    cfg.raw["box"]["data_dir"] = str(tmp_path / "data")
    cards = {"A": Card("A", "Bedtime", play="spotify:playlist:a"), "B": Card("B", "Story", play="spotify:album:b")}
    return App(cfg, cards, PlayerRouter({"spotify": FakePlayer("spotify")}), EventBus())


def test_soloist_lifetime_counts_down_from_the_build_date():
    life = soloist_lifetime(date(2026, 11, 1), today=date(2026, 11, 18))
    assert life == {"soloist_build_age_days": 17, "soloist_expires_in_days": SOLOIST_BUILD_LIFETIME_DAYS - 17}


def test_soloist_lifetime_is_null_without_a_build_date():
    assert soloist_lifetime(None) == {"soloist_build_age_days": None, "soloist_expires_in_days": None}


def test_metrics_without_sync_or_soloist_data(app):
    m = build_metrics(app, today=date(2026, 11, 18))
    assert m["version"] == __version__
    assert m["box"] == "jukebox"
    assert m["backend"] == "go-librespot"
    assert m["cards"] == 2
    assert m["last_sync"] is None and m["last_sync_ok"] is None
    assert m["battery_soc"] is None
    assert m["soloist_expires_in_days"] is None


def test_sync_status_is_written_and_read_back(app, tmp_path):
    data_dir = app.cfg.data_dir
    write_sync_status(sync_status_path(data_dir), SyncResult(cards_changed=True), now=1_800_000_000)
    status = read_sync_status(data_dir)
    assert status["last_run"] == "2027-01-15T08:00:00+00:00"
    assert status["ok"] is True and status["cards_changed"] is True

    m = build_metrics(app)
    assert m["last_sync"] == status["last_run"]
    assert m["last_sync_ok"] is True


def test_failed_sync_is_reported_as_not_ok(app):
    res = SyncResult(errors=["cards: rclone timed out"])
    write_sync_status(sync_status_path(app.cfg.data_dir), res)
    assert build_metrics(app)["last_sync_ok"] is False


def test_unreadable_sync_status_is_ignored(app):
    path = sync_status_path(app.cfg.data_dir)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    assert read_sync_status(app.cfg.data_dir) is None
    assert build_metrics(app)["last_sync"] is None


def test_api_metrics_route(app, tmp_path):
    w = Web(app, tmp_path / "cards.toml", tmp_path, "127.0.0.1", 0)
    w.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{w.port}/api/metrics") as r:
            body = json.loads(r.read())
    finally:
        w.stop()
    assert body["cards"] == 2
    assert body["version"] == __version__
