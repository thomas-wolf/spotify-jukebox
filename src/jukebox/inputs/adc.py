"""Potentiometer on an ADS1115 (I2C), used as a volume knob.

Talks to /dev/i2c-N with plain ioctl/read/write, so no smbus package is needed.
Single-shot conversions, +-4.096 V range, 128 SPS.
"""

from __future__ import annotations

import fcntl
import logging
import os
import threading
import time
from typing import Callable

from ..events import EventBus

log = logging.getLogger(__name__)

I2C_SLAVE = 0x0703
REG_CONVERSION, REG_CONFIG = 0x00, 0x01
_MUX = {0: 0x4000, 1: 0x5000, 2: 0x6000, 3: 0x7000}  # single-ended AINx vs GND
_OS_START = 0x8000
_PGA_4V096 = 0x0200
_MODE_SINGLE = 0x0100
_DR_128 = 0x0080
_COMP_OFF = 0x0003


def to_percent(raw: int, full_scale: int = 26400) -> int:
    """Map a raw reading to 0..100.

    ``full_scale`` is the raw value at the top of the pot. At +-4.096 V a pot
    wired to 3.3 V reads about 26400 (3.3 / 4.096 * 32767). Calibrate per box
    with ``jukebox adc-check`` and put the value in config.toml.
    """
    if full_scale <= 0:
        raise ValueError("full_scale must be positive")
    return max(0, min(100, round(max(raw, 0) * 100 / full_scale)))


class Ads1115:
    def __init__(self, bus: int = 1, address: int = 0x48) -> None:
        self._fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
        fcntl.ioctl(self._fd, I2C_SLAVE, address)

    def read_raw(self, channel: int = 0) -> int:
        cfg = (_OS_START | _MUX[channel] | _PGA_4V096 | _MODE_SINGLE | _DR_128 | _COMP_OFF)
        os.write(self._fd, bytes([REG_CONFIG, cfg >> 8, cfg & 0xFF]))
        time.sleep(0.009)  # 128 SPS -> ~7.8 ms per conversion
        os.write(self._fd, bytes([REG_CONVERSION]))
        data = os.read(self._fd, 2)
        value = int.from_bytes(data, "big", signed=True)
        return value

    def close(self) -> None:
        os.close(self._fd)


class VolumeKnob(threading.Thread):
    """Posts volume_set only when the knob moved by >= ``deadband`` percent."""

    def __init__(self, bus: EventBus, read: Callable[[], int], *, full_scale: int = 26400,
                 deadband: int = 2, interval: float = 0.05) -> None:
        super().__init__(name="volume-knob", daemon=True)
        self.bus, self._read = bus, read
        self.full_scale, self.deadband, self.interval = full_scale, deadband, interval
        self._halt = threading.Event()
        self._last: int | None = None

    def stop(self) -> None:
        self._halt.set()

    def step(self) -> None:
        percent = to_percent(self._read(), self.full_scale)
        if self._last is None or abs(percent - self._last) >= self.deadband:
            first = self._last is None
            self._last = percent
            if not first:  # do not override the start volume at boot
                self.bus.post("action", name="volume_set", args={"value": percent})

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.step()
            except OSError:
                log.warning("ADC read failed", exc_info=True)
                time.sleep(1)
            time.sleep(self.interval)
