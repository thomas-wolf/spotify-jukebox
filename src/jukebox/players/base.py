from __future__ import annotations

from abc import ABC, abstractmethod


class PlayerError(RuntimeError):
    """A backend could not do what was asked (not running, unreachable, ...)."""


class Player(ABC):
    """One playback backend. Volume is 0..100 and software-controlled,
    because the HiFiBerry MiniAmp has no hardware mixer."""

    name = "player"

    @abstractmethod
    def play(self, target: str) -> None: ...

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def resume(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def next(self) -> None: ...

    @abstractmethod
    def prev(self) -> None: ...

    @abstractmethod
    def seek(self, seconds: float) -> None:
        """Relative seek."""

    @abstractmethod
    def set_volume(self, volume: int) -> None: ...

    @abstractmethod
    def is_playing(self) -> bool: ...

    def has_session(self) -> bool:
        """True if the backend has something loaded that play/next/prev can act on, although the jukebox did not
        start it (a Spotify Connect session started from the app, then paused)."""
        return False

    def close(self) -> None:
        pass
