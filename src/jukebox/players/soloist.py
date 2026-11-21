"""Spotify through Spotify Soloist, Spotify's own headless Connect client (the alternative to go-librespot).

Soloist runs as a separate daemon (`soloist --device-name ... --api-key ... --ws 127.0.0.1:9090`) and offers a
local WebSocket API. Commands are JSON text frames `{"type": "command", "command": "...", ...}`; the answers are
events (`auth_state`, `playback_state`, `command_result`, `error`, ...).

Checked against Spotify's Soloist documentation (developer.spotify.com/documentation/soloist) and a real
`playback_state` from soloist 1.3.10.79 on macOS (the sample in tests/test_soloist.py). Not yet run on a Pi.
Confirmed on that Mac: `play` with a playlist or album URI, restored login after a restart, `get_state`.
Taken from the documentation or from other users' reports, not tried here: `pause`, `skip_next`, `skip_prev`,
`set_volume` {volume 0..100}, and the field name of `seek`.

Known behaviour of Soloist that is handled here:
- `set_volume` while Soloist is not the active device is accepted and dropped, and with PipeWire the
  start volume is ignored: for a few seconds after `play` the volume is sent again if Soloist reports another one.
- With a wrong API key the daemon keeps running, signed out: `auth_state` then says `logged_in: false`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from .base import Player, PlayerError
from .websocket import WebSocket, WebSocketError

log = logging.getLogger(__name__)

HEARTBEAT = 5.0           # seconds between state requests; Soloist's own events do not cover everything
VOLUME_WINDOW = 15.0      # seconds after `play` during which the wanted volume is enforced
PLAYING = ("playing", "buffering")


def parse_ws(text: str) -> tuple[str, int]:
    """'127.0.0.1:9090' (or 'ws://127.0.0.1:9090') -> ('127.0.0.1', 9090)"""
    text = text.removeprefix("ws://").rstrip("/")
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise PlayerError(f"[spotify] soloist_ws must look like 127.0.0.1:9090, not {text!r}")
    return host, int(port)


def track_from_state(state: dict[str, Any]) -> dict[str, Any] | None:
    """Title, artist, cover and uri of the current item of a `playback_state`, or None if nothing is loaded."""
    item = state.get("item") or {}
    uri = item.get("uri")
    if not uri:
        return None
    deco = item.get("decorations") or {}

    def name(entity: dict[str, Any]) -> str:
        return (((entity or {}).get("decorations") or {}).get("identity") or {}).get("name") or ""

    artists = [name(c.get("entity")) for c in deco.get("creators") or []]
    covers = (deco.get("visual_identity") or {}).get("cover") or []
    by_size = {c.get("size"): c.get("url") for c in covers if c.get("url")}
    cover = by_size.get("default") or by_size.get("large") or next(iter(by_size.values()), None)
    return {"title": name(item), "artist": ", ".join(a for a in artists if a), "cover_url": cover, "uri": uri}


class SoloistClient(threading.Thread):
    """Keeps one WebSocket connection to Soloist (reconnects by itself), remembers the latest state."""

    def __init__(self, host: str, port: int, connect: Callable[..., WebSocket] = WebSocket.connect) -> None:
        super().__init__(name="soloist", daemon=True)
        self.host, self.port, self._connect = host, port, connect
        self.state: dict[str, Any] | None = None
        self.logged_in: bool | None = None
        self.connected = False
        self.listeners: list[Callable[[dict[str, Any]], None]] = []
        self.wanted_volume: int | None = None
        self.enforce_until = 0.0
        self._ws: WebSocket | None = None
        self._write = threading.Lock()
        self._halt = threading.Event()
        self._last_fix = 0.0
        self._warned = False

    # -- sending -----------------------------------------------------------------
    def send(self, command: str, **fields: Any) -> None:
        ws = self._ws
        if ws is None or not self.connected:
            raise PlayerError(f"Soloist is not reachable at {self.host}:{self.port}")
        if self.logged_in is False and command != "get_state":
            raise PlayerError("Soloist is not logged in: pair it once from the Spotify app (docs/INSTALL.md)")
        message = json.dumps({"type": "command", "command": command, **fields})
        try:
            with self._write:
                ws.send_text(message)
        except OSError as exc:
            raise PlayerError(f"Soloist connection lost: {exc}") from exc

    def _request_state(self) -> None:
        try:
            self.send("get_state")
        except PlayerError:
            pass

    # -- receiving ---------------------------------------------------------------
    def handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "auth_state":
            self.logged_in = bool(message.get("logged_in"))
            if self.logged_in:
                self._request_state()
            else:
                log.warning("Soloist is not logged in; pair it once from the Spotify app")
        elif kind == "playback_state":
            self.state = message
            self._enforce_volume(message)
            for listener in list(self.listeners):
                try:
                    listener(message)
                except Exception:
                    log.exception("Soloist listener failed")
        elif kind in ("playback_changed", "volume_changed"):
            self._request_state()
        elif kind == "error":
            log.warning("Soloist: %s", message.get("message") or message)

    def _enforce_volume(self, state: dict[str, Any]) -> None:
        wanted, now = self.wanted_volume, time.monotonic()
        if wanted is None or now > self.enforce_until or now - self._last_fix < 1.0:
            return
        reported = state.get("volume")
        if state.get("is_active") and isinstance(reported, (int, float)) and abs(reported - wanted) > 1:
            self._last_fix = now
            try:
                self.send("set_volume", volume=wanted)
            except PlayerError:
                pass

    def run(self) -> None:
        delay = 1.0
        while not self._halt.is_set():
            try:
                ws = self._connect(self.host, self.port)
            except OSError as exc:
                if not self._warned:
                    log.warning("Soloist not reachable at %s:%s (%s); trying again", self.host, self.port, exc)
                    self._warned = True
                self._halt.wait(delay)
                delay = min(delay * 2, 10.0)
                continue
            delay, self._warned = 1.0, False
            self._ws, self.connected = ws, True
            log.info("connected to Soloist at %s:%s", self.host, self.port)
            try:
                ws.sock.settimeout(HEARTBEAT)
                self._request_state()
                while not self._halt.is_set():
                    try:
                        text = ws.recv_text()
                    except TimeoutError:
                        self._request_state()
                        continue
                    try:
                        self.handle(json.loads(text))
                    except ValueError:
                        log.warning("Soloist sent something that is not JSON")
            except WebSocketError as exc:
                log.warning("Soloist connection ended: %s", exc)
            except OSError as exc:
                log.warning("Soloist connection failed: %s", exc)
            finally:
                self.connected, self._ws = False, None
                self.logged_in = None
                try:
                    ws.sock.close()
                except OSError:
                    pass

    def stop(self) -> None:
        self._halt.set()
        ws = self._ws
        if ws is not None:
            ws.close()


class SoloistPlayer(Player):
    name = "spotify"

    def __init__(self, client: SoloistClient) -> None:
        self.client = client

    def play(self, target: str) -> None:
        if not target.startswith("spotify:"):
            raise PlayerError(f"not a Spotify URI: {target!r}")
        self.client.enforce_until = time.monotonic() + VOLUME_WINDOW
        self.client.send("play", uri=target)

    def pause(self) -> None:
        self.client.send("pause")

    def resume(self) -> None:
        self.client.send("play")

    def stop(self) -> None:
        self.pause()      # as with go-librespot: Connect has no real stop

    def next(self) -> None:
        self.client.send("skip_next")

    def prev(self) -> None:
        self.client.send("skip_prev")

    def seek(self, seconds: float) -> None:
        state = self.client.state or {}
        pos = state.get("position") or {}
        if "position_ms" not in pos:
            raise PlayerError("nothing is playing")
        now = float(pos["position_ms"])
        if state.get("status") in PLAYING and "timestamp_ms" in pos:
            now += (time.time() * 1000 - float(pos["timestamp_ms"])) * float(pos.get("speed", 1))
        self.client.send("seek", position_ms=max(0, int(now + seconds * 1000)))   # field name: not verified

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, int(volume)))
        self.client.wanted_volume = volume
        self.client.send("set_volume", volume=volume)

    def is_playing(self) -> bool:
        return bool(self.client.state) and self.client.state.get("status") in PLAYING

    def has_session(self) -> bool:
        state = self.client.state or {}
        return bool(state.get("item"))

    def close(self) -> None:
        self.client.stop()
