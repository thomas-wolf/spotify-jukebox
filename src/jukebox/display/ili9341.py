"""ILI9341 TFT over SPI (240x320). Needs python3-spidev and python3-libgpiod 2.x (apt).

The initialisation sequence and the rotation register values follow the Adafruit ILI9341 library as I remember
it. They have NOT been run on a real panel yet.
"""
from __future__ import annotations

import time

from .settings import DisplaySettings

# MADCTL bits
MY, MX, MV, BGR = 0x80, 0x40, 0x20, 0x08
MADCTL = {0: MX | BGR, 90: MV | BGR, 180: MY | BGR, 270: MX | MY | MV | BGR}

INIT = [
    (0xEF, b"\x03\x80\x02"), (0xCF, b"\x00\xC1\x30"), (0xED, b"\x64\x03\x12\x81"), (0xE8, b"\x85\x00\x78"),
    (0xCB, b"\x39\x2C\x00\x34\x02"), (0xF7, b"\x20"), (0xEA, b"\x00\x00"),
    (0xC0, b"\x23"), (0xC1, b"\x10"), (0xC5, b"\x3E\x28"), (0xC7, b"\x86"),
    (0x37, b"\x00"), (0x3A, b"\x55"), (0xB1, b"\x00\x18"), (0xB6, b"\x08\x82\x27"), (0xF2, b"\x00"), (0x26, b"\x01"),
    (0xE0, bytes.fromhex("0F312B0C0E084EF1370710030E0900")),
    (0xE1, bytes.fromhex("000E14031107" "31C148080F0C310F36")),
]

_HI_G = bytes(g >> 5 for g in range(256))
_LO_G = bytes((g & 0x1C) << 3 for g in range(256))
_HI_R = bytes(r & 0xF8 for r in range(256))
_LO_B = bytes(b >> 3 for b in range(256))


def rgb565(rgb: bytes) -> bytes:
    """RGB888 bytes -> RGB565, two bytes per pixel, high byte first (what the ILI9341 expects)."""
    n = len(rgb) // 3
    r, g, b = rgb[0::3], rgb[1::3], rgb[2::3]
    hi = (int.from_bytes(r.translate(_HI_R), "big") | int.from_bytes(g.translate(_HI_G), "big")).to_bytes(n, "big")
    lo = (int.from_bytes(g.translate(_LO_G), "big") | int.from_bytes(b.translate(_LO_B), "big")).to_bytes(n, "big")
    out = bytearray(2 * n)
    out[0::2], out[1::2] = hi, lo
    return bytes(out)


class ILI9341:
    def __init__(self, s: DisplaySettings, spi=None, gpio=None, sleep=time.sleep) -> None:
        self.s, self._sleep = s, sleep
        self.lw, self.lh = s.logical
        if spi is None:
            import spidev
            spi = spidev.SpiDev()
            spi.open(s.spi_bus, s.spi_device)
            spi.max_speed_hz = s.spi_speed_hz
            spi.mode = 0
        if gpio is None:
            from ..inputs.gpio import GpiodBackend
            pins = [p for p in (s.dc, s.reset, s.backlight) if p is not None]
            gpio = GpiodBackend(s.gpio_chip, {}, pins)
        self.spi, self.gpio = spi, gpio
        self._init_panel()

    def _cmd(self, command: int, data: bytes = b"") -> None:
        self.gpio.set_output(self.s.dc, False)
        self.spi.writebytes([command])
        if data:
            self.gpio.set_output(self.s.dc, True)
            self._write(data)

    def _write(self, data: bytes) -> None:
        for i in range(0, len(data), 4096):
            self.spi.writebytes2(data[i:i + 4096])

    def _init_panel(self) -> None:
        s = self.s
        if s.reset is not None:
            for level, wait in ((True, 0.005), (False, 0.02), (True, 0.15)):
                self.gpio.set_output(s.reset, level)
                self._sleep(wait)
        else:
            self._cmd(0x01)                          # software reset
            self._sleep(0.15)
        for command, data in INIT:
            self._cmd(command, data)
        self._cmd(0x36, bytes([MADCTL[s.rotation]]))
        self._cmd(0x11)                              # sleep out
        self._sleep(0.12)
        self._cmd(0x29)                              # display on
        if s.backlight is not None:
            self.gpio.set_output(s.backlight, True)
        self.show_raw(bytes(self.lw * self.lh * 2))  # black

    def show_raw(self, data565: bytes) -> None:
        w, h = self.lw, self.lh
        self._cmd(0x2A, bytes([0, 0, (w - 1) >> 8, (w - 1) & 0xFF]))
        self._cmd(0x2B, bytes([0, 0, (h - 1) >> 8, (h - 1) & 0xFF]))
        self._cmd(0x2C, data565)

    def show(self, image) -> None:
        if image.size != (self.lw, self.lh):
            raise ValueError(f"picture is {image.size}, display shows {(self.lw, self.lh)}")
        self.show_raw(rgb565(image.convert("RGB").tobytes()))

    def close(self) -> None:
        try:
            self.show_raw(bytes(self.lw * self.lh * 2))
            if self.s.backlight is not None:
                self.gpio.set_output(self.s.backlight, False)
        finally:
            self.spi.close()
            self.gpio.close()
