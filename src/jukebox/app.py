"""Core logic: turns card and action events into player calls."""

from __future__ import annotations

import logging
import subprocess
import threading
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
        self._cards_ci = {k.lower(): v for k, v in cards.items()}
        self._cards_lock = threading.Lock()
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
        # Boot first so the startup sound is not held up by a player that is still waking up;
        # the start volume follows through the same queue.
        self.bus.post(ev.BOOT)
        self.bus.post(ev.ACTION, name="volume_set", args={"value": self.cfg.section("audio")["start_volume"]})

    # -- event entry point (runs on the main loop thread) -------------------
    def handle(self, event: Event) -> None:
        if event.name == ev.CARD:
            self.on_card(str(event.data["id"]), str(event.data.get("source", "")))
        elif event.name == ev.ACTION:
            self.do_action(event.data["name"], **event.data.get("args", {}))

    # -- cards ---------------------------------------------------------------
    def set_card(self, card: Card) -> None:
        """Add or replace a card; safe to call from another thread (the web UI)."""
        with self._cards_lock:
            for key in [k for k in self.cards if k.lower() == card.id.lower()]:
                del self.cards[key]
            self.cards[card.id] = card
            self._cards_ci = {k.lower(): v for k, v in self.cards.items()}

    def replace_cards(self, cards: dict[str, Card]) -> None:
        """Swap in a whole new card set (after a sync); thread safe like set_card."""
        with self._cards_lock:
            self.cards = dict(cards)
            self._cards_ci = {k.lower(): v for k, v in self.cards.items()}

    def remove_card(self, card_id: str) -> bool:
        with self._cards_lock:
            keys = [k for k in self.cards if k.lower() == card_id.lower()]
            for key in keys:
                del self.cards[key]
            self._cards_ci = {k.lower(): v for k, v in self.cards.items()}
        return bool(keys)

    def on_card(self, card_id: str, source: str = "") -> None:
        card = self._cards_ci.get(card_id.lower())
        if card is None:
            log.info("unknown card %s (%s)", card_id, source or "?")
            self.bus.post(ev.CARD_UNKNOWN, id=card_id)
            return
        # One line per card, with its source: this is what to look at when a start seems late.
        log.info("card %s (%s) via %s: %s", card_id, card.name or "-", source or "?", card.action or card.play)
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
            target = self.players.current_target
            assert target
            self.players.play(target)
            self.bus.post(ev.PLAYING, target=target)
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
