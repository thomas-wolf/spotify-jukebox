"""Thread-safe event queue plus an observer bus.

Inputs (readers, GPIO, ADC) run in their own threads and only call
``bus.post(...)``. The main loop drains the queue, so all player logic runs
on one thread. Hooks (LED animations, sounds, display) subscribe with
``bus.subscribe``; a failing hook never stops the box.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

# Event names used by the core. Hooks may also post their own.
CARD = "card"                  # data: id
CARD_UNKNOWN = "card_unknown"  # data: id
ACTION = "action"              # data: name, args
BOOT = "boot"
PLAYING = "playing"            # data: target
PAUSED = "paused"
STOPPED = "stopped"
VOLUME = "volume"              # data: value
TRACK = "track"                # data: title, artist, cover_url
SHUTDOWN = "shutdown"
UPDATED = "updated"            # data: old, new (the installed build changed since the last start)
ERROR = "error"                # data: message
CARDS_SAVED = "cards_saved"    # cards.toml was written by the web interface
CARDS_CHANGED = "cards_changed"  # cards.toml was replaced on disk (sync): reload it


@dataclass
class Event:
    name: str
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._queue: queue.Queue[Event | None] = queue.Queue()
        self._handlers: dict[str, list[Handler]] = {}
        self._lock = threading.Lock()

    def post(self, name: str, /, **data: Any) -> None:
        # positional-only: event data may itself contain a key called "name"
        self._queue.put(Event(name, data))

    def subscribe(self, name: str, handler: Handler) -> None:
        """Subscribe to one event name; '*' receives everything."""
        with self._lock:
            self._handlers.setdefault(name, []).append(handler)

    def stop(self) -> None:
        self._queue.put(None)

    def dispatch(self, event: Event) -> None:
        with self._lock:
            handlers = list(self._handlers.get(event.name, ())) + list(self._handlers.get("*", ()))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                log.exception("handler failed for event %s", event.name)

    def run(self, core: Handler) -> None:
        """Block, feeding every event to ``core`` first, then to observers."""
        while True:
            event = self._queue.get()
            if event is None:
                return
            try:
                core(event)
            except Exception:
                log.exception("core failed for event %s", event.name)
            self.dispatch(event)

    def drain(self, core: Handler) -> None:
        """Process queued events without blocking (used by tests)."""
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                return
            if event is None:
                return
            core(event)
            self.dispatch(event)
