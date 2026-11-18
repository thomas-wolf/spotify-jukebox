import json
import threading
import time

import pytest

from jukebox.mqtt_export import MqttExporter, make_paho_client

METRICS = {
    "version": "3.0.0.dev0", "box": "pferd", "backend": "go-librespot", "cards": 12,
    "last_sync": "2026-11-18T06:00:00+00:00", "last_sync_ok": True, "battery_soc": None,
    "soloist_build_age_days": None, "soloist_expires_in_days": None,
}


class FakeMqtt:
    def __init__(self, fail_connects: int = 0) -> None:
        self.fail_connects = fail_connects
        self.will = None
        self.connects = 0
        self.loops = 0
        self.published: list[tuple[str, str, bool]] = []

    def will_set(self, topic, payload, retain):
        self.will = (topic, payload, retain)

    def connect(self, host, port, keepalive):
        self.connects += 1
        if self.connects <= self.fail_connects:
            raise ConnectionRefusedError("broker down")

    def loop_start(self):
        self.loops += 1

    def publish(self, topic, payload, retain):
        self.published.append((topic, payload, retain))

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


def exporter(client, metrics=None, backend="go-librespot", interval=60.0):
    return MqttExporter(client, lambda: dict(metrics or METRICS), "pferd", backend=backend, interval=interval)


def state_messages(client):
    return [json.loads(p) for t, p, _ in client.published if t.endswith("/state")]


def test_discovery_uses_retained_configs_with_stable_ids():
    ex = exporter(FakeMqtt())
    topics = {t: c for t, c in ex.discovery_messages(METRICS)}
    assert "homeassistant/sensor/jukebox_pferd/cards/config" in topics
    cards = topics["homeassistant/sensor/jukebox_pferd/cards/config"]
    assert cards["unique_id"] == "jukebox_pferd_cards"
    assert cards["state_topic"] == "jukebox/pferd/state"
    assert cards["availability_topic"] == "jukebox/pferd/availability"
    assert cards["device"]["identifiers"] == ["jukebox_pferd"]
    assert "homeassistant/binary_sensor/jukebox_pferd/sync_problem/config" in topics


def test_soloist_entities_only_for_soloist_boxes():
    no_soloist = {t for t, _ in exporter(FakeMqtt()).discovery_messages(METRICS)}
    assert not any("soloist" in t for t in no_soloist)
    with_soloist = {t for t, _ in exporter(FakeMqtt(), backend="soloist").discovery_messages(METRICS)}
    assert "homeassistant/sensor/jukebox_pferd/soloist_expires_in_days/config" in with_soloist


def test_publish_once_sends_discovery_online_and_state_without_nulls():
    client = FakeMqtt()
    ex = exporter(client)
    ex._connect()
    ex.publish_once()
    assert (("jukebox/pferd/availability", "online", True)) in client.published
    assert all(retain for _, _, retain in client.published)
    state = state_messages(client)[-1]
    assert state["cards"] == 12
    assert "battery_soc" not in state and "soloist_expires_in_days" not in state


def test_last_will_is_offline_and_set_once():
    client = FakeMqtt(fail_connects=2)
    ex = exporter(client)
    assert ex._connect() is False
    assert ex._connect() is False
    assert ex._connect() is True
    assert ex._connect() is True
    assert client.will == ("jukebox/pferd/availability", "offline", True)
    assert client.connects == 3 and client.loops == 1


def test_run_retries_until_broker_is_up_and_says_offline_on_stop():
    client = FakeMqtt(fail_connects=1)
    ex = exporter(client, interval=0.01)
    t = threading.Thread(target=ex.run, daemon=True)
    t.start()
    deadline = time.time() + 2
    while time.time() < deadline and not state_messages(client):
        time.sleep(0.01)
    ex.stop()
    t.join(timeout=2)
    assert state_messages(client), "no state published after the broker came up"
    assert client.published[-1] == ("jukebox/pferd/availability", "offline", True)


def test_paho_client_without_library_gives_clear_error():
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="paho-mqtt"):
            make_paho_client("127.0.0.1", 1883, "", "", "pferd")
    else:
        pytest.skip("paho-mqtt is installed")
