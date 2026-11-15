from pathlib import Path

import pytest

from jukebox.config import load_config
from jukebox.pins import check_pins

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = sorted([*ROOT.glob("boxes/*/config.toml"), ROOT / "examples" / "config.toml"])


def cfg_from(tmp_path, text):
    p = tmp_path / "c.toml"
    p.write_text(text)
    return load_config(p)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: str(p.relative_to(ROOT)))
def test_shipped_configs_have_no_pin_errors(path):
    assert check_pins(load_config(path)).errors == []


def test_duplicate_pin(tmp_path):
    cfg = cfg_from(tmp_path, '[[gpio.button]]\npin = 5\naction = "next"\n[[gpio.led]]\nname = "a"\npin = 5\n')
    assert any("used twice" in p.message for p in check_pins(cfg).errors)


def test_collision_with_bus_pins(tmp_path):
    cfg = cfg_from(tmp_path, '[readers.rdm6300]\nenabled = true\n[boot]\naudio = "hifiberry-miniamp"\n'
                             '[[gpio.button]]\npin = 14\naction = "next"\n[[gpio.button]]\npin = 18\naction = "prev"\n')
    msgs = [p.message for p in check_pins(cfg).errors]
    assert any("UART" in m for m in msgs) and any("I2S" in m for m in msgs)


def test_gpio20_is_only_a_warning_and_reserved_pins_count(tmp_path):
    cfg = cfg_from(tmp_path, '[boot]\naudio = "hifiberry-miniamp"\n[gpio.reserved]\n4 = "SHIM"\n'
                             '[[gpio.button]]\npin = 20\naction = "prev"\n[[gpio.button]]\npin = 4\naction = "next"\n')
    r = check_pins(cfg)
    assert any("GPIO 20" in p.message for p in r.problems if p.level == "warning")
    assert any("GPIO 4" in p.message and "SHIM" in p.message for p in r.errors)


def test_display_pins_and_bad_pin(tmp_path):
    cfg = cfg_from(tmp_path, '[display]\nenabled = true\ndc = 10\nreset = 40\n')
    msgs = [p.message for p in check_pins(cfg).errors]
    assert any("MOSI" in m for m in msgs) and any("not usable" in m for m in msgs)


def test_onoff_shim_reserves_gpio4(tmp_path):
    cfg = cfg_from(tmp_path, '[boot]\npower = "onoff-shim"\n[[gpio.button]]\npin = 4\naction = "next"\n')
    assert any("SHIM" in p.message for p in check_pins(cfg).errors)
