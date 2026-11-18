"""Minutes of playback per day, kept in the data dir. Fed by the bus events playing / paused / stopped / shutdown.

A day is the local date at the moment playback stops, so a session that runs past midnight counts for the day it
ends on. Days older than KEEP_DAYS are dropped.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date
from pathlib import Path
from typing import Callable

from . import events as ev

log = logging.getLogger(__name__)

KEEP_DAYS = 30


class Playtime:
    def __init__(self, path: Path, clock: Callable[[], float] = time.monotonic,
                 today: Callable[[], date] = date.today) -> None:
        self.path, self.clock, self.today = path, clock, today
        self._lock = threading.Lock()
        self._started: float | None = None
        self._days: dict[str, float] = self._load()

    # -- persistence ----------------------------------------------------------------------
    def _load(self) -> dict[str, float]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, float] = {}
        for key, value in data.items():
            try:
                out[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return out

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._days, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            log.warning("could not write playtime to %s", self.path, exc_info=True)

    def _prune(self) -> None:
        for key in sorted(self._days)[:-KEEP_DAYS]:
            del self._days[key]

    # -- counting -------------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._started is None:
                self._started = self.clock()

    def stop(self) -> None:
        with self._lock:
            if self._started is None:
                return
            seconds = self.clock() - self._started
            self._started = None
            key = self.today().isoformat()
            self._days[key] = self._days.get(key, 0.0) + seconds
            self._prune()
            self._save()

    def minutes(self, day: date | None = None) -> float:
        """Playback minutes of ``day`` (default today), including a session that is still running."""
        day = day or self.today()
        with self._lock:
            seconds = self._days.get(day.isoformat(), 0.0)
            if self._started is not None and day == self.today():
                seconds += self.clock() - self._started
        return round(seconds / 60, 1)

    def bind(self, bus) -> None:
        bus.subscribe(ev.PLAYING, lambda _e: self.start())
        for name in (ev.PAUSED, ev.STOPPED, ev.SHUTDOWN):
            bus.subscribe(name, lambda _e: self.stop())
