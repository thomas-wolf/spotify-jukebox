"""Chooses the backend by target scheme and keeps only one of them playing."""

from __future__ import annotations

import logging

from .base import Player, PlayerError

log = logging.getLogger(__name__)


class PlayerRouter:
    def __init__(self, backends: dict[str, Player]) -> None:
        # scheme -> backend, e.g. {"spotify": ..., "folder": ..., "file": ...}
        self._backends = backends
        self._active: Player | None = None
        self._volume = 0
        self.current_target: str | None = None

    def backend(self, scheme: str) -> Player | None:
        return self._backends.get(scheme)

    def _backend_for(self, target: str) -> Player:
        scheme = target.partition(":")[0]
        try:
            return self._backends[scheme]
        except KeyError:
            raise PlayerError(f"no player enabled for {target!r}") from None

    def play(self, target: str) -> None:
        backend = self._backend_for(target)
        if self._active is not None and self._active is not backend:
            try:
                self._active.stop()
            except PlayerError:
                log.warning("could not stop previous backend", exc_info=True)
        backend.set_volume(self._volume)
        backend.play(target)
        self._active = backend
        self.current_target = target

    def _current(self) -> Player | None:
        """The backend the buttons control: the one that is playing right now, also when somebody else started it
        (the Spotify app: "play on <box>"), otherwise the one the jukebox started last, otherwise a backend with a
        loaded session (started from outside and paused)."""
        active = self._active
        if active is not None and active.is_playing():
            return active
        for backend in set(self._backends.values()):
            if backend is not active and backend.is_playing():
                self._active, self.current_target = backend, None
                return backend
        if active is None:
            for backend in set(self._backends.values()):
                if backend.has_session():
                    self._active = backend
                    return backend
        return active

    def _need(self) -> Player:
        active = self._current()
        if active is None:
            raise PlayerError("nothing is loaded")
        return active

    def pause(self) -> None:
        self._need().pause()

    def resume(self) -> None:
        self._need().resume()

    def toggle(self) -> None:
        active = self._need()
        active.pause() if active.is_playing() else active.resume()

    def stop(self) -> None:
        active = self._current()
        if active is not None:
            active.stop()

    def next(self) -> None:
        self._need().next()

    def prev(self) -> None:
        self._need().prev()

    def seek(self, seconds: float) -> None:
        self._need().seek(seconds)

    def is_playing(self) -> bool:
        active = self._current()
        return active is not None and active.is_playing()

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, volume))
        for backend in set(self._backends.values()):
            try:
                backend.set_volume(self._volume)
            except PlayerError:
                log.warning("volume not applied to %s (it is applied again on the next play)", backend.name)

    @property
    def volume(self) -> int:
        return self._volume

    def close(self) -> None:
        for backend in set(self._backends.values()):
            backend.close()
