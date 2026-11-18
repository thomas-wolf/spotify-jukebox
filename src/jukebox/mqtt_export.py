"""Publishes the box metrics to MQTT for Home Assistant (MQTT discovery). Read-only: nothing is subscribed.

Each tick publishes, all retained: the discovery configs, the state, and "online". The broker's last will
publishes "offline" when the box disappears. Repeating everything each tick means a restarted broker or a
reconnect is healed by the next tick, without tracking connection events.

The MQTT client is passed in (see ``make_paho_client``), so the logic is testable without a broker.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

from . import __version__

log = logging.getLogger(__name__)

# (key in the metrics dict, entity name, extra HA config). Only these keys become entities.
SENSORS: list[tuple[str, str, dict[str, Any]]] = [
    ("cards", "Karten", {"icon": "mdi:cards"}),
    ("last_sync", "Letzter Sync", {"device_class": "timestamp"}),
    ("soloist_expires_in_days", "Soloist läuft noch", {"unit_of_measurement": "d", "icon": "mdi:timer-sand"}),
    ("soloist_build_age_days", "Soloist Build-Alter", {"unit_of_measurement": "d", "icon": "mdi:calendar-clock"}),
    ("version", "Version", {"icon": "mdi:tag"}),
]
SOLOIST_KEYS = {"soloist_expires_in_days", "soloist_build_age_days"}


class MqttClient:
    """What the exporter needs from an MQTT client (paho-mqtt implements this shape)."""

    def will_set(self, topic: str, payload: str, retain: bool) -> None: ...
    def connect(self, host: str, port: int, keepalive: int) -> None: ...
    def loop_start(self) -> None: ...
    def publish(self, topic: str, payload: str, retain: bool) -> None: ...
    def loop_stop(self) -> None: ...
    def disconnect(self) -> None: ...


def make_paho_client(host: str, port: int, username: str, password: str, box: str) -> MqttClient:
    """Real client. Needs the "mqtt" extra; raises a clear error when paho-mqtt is missing."""
    try:
        import paho.mqtt.client as paho
    except ImportError as exc:
        raise RuntimeError("MQTT is enabled but paho-mqtt is not installed (pip install 'spotify-jukebox[mqtt]')") from exc

    client = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"jukebox-{box}")
    if username:
        client.username_pw_set(username, password or None)
    return client


class MqttExporter(threading.Thread):
    def __init__(self, client: MqttClient, metrics: Callable[[], dict[str, Any]], box: str, *,
                 backend: str, discovery_prefix: str = "homeassistant", topic_prefix: str = "jukebox",
                 interval: float = 60.0, host: str = "", port: int = 1883, keepalive: int = 60) -> None:
        super().__init__(name="mqtt-export", daemon=True)
        self.client, self.metrics, self.box, self.backend = client, metrics, box, backend
        self.discovery_prefix, self.topic_prefix = discovery_prefix, topic_prefix
        self.interval = interval
        self.host, self.port, self.keepalive = host, port, keepalive
        self._stop = threading.Event()
        self._connected = False
        self._will_set = False
        base = f"{topic_prefix}/{box}"
        self.state_topic = f"{base}/state"
        self.availability_topic = f"{base}/availability"

    # -- topics and payloads ------------------------------------------------------------
    def _device(self) -> dict[str, Any]:
        return {"identifiers": [f"jukebox_{self.box}"], "name": f"Jukebox {self.box}",
                "manufacturer": "spotify-jukebox", "sw_version": __version__}

    def discovery_messages(self, metrics: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for key, name, extra in SENSORS:
            if key in SOLOIST_KEYS and self.backend != "soloist" and metrics.get(key) is None:
                continue  # no Soloist on this box: no entity
            entity = {"name": name, "unique_id": f"jukebox_{self.box}_{key}",
                      "state_topic": self.state_topic, "value_template": f"{{{{ value_json.{key} }}}}",
                      "availability_topic": self.availability_topic, "entity_category": "diagnostic",
                      "device": self._device(), **extra}
            out.append((f"{self.discovery_prefix}/sensor/jukebox_{self.box}/{key}/config", entity))
        problem = {"name": "Letzter Sync fehlgeschlagen", "unique_id": f"jukebox_{self.box}_sync_problem",
                   "state_topic": self.state_topic, "device_class": "problem", "entity_category": "diagnostic",
                   "value_template": "{% if value_json.last_sync_ok is none %}{% else %}"
                                     "{{ 'OFF' if value_json.last_sync_ok else 'ON' }}{% endif %}",
                   "availability_topic": self.availability_topic, "device": self._device()}
        out.append((f"{self.discovery_prefix}/binary_sensor/jukebox_{self.box}/sync_problem/config", problem))
        return out

    # -- lifecycle ---------------------------------------------------------------------
    def _connect(self) -> bool:
        """Retried every tick until the broker answers. paho reconnects by itself after the first success."""
        if self._connected:
            return True
        try:
            if not self._will_set:
                self.client.will_set(self.availability_topic, "offline", retain=True)
                self._will_set = True
            self.client.connect(self.host, self.port, self.keepalive)
            self.client.loop_start()
        except Exception as exc:
            log.warning("MQTT: broker %s:%s not reachable yet (%s)", self.host, self.port, exc)
            return False
        self._connected = True
        log.info("MQTT: connected to %s:%s", self.host, self.port)
        return True

    def publish_once(self) -> None:
        metrics = self.metrics()
        for topic, config in self.discovery_messages(metrics):
            self.client.publish(topic, json.dumps(config), retain=True)
        self.client.publish(self.availability_topic, "online", retain=True)
        # null values are left out: the template then yields "unknown" in HA
        state = {k: v for k, v in metrics.items() if v is not None}
        self.client.publish(self.state_topic, json.dumps(state), retain=True)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._connect():
                    self.publish_once()
            except Exception:
                log.exception("MQTT: publish failed")
            self._stop.wait(self.interval)
        if not self._connected:
            return
        try:
            self.client.publish(self.availability_topic, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            log.debug("MQTT: clean shutdown failed", exc_info=True)

    def stop(self) -> None:
        self._stop.set()
