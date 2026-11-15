"""GPIO buttons, rotary encoders and LEDs on libgpiod.

The behaviour (hold, repeat, quadrature decoding) is plain Python driven by
explicit timestamps, so it is tested without hardware. Only ``GpiodBackend``
touches the kernel, and it is imported lazily.

Per-box pinouts live in config.toml, e.g.

    [[gpio.button]]
    pin = 26
    action = "next"

    [[gpio.button]]
    pin = 16
    action = "volume_up"
    repeat = true            # keep firing while held

    [[gpio.button]]
    pin = 3
    action = "play_pause"
    hold_action = "shutdown" # held for hold_time seconds
    hold_time = 2.0

    [[gpio.rotary]]
    pin_a = 22
    pin_b = 23
    cw = "volume_up"
    ccw = "volume_down"

    [[gpio.led]]
    name = "status"
    pin = 14
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from typing import Any, Callable, Protocol

from ..events import EventBus

log = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], None]


class Button:
    def __init__(self, emit: Emit, *, pull: str = "up", action: str | None = None,
                 args: dict[str, Any] | None = None, hold_action: str | None = None,
                 hold_time: float = 1.0, repeat: bool = False,
                 repeat_interval: float = 0.3) -> None:
        self.emit, self.action, self.args = emit, action, args or {}
        self.hold_action, self.hold_time = hold_action, hold_time
        self.repeat, self.repeat_interval = repeat, repeat_interval
        self.active_level = 0 if pull == "up" else 1
        self._pressed_at: float | None = None
        self._next_repeat = 0.0
        self._hold_fired = False

    def on_level(self, level: int, now: float) -> None:
        pressed = level == self.active_level
        if pressed and self._pressed_at is None:
            self._pressed_at, self._hold_fired = now, False
            if self.repeat and self.action:
                self.emit(self.action, self.args)
                self._next_repeat = now + self.repeat_interval * 2  # longer first pause
            elif not self.hold_action and self.action:
                self.emit(self.action, self.args)
        elif not pressed and self._pressed_at is not None:
            if self.hold_action and not self._hold_fired and self.action:
                self.emit(self.action, self.args)  # short press (no action: only the hold counts)
            self._pressed_at = None

    def tick(self, now: float) -> None:
        if self._pressed_at is None:
            return
        if self.repeat and self.action and now >= self._next_repeat:
            self.emit(self.action, self.args)
            self._next_repeat = now + self.repeat_interval
        if self.hold_action and not self._hold_fired and now - self._pressed_at >= self.hold_time:
            self._hold_fired = True
            self.emit(self.hold_action, {})


class RotaryEncoder:
    """Quadrature decoder; one action per detent (4 valid transitions)."""

    _STEP = {(0b00, 0b01): 1, (0b01, 0b11): 1, (0b11, 0b10): 1, (0b10, 0b00): 1,
             (0b00, 0b10): -1, (0b10, 0b11): -1, (0b11, 0b01): -1, (0b01, 0b00): -1}

    def __init__(self, emit: Emit, *, cw: str, ccw: str,
                 cw_args: dict[str, Any] | None = None,
                 ccw_args: dict[str, Any] | None = None) -> None:
        self.emit, self.cw, self.ccw = emit, cw, ccw
        self.cw_args, self.ccw_args = cw_args or {}, ccw_args or {}
        self.a = self.b = 1
        self._state = 0b11
        self._acc = 0

    def on_level(self, which: str, level: int) -> None:
        if which == "a":
            self.a = level
        else:
            self.b = level
        new = (self.a << 1) | self.b
        step = self._STEP.get((self._state, new), 0)
        self._state = new
        self._acc += step
        if self._acc >= 4:
            self._acc = 0
            self.emit(self.cw, self.cw_args)
        elif self._acc <= -4:
            self._acc = 0
            self.emit(self.ccw, self.ccw_args)


class GpioBackend(Protocol):
    def read_edges(self, timeout: float) -> list[tuple[int, int]]:
        """Return (pin, level) pairs seen within ``timeout`` seconds."""

    def set_output(self, pin: int, value: bool) -> None: ...
    def close(self) -> None: ...


class GpiodBackend:
    """libgpiod v2 bindings: apt package python3-libgpiod 2.x (Raspberry Pi OS Trixie,
    or Bookworm with bookworm-backports). Bookworm's own 1.6.x has a different API."""

    def __init__(self, chip: str, inputs: dict[int, str], outputs: list[int]) -> None:
        import gpiod
        from gpiod.line import Bias, Direction, Edge, Value

        self._gpiod, self._Value = gpiod, Value
        self._in = self._out = None
        if inputs:
            bias = {"up": Bias.PULL_UP, "down": Bias.PULL_DOWN, "none": Bias.DISABLED}
            self._in = gpiod.request_lines(chip, consumer="jukebox", config={
                pin: gpiod.LineSettings(direction=Direction.INPUT, bias=bias[pull],
                                        edge_detection=Edge.BOTH,
                                        debounce_period=timedelta(milliseconds=3))
                for pin, pull in inputs.items()})
        if outputs:
            self._out = gpiod.request_lines(chip, consumer="jukebox", config={
                pin: gpiod.LineSettings(direction=Direction.OUTPUT,
                                        output_value=Value.INACTIVE)
                for pin in outputs})

    def read_edges(self, timeout: float) -> list[tuple[int, int]]:
        if self._in is None:
            time.sleep(timeout)
            return []
        if not self._in.wait_edge_events(timedelta(seconds=timeout)):
            return []
        rising = self._gpiod.EdgeEvent.Type.RISING_EDGE
        return [(e.line_offset, 1 if e.event_type is rising else 0)
                for e in self._in.read_edge_events()]

    def set_output(self, pin: int, value: bool) -> None:
        if self._out is not None:
            self._out.set_value(pin, self._Value.ACTIVE if value else self._Value.INACTIVE)

    def close(self) -> None:
        for req in (self._in, self._out):
            if req is not None:
                req.release()


class Led:
    def __init__(self, backend: GpioBackend, pin: int) -> None:
        self._backend, self.pin = backend, pin

    def set(self, on: bool) -> None:
        self._backend.set_output(self.pin, on)

    def on(self) -> None:
        self.set(True)

    def off(self) -> None:
        self.set(False)


class GpioInputs(threading.Thread):
    """Builds devices from ``[[gpio.*]]`` tables and runs the edge loop."""

    def __init__(self, bus: EventBus, gpio_cfg: dict[str, Any],
                 backend_factory: Callable[[str, dict[int, str], list[int]], GpioBackend] = GpiodBackend,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(name="gpio", daemon=True)
        self.bus, self._clock = bus, clock
        self._halt = threading.Event()
        self._buttons: dict[int, Button] = {}
        self._encoders: dict[int, tuple[RotaryEncoder, str]] = {}
        self.leds: dict[str, Led] = {}
        pulls: dict[int, str] = {}
        led_pins: list[int] = []

        def emit(name: str, args: dict[str, Any]) -> None:
            self.bus.post("action", name=name, args=args)

        for c in gpio_cfg.get("button", []):
            pulls[c["pin"]] = c.get("pull", "up")
            self._buttons[c["pin"]] = Button(
                emit, pull=c.get("pull", "up"), action=c.get("action"), args=c.get("args"),
                hold_action=c.get("hold_action"), hold_time=c.get("hold_time", 1.0),
                repeat=c.get("repeat", False))
        for c in gpio_cfg.get("rotary", []):
            enc = RotaryEncoder(emit, cw=c["cw"], ccw=c["ccw"],
                                cw_args=c.get("cw_args"), ccw_args=c.get("ccw_args"))
            for key, which in (("pin_a", "a"), ("pin_b", "b")):
                pulls[c[key]] = c.get("pull", "up")
                self._encoders[c[key]] = (enc, which)
        for c in gpio_cfg.get("led", []):
            led_pins.append(c["pin"])
        self.backend = backend_factory(gpio_cfg.get("chip", "/dev/gpiochip0"), pulls, led_pins)
        for c in gpio_cfg.get("led", []):
            self.leds[c["name"]] = Led(self.backend, c["pin"])

    def stop(self) -> None:
        self._halt.set()

    def step(self, timeout: float = 0.05) -> None:
        """One loop iteration; separate so tests can drive it."""
        for pin, level in self.backend.read_edges(timeout):
            if pin in self._buttons:
                self._buttons[pin].on_level(level, self._clock())
            elif pin in self._encoders:
                enc, which = self._encoders[pin]
                enc.on_level(which, level)
        now = self._clock()
        for button in self._buttons.values():
            button.tick(now)

    def run(self) -> None:
        try:
            while not self._halt.is_set():
                self.step()
        except Exception:
            log.exception("GPIO loop crashed")
        finally:
            self.backend.close()
