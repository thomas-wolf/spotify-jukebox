"""Validated settings of the [display] section."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import ConfigError
from .layout import ROTATIONS, logical_size, visible_rect

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class DisplaySettings:
    width: int = 240                # native size of the panel, portrait
    height: int = 320
    rotation: int = 90
    spi_bus: int = 0
    spi_device: int = 0
    spi_speed_hz: int = 32_000_000
    dc: int = 25
    reset: int | None = 17
    backlight: int | None = None
    gpio_chip: str = "/dev/gpiochip0"
    margin_left: int = 0
    margin_top: int = 0
    margin_right: int = 0
    margin_bottom: int = 0
    layout: str = "auto"
    cover_side: str = "left"
    cover_fit: str = "contain"
    background: str = "average"
    font: str = ""
    title_size: int = 22
    artist_size: int = 16
    idle_image: str = ""            # picture for boot and "nothing playing" (empty: blank screen)
    idle_fit: str = "cover"         # cover: fill and crop, contain: whole picture visible
    idle_on_pause: bool = False     # also show it while paused

    @classmethod
    def from_section(cls, d: dict) -> "DisplaySettings":
        m = d.get("margins", {}) or {}
        s = cls(
            width=int(d.get("width", 240)), height=int(d.get("height", 320)),
            rotation=int(d.get("rotation", 90)),
            spi_bus=int(d.get("spi_bus", 0)), spi_device=int(d.get("spi_device", 0)),
            spi_speed_hz=int(d.get("spi_speed_hz", 32_000_000)),
            dc=int(d.get("dc", 25)),
            reset=None if d.get("reset", 17) in (None, "", -1) else int(d.get("reset", 17)),
            backlight=None if d.get("backlight", None) in (None, "", -1) else int(d["backlight"]),
            gpio_chip=str(d.get("gpio_chip", "/dev/gpiochip0")),
            margin_left=int(m.get("left", 0)), margin_top=int(m.get("top", 0)),
            margin_right=int(m.get("right", 0)), margin_bottom=int(m.get("bottom", 0)),
            layout=str(d.get("layout", "auto")), cover_side=str(d.get("cover_side", "left")),
            cover_fit=str(d.get("cover_fit", "contain")), background=str(d.get("background", "average")),
            font=str(d.get("font", "")), title_size=int(d.get("title_size", 22)),
            artist_size=int(d.get("artist_size", 16)),
            idle_image=str(d.get("idle_image", "") or ""), idle_fit=str(d.get("idle_fit", "cover")),
            idle_on_pause=bool(d.get("idle_on_pause", False)),
        )
        s.validate()
        return s

    def validate(self) -> None:
        if self.rotation not in ROTATIONS:
            raise ConfigError(f"[display] rotation must be one of {ROTATIONS}")
        if self.width < 16 or self.height < 16:
            raise ConfigError("[display] width and height must be the panel's native size in pixels")
        if self.layout not in ("auto", "split", "cover"):
            raise ConfigError("[display] layout must be auto, split or cover")
        if self.cover_side not in ("left", "right", "top", "bottom"):
            raise ConfigError("[display] cover_side must be left, right, top or bottom")
        if self.cover_fit not in ("contain", "cover"):
            raise ConfigError("[display] cover_fit must be contain or cover")
        if self.idle_fit not in ("contain", "cover"):
            raise ConfigError("[display] idle_fit must be contain or cover")
        if self.background not in ("average", "blur") and not _COLOR.match(self.background):
            raise ConfigError("[display] background must be average, blur or a color like #101010")
        try:
            lw, lh = logical_size(self.width, self.height, self.rotation)
            visible_rect(lw, lh, self.margin_left, self.margin_top, self.margin_right, self.margin_bottom)
        except ValueError as exc:
            raise ConfigError(f"[display] {exc}") from exc

    @property
    def logical(self) -> tuple[int, int]:
        return logical_size(self.width, self.height, self.rotation)
