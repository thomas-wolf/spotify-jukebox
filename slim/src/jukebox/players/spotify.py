"""Spotify through a local go-librespot daemon.

go-librespot registers itself as a Spotify Connect device and exposes a REST
API on localhost, so commands do not go through Spotify's Web API.

Endpoints and request fields were checked against go-librespot's api-spec.yml (release v0.10.5, November
2026): POST /player/play {uri}, /player/pause, /player/resume, /player/next, /player/prev,
/player/seek {position (ms), relative}, /player/volume {volume}, GET /status (204 without a session).
Not yet run against a real daemon from this code.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Callable

from .base import Player, PlayerError

log = logging.getLogger(__name__)

# name -> (HTTP method, path), as in api-spec.yml.
ENDPOINTS: dict[str, tuple[str, str]] = {
    "status": ("GET", "/status"),
    "play": ("POST", "/player/play"),
    "pause": ("POST", "/player/pause"),
    "resume": ("POST", "/player/resume"),
    "next": ("POST", "/player/next"),
    "prev": ("POST", "/player/prev"),
    "seek": ("POST", "/player/seek"),
    "volume": ("POST", "/player/volume"),
}

Transport = Callable[[str, str, "dict[str, Any] | None"], Any]


def http_transport(base_url: str, timeout: float = 5.0) -> Transport:
    base = base_url.rstrip("/")

    def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise PlayerError(f"go-librespot {method} {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PlayerError(f"go-librespot not reachable at {base}: {exc}") from exc
        return json.loads(raw) if raw else None

    return call


class SpotifyPlayer(Player):
    name = "spotify"

    def __init__(self, transport: Transport) -> None:
        self._call = transport
        self._playing = False

    def _do(self, name: str, body: dict[str, Any] | None = None) -> Any:
        method, path = ENDPOINTS[name]
        return self._call(method, path, body)

    def play(self, target: str) -> None:
        if not target.startswith("spotify:"):
            raise PlayerError(f"not a Spotify URI: {target!r}")
        self._do("play", {"uri": target})
        self._playing = True

    def pause(self) -> None:
        self._do("pause")
        self._playing = False

    def resume(self) -> None:
        self._do("resume")
        self._playing = True

    def stop(self) -> None:
        # Connect has no real "stop"; pausing keeps the session warm and
        # makes the next card start faster.
        self.pause()

    def next(self) -> None:
        self._do("next")

    def prev(self) -> None:
        self._do("prev")

    def seek(self, seconds: float) -> None:
        self._do("seek", {"position": int(seconds * 1000), "relative": True})

    def set_volume(self, volume: int) -> None:
        self._do("volume", {"volume": max(0, min(100, volume))})

    def is_playing(self) -> bool:
        try:
            status = self._do("status") or {}
        except PlayerError:
            return self._playing
        if "paused" in status:
            self._playing = not status["paused"] and not status.get("stopped", False)
        return self._playing
