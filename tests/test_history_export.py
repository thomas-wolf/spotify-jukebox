from datetime import date

from fakes import FakePlayer
from jukebox.app import App
from jukebox.config import Card, load_config
from jukebox.events import EventBus
from jukebox.history import PlayHistory
from jukebox.metrics import build_metrics
from jukebox.mqtt_export import MqttExporter
from jukebox.players import PlayerRouter


def test_metrics_carry_last_track_and_history(tmp_path):
    cfg = load_config(None)
    cfg.raw["box"]["data_dir"] = str(tmp_path / "data")
    app = App(cfg, {"A": Card("A", "Bedtime", play="spotify:playlist:a")},
              PlayerRouter({"spotify": FakePlayer("spotify")}), EventBus())
    app.history = PlayHistory(tmp_path / "history.json")
    app.history.record("Erste")
    app.history.record("Zweite", "Band")

    m = build_metrics(app, today=date(2026, 11, 18))
    assert m["last_track"] == "Zweite"
    assert [e["title"] for e in m["history"]] == ["Erste", "Zweite"]


def test_last_track_discovery_reads_history_as_attributes():
    exporter = MqttExporter(None, lambda: {}, "pferd", backend="go-librespot")
    configs = dict(exporter.discovery_messages({"last_track": None}))
    entity = configs["homeassistant/sensor/jukebox_pferd/last_track/config"]
    assert entity["json_attributes_topic"] == "jukebox/pferd/state"
    assert "history" in entity["json_attributes_template"]
