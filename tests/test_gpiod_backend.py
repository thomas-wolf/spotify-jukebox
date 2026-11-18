import sys
import types
from datetime import timedelta

import pytest


class FakeSettings:
    def __init__(self, **kw):
        self.kw = kw


class FakeRequest:
    def __init__(self, pins):
        self.pins = pins

    def release(self):
        pass


def install_fake_gpiod(monkeypatch, bad_with_debounce=(), bad=()):
    gpiod = types.ModuleType("gpiod")
    calls = []

    def request_lines(chip, consumer, config):
        calls.append((consumer, sorted(config)))
        for pin, st in config.items():
            if pin in bad or (pin in bad_with_debounce and "debounce_period" in st.kw):
                raise ValueError(22, "Invalid argument")
        return FakeRequest(config)

    gpiod.request_lines, gpiod.LineSettings = request_lines, FakeSettings
    line = types.ModuleType("gpiod.line")
    for name in ("Bias", "Direction", "Edge", "Value"):
        setattr(line, name, types.SimpleNamespace(PULL_UP=1, PULL_DOWN=2, DISABLED=3, INPUT=4, OUTPUT=5,
                                                  BOTH=6, INACTIVE=7, ACTIVE=8))
    monkeypatch.setitem(sys.modules, "gpiod", gpiod)
    monkeypatch.setitem(sys.modules, "gpiod.line", line)
    return calls


def test_all_good_is_one_request(monkeypatch):
    from jukebox.inputs.gpio import GpiodBackend
    calls = install_fake_gpiod(monkeypatch)
    b = GpiodBackend("/dev/gpiochip0", {5: "up", 6: "up"}, [24])
    assert calls == [("jukebox", [5, 6]), ("jukebox", [24])] and b.failed == {}


def test_bad_pin_is_skipped_not_fatal(monkeypatch):
    from jukebox.inputs.gpio import GpiodBackend
    install_fake_gpiod(monkeypatch, bad=(20,))
    b = GpiodBackend("/dev/gpiochip0", {5: "up", 20: "up"}, [])
    assert set(b.failed) == {20} and set(b._in.pins) == {5}


def test_pin_without_debounce_still_works(monkeypatch):
    from jukebox.inputs.gpio import GpiodBackend
    install_fake_gpiod(monkeypatch, bad_with_debounce=(20,))
    b = GpiodBackend("/dev/gpiochip0", {5: "up", 20: "up"}, [])
    assert b.failed == {} and set(b._in.pins) == {5, 20}
    assert "debounce_period" not in b._in.pins[20].kw and "debounce_period" in b._in.pins[5].kw
