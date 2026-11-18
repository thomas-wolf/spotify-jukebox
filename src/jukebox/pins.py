"""Pin check: who uses which BCM pin on this box, and what collides.

Pure function of the configuration, so it runs without hardware
(``jukebox pins``) and in the tests for every ``boxes/*/config.toml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Config

I2S_PINS = {18: "CLK", 19: "FS", 20: "DIN", 21: "DOUT"}
USABLE = range(2, 28)  # 0 and 1 are the HAT EEPROM, 28+ do not exist on the 40-pin header


@dataclass(frozen=True)
class Problem:
    level: str  # "error" or "warning"
    message: str


@dataclass
class PinReport:
    claims: dict[int, list[str]]
    problems: list[Problem]

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.level == "error"]


def check_pins(cfg: Config) -> PinReport:
    claims: dict[int, list[str]] = {}       # pins assigned by the configuration
    hardware: dict[int, str] = {}           # pins taken by a bus or an overlay
    problems: list[Problem] = []

    def claim(pin: Any, what: str) -> None:
        if not isinstance(pin, int) or isinstance(pin, bool):
            problems.append(Problem("error", f"{what}: pin must be an integer, got {pin!r}"))
            return
        claims.setdefault(pin, []).append(what)

    gpio = cfg.section("gpio")
    for b in cfg.hardware_list("gpio", "button"):
        claim(b.get("pin"), f"button {b.get('action') or b.get('hold_action') or '?'}")
    for r in cfg.hardware_list("gpio", "rotary"):
        claim(r.get("pin_a"), "rotary A")
        claim(r.get("pin_b"), "rotary B")
    for led in cfg.hardware_list("gpio", "led"):
        claim(led.get("pin"), f"LED {led.get('name', '?')}")

    disp = cfg.section("display")
    boot = cfg.section("boot")
    if disp.get("enabled"):
        claim(disp.get("dc", 25), "display DC")
        claim(disp.get("reset", 17), "display RESET")
        if disp.get("backlight") is not None:
            claim(disp["backlight"], "display backlight")
        cs = {0: 8, 1: 7}.get(int(disp.get("spi_device", 0)), 8)
        for pin, name in ((10, "MOSI"), (9, "MISO"), (11, "SCLK"), (cs, "CS")):
            hardware[pin] = f"SPI display {name}"
        if not boot.get("spi"):
            problems.append(Problem("warning", "[display] is enabled but [boot] spi is not true"))
    if cfg.section("readers").get("rdm6300", {}).get("enabled"):
        hardware[14] = "UART TX (RDM6300)"
        hardware[15] = "UART RX (RDM6300)"
    if cfg.section("adc").get("enabled") or boot.get("i2c"):
        hardware[2] = "I2C SDA"
        hardware[3] = "I2C SCL"
    if str(boot.get("audio", "")).startswith("hifiberry"):
        for pin, name in I2S_PINS.items():
            if pin == 20 and boot.get("i2s_free_gpio20"):
                continue   # jukebox-i2s-free-gpio20 leaves the data-in pin alone (BCM2835 family)
            hardware[pin] = f"I2S {name} (audio overlay)"
    elif boot.get("audio") == "pirate-audio":
        hardware[25] = "pirate-audio amplifier"
    if boot.get("power") == "onoff-shim":
        hardware[4] = "OnOff SHIM power-off signal"
    for pin, why in gpio.get("reserved", {}).items():
        if str(pin).isdigit():
            hardware[int(pin)] = f"reserved: {why}"

    for pin, whats in sorted(claims.items()):
        if pin not in USABLE:
            problems.append(Problem("error", f"GPIO {pin} ({', '.join(whats)}) is not usable on the header"))
        if len(whats) > 1:
            problems.append(Problem("error", f"GPIO {pin} is used twice: {', '.join(whats)}"))
        if pin in hardware:
            what = ", ".join(whats)
            what = ", ".join(whats)
            note = " (on a Pi 4 with the hifiberry overlay libgpiod refuses it: Invalid argument)" \
                if pin == 20 and hardware[pin].startswith("I2S") else ""
            problems.append(Problem("error", f"GPIO {pin} ({what}) collides with {hardware[pin]}{note}"))
        elif pin in (2, 3):
            problems.append(Problem(
                "warning", f"GPIO {pin} ({', '.join(whats)}) has a fixed pull-up on the Pi "
                           "and is the I2C bus; fine as long as I2C stays off"))
    return PinReport(claims, problems)


def format_report(report: PinReport, cfg: Config) -> str:
    lines = ["BCM  used by"]
    for pin in sorted(report.claims):
        lines.append(f"{pin:>3}  {', '.join(report.claims[pin])}")
    lines.append("")
    if not report.problems:
        lines.append("No conflicts.")
    for p in report.problems:
        lines.append(f"{p.level.upper():8} {p.message}")
    return "\n".join(lines)
