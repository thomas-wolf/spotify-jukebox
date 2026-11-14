"""Core logic: turns card and action events into player calls."""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Any, Callable

from . import events as ev
from .config import Card, Config
from .events import Event, EventBus
from .players import PlayerError, PlayerRouter

log = logging.getLogger(__name__)

SEEK_STEP = 15  # seconds, like the v2 seek cards


class App:
    def __init__(
        self,
        cfg: Config,
        cards: dict[str, Card],
        players: PlayerRouter,
        bus: EventBus,
        *,
        clock: Callable[[], float] = time.monotonic,
        run: Callable[[list[str]], Any] = subprocess.Popen,
    ) -> None:
        self.cfg, self.cards, self.players, self.bus = cfg, cards, players, bus
        self._clock, self._run = clock, run
        audio = cfg.section("audio")
        self.max_volume: int = audio["max_volume"]
        self.step: int = audio["volume_step"]
        self._muted_from: int | None = None
        self._last_card: str | None = None
        self._last_card_time = -1e9
        self.actions: dict[str, Callable[..., None]] = {
            "play_pause": self.players.toggle,
            "pause": self.players.pause,
            "resume": self.players.resume,
            "stop": self.players.stop,
            "next": self.players.next,
            "prev": self.players.prev,
            "seek_forward": lambda seconds=SEEK_STEP: self.players.seek(seconds),
            "seek_back": lambda seconds=SEEK_STEP: self.players.seek(-seconds),
            "volume_up": lambda: self.set_volume(self.players.volume + self.step),
            "volume_down": lambda: self.set_volume(self.players.volume - self.step),
            "volume_set": self.set_volume,
            "mute": self.toggle_mute,
            "shutdown": self.shutdown,
        }

    # -- start -------------------------------------------------------------
    def start(self) -> None:
        self.set_volume(self.cfg.section("audio")["start_volume"])
        self.bus.post(ev.BOOT)

    # -- event entry point (runs on the main loop thread) -------------------
    def handle(self, event: Event) -> None:
        if event.name == ev.CARD:
            self.on_card(str(event.data["id"]))
        elif event.name == ev.ACTION:
            self.do_action(event.data["name"], **event.data.get("args", {}))

    # -- cards ---------------------------------------------------------------
    def on_card(self, card_id: str) -> None:
        card = self.cards.get(card_id)
        if card is None:
            log.info("unknown card %s", card_id)
            self.bus.post(ev.CARD_UNKNOWN, id=card_id)
            return
        if card.action:
            self.do_action(card.action, **card.args)
            return
        assert card.play
        now = self._clock()
        same = card.play == self.players.current_target
        delay = self.cfg.section("cards")["same_card_delay"]
        recent = self._last_card == card_id and now - self._last_card_time < delay
        self._last_card, self._last_card_time = card_id, now
        if same and recent:
            return  # reader reported the same card repeatedly
        try:
            if same:
                self._same_card()
            else:
                self.players.play(card.play)
                self.bus.post(ev.PLAYING, target=card.play, name=card.name)
        except PlayerError as exc:
            self._error(exc)

    def _same_card(self) -> None:
        mode = self.cfg.section("cards")["same_card"]
        if mode == "toggle":
            self.players.toggle()
            self.bus.post(ev.PLAYING if self.players.is_playing() else ev.PAUSED,
                          target=self.players.current_target)
        elif mode == "restart":
            assert self.players.current_target
            self.players.play(self.players.current_target)
        elif mode == "next":
            self.players.next()

    # -- actions -------------------------------------------------------------
    def do_action(self, name: str, **args: Any) -> None:
        fn = self.actions.get(name)
        if fn is None:
            log.warning("unknown action %r", name)
            return
        try:
            fn(**args)
        except PlayerError as exc:
            self._error(exc)
        except TypeError:
            log.exception("bad arguments for action %s: %s", name, args)
            return
        if name in ("pause", "stop"):
            self.bus.post(ev.PAUSED if name == "pause" else ev.STOPPED)
        elif name in ("resume", "play_pause"):
            self.bus.post(ev.PLAYING if self.players.is_playing() else ev.PAUSED)

    def set_volume(self, value: int) -> None:
        value = max(0, min(self.max_volume, int(value)))
        self._muted_from = None
        self.players.set_volume(value)
        self.bus.post(ev.VOLUME, value=value)

    def toggle_mute(self) -> None:
        if self._muted_from is None:
            previous = self.players.volume
            self.set_volume(0)
            self._muted_from = previous
        else:
            previous, self._muted_from = self._muted_from, None
            self.set_volume(previous)

    def shutdown(self) -> None:
        self.bus.post(ev.SHUTDOWN)
        try:
            self.players.stop()
        except PlayerError:
            pass
        self._run(list(self.cfg.section("system")["shutdown_command"]))

    def _error(self, exc: Exception) -> None:
        log.error("%s", exc)
        self.bus.post(ev.ERROR, message=str(exc))
