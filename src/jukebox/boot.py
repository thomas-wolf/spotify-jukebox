"""Idempotent management of the Raspberry Pi boot config (device tree overlays).

``jukebox setup`` writes one marked block into config.txt and never touches
the rest, except for commenting out lines that conflict with the audio preset.
Re-running it replaces the block, so the result is always the same.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BEGIN = "# >>> jukebox managed block (do not edit) >>>"
END = "# <<< jukebox managed block <<<"

# Audio presets. The MiniAmp overlay and the need to switch off the on-board
# audio come from HiFiBerry's own documentation.
AUDIO_PRESETS: dict[str, dict[str, list[str]]] = {
    "hifiberry-miniamp": {
        "lines": ["dtoverlay=hifiberry-dac"],
        "comment_out": ["dtparam=audio=on"],
    },
    "hifiberry-dac": {
        "lines": ["dtoverlay=hifiberry-dac"],
        "comment_out": ["dtparam=audio=on"],
    },
    "pirate-audio": {  # as in the v2 setup script
        "lines": ["gpio=25=op,dh", "dtoverlay=hifiberry-dac"],
        "comment_out": ["dtparam=audio=on"],
    },
}


# Power hardware. The OnOff SHIM cuts the power after a halt when GPIO 4 is pulled low by gpio-poweroff.
# The button on GPIO 17 stays with the jukebox ([[gpio.button]] with hold_action = "shutdown"), so the
# gpio-shutdown overlay is deliberately not used (it would hold the pin).
POWER_PRESETS: dict[str, list[str]] = {
    "onoff-shim": ["dtoverlay=gpio-poweroff,gpiopin=4,active_low=1,input=1"],
}


class BootConfigError(ValueError):
    pass


@dataclass
class BootPlan:
    lines: list[str] = field(default_factory=list)        # unconditional lines
    by_model: dict[str, list[str]] = field(default_factory=dict)  # [pi5] -> lines
    comment_out: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)      # for modules-load.d


def plan_from_config(boot: dict[str, Any]) -> BootPlan:
    plan = BootPlan()
    preset = boot.get("audio")
    if preset:
        if preset not in AUDIO_PRESETS:
            raise BootConfigError(
                f"unknown audio preset {preset!r}; known: {', '.join(sorted(AUDIO_PRESETS))}")
        plan.lines += AUDIO_PRESETS[preset]["lines"]
        plan.comment_out += AUDIO_PRESETS[preset]["comment_out"]
    power = boot.get("power")
    if power:
        if power not in POWER_PRESETS:
            raise BootConfigError(
                f"unknown power preset {power!r}; known: {', '.join(sorted(POWER_PRESETS))}")
        plan.lines += POWER_PRESETS[power]
    if boot.get("uart"):
        plan.lines.append("enable_uart=1")
    if boot.get("spi"):
        plan.lines.append("dtparam=spi=on")
    if boot.get("i2c"):
        plan.lines.append("dtparam=i2c_arm=on")
        plan.modules.append("i2c-dev")
    for item in boot.get("extra", []):
        if isinstance(item, str):
            plan.lines.append(item)
        elif isinstance(item, dict) and "line" in item:
            model = item.get("model")
            (plan.by_model.setdefault(model, []) if model else plan.lines).append(item["line"])
        else:
            raise BootConfigError(f"bad [boot] extra entry: {item!r}")
    for line in plan.lines + [l for ls in plan.by_model.values() for l in ls]:
        if "\n" in line or not line.strip():
            raise BootConfigError(f"invalid config.txt line: {line!r}")
    plan.lines = list(dict.fromkeys(plan.lines))  # de-duplicate, keep order
    return plan


def render_block(plan: BootPlan) -> str:
    out = [BEGIN, *plan.lines]
    for model, lines in plan.by_model.items():
        out += [f"[{model}]", *lines]
    if plan.by_model:
        out.append("[all]")
    out.append(END)
    return "\n".join(out) + "\n"


def apply_plan(text: str, plan: BootPlan) -> str:
    block = re.compile(rf"^{re.escape(BEGIN)}\n.*?^{re.escape(END)}\n?", re.S | re.M)
    text = block.sub("", text)
    managed = {l for l in plan.lines} | {l for ls in plan.by_model.values() for l in ls}
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped in plan.comment_out and stripped not in managed:
            raw = "#" + raw + "  # disabled by jukebox setup"
        lines.append(raw)
    body = "\n".join(lines).rstrip("\n")
    return (body + "\n\n" if body else "") + render_block(plan)


def find_config_txt() -> Path:
    for candidate in (Path("/boot/firmware/config.txt"), Path("/boot/config.txt")):
        if candidate.exists():
            return candidate
    raise BootConfigError("no config.txt found in /boot/firmware or /boot")


def diff(old: str, new: str, name: str = "config.txt") -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"{name} (current)", f"{name} (new)"))


def write_config(path: Path, new_text: str) -> Path | None:
    """Write ``new_text``; keep a one-time backup next to the original."""
    backup = path.with_name(path.name + ".jukebox.bak")
    made = None
    if not backup.exists():
        backup.write_text(path.read_text())
        made = backup
    path.write_text(new_text)
    return made


MODULES_FILE = Path("/etc/modules-load.d/jukebox.conf")


def modules_text(plan: BootPlan) -> str | None:
    """Content of modules-load.d/jukebox.conf (None if no module is needed)."""
    if not plan.modules:
        return None
    return "# written by jukebox setup\n" + "\n".join(plan.modules) + "\n"
