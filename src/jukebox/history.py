"""Playback history: the tracks the box played, newest last. Fed by the track events of the players.

The same track reported again (the poller sends it every few seconds, and a pause resumes it) is not a new entry:
an entry is added only when the title or artist differs from the last one. The last ``limit`` entries are kept
in ``history.json`` in the data dir.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import events as ev

log = logging.getLogger(__name__)

LIMIT = 50


class PlayHistory:
    def __init__(self, path: Path, limit: int = LIMIT,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.path, self.now = path, now
        self._lock = threading.Lock()
        self._entries: deque[dict[str, Any]] = deque(self._load(), maxlen=limit)

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict) and e.get("title")]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(list(self._entries), indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        except OSError:
            log.warning("could not write play history to %s", self.path, exc_info=True)

    def record(self, title: str, artist: str = "", uri: str = "") -> bool:
        """Adds a track unless it is the same as the last one. Returns True when an entry was added."""
        title = (title or "").strip()
        if not title:
            return False
        artist = (artist or "").strip()
        with self._lock:
            if self._entries and (self._entries[-1]["title"], self._entries[-1].get("artist", "")) == (title, artist):
                return False
            entry: dict[str, Any] = {"time": self.now().isoformat(timespec="seconds"), "title": title, "artist": artist}
            if uri:
                entry["uri"] = uri
            self._entries.append(entry)
            self._save()
        return True

    def last(self, n: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)[-n:]

    def bind(self, bus) -> None:
        bus.subscribe(ev.TRACK, self._on_track)

    def _on_track(self, event) -> None:
        data = getattr(event, "data", None) or {}
        self.record(data.get("title", ""), data.get("artist", ""), data.get("uri", ""))
