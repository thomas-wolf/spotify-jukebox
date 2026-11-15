"""Display: shows cover and track text. Boxes without a display use NullDisplay and nothing else changes."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Protocol

from ..events import Event, EventBus

log = logging.getLogger(__name__)


class Display(Protocol):
    def show_track(self, title: str, artist: str = "", cover_url: str | None = None) -> None: ...
    def clear(self) -> None: ...
    def close(self) -> None: ...


class NullDisplay:
    def show_track(self, title: str, artist: str = "", cover_url: str | None = None) -> None:
        pass

    def clear(self) -> None:
        pass

    def close(self) -> None:
        pass


class ScreenDisplay:
    """Renders in a worker thread, so downloading a cover never blocks cards or buttons.
    Only the newest request counts: if tracks change quickly, the older ones are dropped."""

    def __init__(self, renderer, driver, fetch=None) -> None:
        self._renderer, self._driver = renderer, driver
        if fetch is None:
            from .render import fetch_cover
            fetch = fetch_cover
        self._fetch = fetch
        self._q: queue.Queue = queue.Queue(maxsize=1)
        self._cache: tuple[str, object] | None = None
        self._thread = threading.Thread(target=self._run, name="display", daemon=True)
        self._thread.start()

    def _put(self, item) -> None:
        try:
            self._q.get_nowait()                  # drop an older, not yet handled request
        except queue.Empty:
            pass
        self._q.put(item)

    def show_track(self, title: str, artist: str = "", cover_url: str | None = None) -> None:
        self._put(("track", title, artist, cover_url))

    def clear(self) -> None:
        self._put(("clear",))

    def close(self) -> None:
        self._put(("close",))
        self._thread.join(timeout=5)

    def _cover(self, url: str | None):
        if not url:
            return None
        if self._cache and self._cache[0] == url:
            return self._cache[1]
        try:
            img = self._fetch(url)
        except Exception as exc:                  # network, bad image: show the text without a cover
            log.warning("cover not loaded: %s", exc)
            return None
        self._cache = (url, img)
        return img

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item[0] == "close":
                    self._driver.close()
                    return
                if item[0] == "clear":
                    self._driver.show(self._renderer.blank())
                else:
                    _, title, artist, url = item
                    self._driver.show(self._renderer.render(self._cover(url), title, artist))
            except Exception:
                log.exception("display update failed")


def build_display(section: dict) -> Display:
    """The display described by the [display] section; NullDisplay (with an error in the log) if the
    hardware or packages are missing, so that the rest of the box keeps working."""
    from ..config import ConfigError
    from .settings import DisplaySettings
    try:
        settings = DisplaySettings.from_section(section)
    except ConfigError as exc:
        log.error("display disabled: %s", exc)
        return NullDisplay()
    try:
        from .ili9341 import ILI9341
        from .render import Renderer
        renderer = Renderer(settings)
        return ScreenDisplay(renderer, ILI9341(settings))
    except Exception as exc:                      # missing PIL/spidev/gpiod, no SPI device, ...
        log.error("display disabled: %s", exc)
        return NullDisplay()


def bind(display: Display, bus: EventBus) -> None:
    """Connect a display to the events that carry track information."""
    def on_track(event: Event) -> None:
        display.show_track(event.data.get("title", ""), event.data.get("artist", ""), event.data.get("cover_url"))

    def on_playing(event: Event) -> None:
        if event.data.get("name"):                # started by a card: name now, track info follows
            display.show_track(event.data["name"], "", None)

    bus.subscribe("track", on_track)
    bus.subscribe("playing", on_playing)
    bus.subscribe("stopped", lambda _e: display.clear())
    bus.subscribe("shutdown", lambda _e: display.clear())
