"""Display interface. The ILI9341 SPI driver is not written yet; boxes without
a driver use ``NullDisplay`` and everything else works unchanged."""

from __future__ import annotations

from typing import Protocol

from ..events import Event, EventBus


class Display(Protocol):
    def show_cover(self, cover_url: str | None) -> None: ...
    def show_text(self, title: str, subtitle: str = "") -> None: ...
    def clear(self) -> None: ...


class NullDisplay:
    def show_cover(self, cover_url: str | None) -> None:
        pass

    def show_text(self, title: str, subtitle: str = "") -> None:
        pass

    def clear(self) -> None:
        pass


def bind(display: Display, bus: EventBus) -> None:
    """Connect a display driver to the events that carry track information."""
    def on_track(event: Event) -> None:
        display.show_cover(event.data.get("cover_url"))
        display.show_text(event.data.get("title", ""), event.data.get("artist", ""))

    bus.subscribe("track", on_track)
    bus.subscribe("stopped", lambda _e: display.clear())
