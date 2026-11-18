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


class SoloistTrackReporter:
    """Reports what Soloist plays as `track` events. Fed with every `playback_state` by the Soloist client
    (a listener, no polling). Only while playing: a session restored in the paused state should not put the old
    cover on the screen at boot."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self._last: tuple[str, bool] | None = None

    def on_state(self, state: dict) -> None:
        from .soloist import PLAYING, track_from_state
        info = track_from_state(state)
        if info is None:
            self._last = None
            return
        playing = state.get("status") in PLAYING
        if playing and (self._last is None or self._last[0] != info["uri"] or not self._last[1]):
            self.bus.post(ev.TRACK, **info)
        self._last = (info["uri"], playing)


class LocalTrackPoller(threading.Thread):
    """Reports the local file that mpv plays as `track` events, with a cover picture if there is one:
    first a picture in the folder, then (in a second event, once found) one from Spotify."""

    def __init__(self, bus, player, resolver, root, interval: float = 2.0) -> None:
        super().__init__(name="localtrackinfo", daemon=True)
        from pathlib import Path
        self.bus, self.player, self.resolver, self.interval = bus, player, resolver, interval
        self.root = Path(root).resolve()
        self._last: tuple[str, bool] | None = None
        self._tried: set[str] = set()
        self._last_stream: tuple | None = None
        self._halt = threading.Event()

    def poll_once(self) -> None:
        from pathlib import Path
        info = self.player.current_track()
        if not info:
            self._last = self._last_stream = None
            return
        playing = not info["paused"]
        if info.get("stream"):
            return self._stream(info, playing)
        path = Path(info["path"])
        key = (info["path"], playing)
        if self._last is not None and self._last[0] == key[0] and not (playing and not self._last[1]):
            self._last = key
            return
        self._last = key
        folder = path.parent
        title = info["title"] or path.stem
        cover = self.resolver.lookup(folder)
        self._post(title, info["artist"], cover, info["path"])
        if cover is None and str(folder) not in self._tried:
            self._tried.add(str(folder))
            # without tags: folder name = album, the folder above it (inside the music root) = artist
            parent = folder.parent.name if self.root in folder.parents and folder.parent != self.root else ""
            found = self.resolver.fetch(folder, info["album"] or folder.name, info["artist"] or parent)
            if found:
                self._post(title, info["artist"], found, info["path"])

    def _stream(self, info, playing: bool) -> None:
        """Web radio: no cover; report again whenever the song (the stream's title) changes."""
        key = (info["path"], playing, info["title"])
        if key != self._last_stream:
            self._last_stream = key
            self._last = (info["path"], playing)
            self._post(info["title"] or info["artist"] or info["path"], info["artist"] if info["title"] else "",
                       None, info["path"])

    def _post(self, title, artist, cover, uri) -> None:
        self.bus.post(ev.TRACK, title=title, artist=artist, cover_url=cover, uri=uri)

    def run(self) -> None:
        while not self._halt.wait(self.interval):
            try:
                self.poll_once()
            except Exception:
                log.exception("local track info failed")

    def stop(self) -> None:
        self._halt.set()
