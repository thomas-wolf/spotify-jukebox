"""Reports what go-librespot is playing (title, artist, cover) as `track` events.

Polls GET /status (documented in go-librespot's api-spec.yml: 204 without a session, otherwise `track` with
`uri`, `name`, `artist_names`, `album_cover_url`, plus `paused` and `stopped`). Polling instead of the
WebSocket keeps the core free of a WebSocket client.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from .. import events as ev
from .base import PlayerError
from .spotify import ENDPOINTS

log = logging.getLogger(__name__)


class SpotifyTrackPoller(threading.Thread):
    def __init__(self, bus, transport, interval: float = 2.0) -> None:
        super().__init__(name="trackinfo", daemon=True)
        self.bus, self._call, self.interval = bus, transport, interval
        self._last: tuple[str, bool] | None = None
        self._halt = threading.Event()

    def poll_once(self) -> None:
        method, path = ENDPOINTS["status"]
        try:
            status: Any = self._call(method, path, None)
        except PlayerError:
            return
        track = (status or {}).get("track") if isinstance(status, dict) else None
        if not track or not track.get("uri"):
            self._last = None
            return
        playing = not status.get("paused", False) and not status.get("stopped", False)
        key = (track["uri"], playing)
        # post when the track changes, or when playback resumes (the display may have been cleared)
        if self._last is None or self._last[0] != key[0] or (playing and not self._last[1]):
            self.bus.post(ev.TRACK, title=track.get("name", ""), artist=", ".join(track.get("artist_names") or []),
                          cover_url=track.get("album_cover_url"), uri=track["uri"])
        self._last = key

    def run(self) -> None:
        while not self._halt.wait(self.interval):
            self.poll_once()

    def stop(self) -> None:
        self._halt.set()
