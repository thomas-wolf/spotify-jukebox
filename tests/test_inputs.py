import pytest

from jukebox.events import EventBus
from jukebox.inputs.adc import VolumeKnob, to_percent
from jukebox.inputs.gpio import Button, GpioInputs, RotaryEncoder
from jukebox.inputs.rdm6300 import FrameBuffer, parse_frame
from jukebox.inputs.usb_reader import KeyAssembler


# -- USB reader -------------------------------------------------------------
def test_key_assembler_builds_card_on_enter():
    a = KeyAssembler()
    out = [a.feed(k) for k in ("KEY_0", "KEY_4", "KEY_A", "KEY_LEFTSHIFT", "KEY_KP7", "KEY_ENTER")]
    assert out[:-1] == [None] * 5 and out[-1] == "04a7"   # lower case, like v2
    assert a.feed("KEY_ENTER") is None             # empty line gives no card


# -- RDM6300 ----------------------------------------------------------------
def frame(tag_hex: str, checksum: int | None = None) -> bytes:
    tag = bytes.fromhex(tag_hex)
    if checksum is None:
        checksum = 0
        for b in tag:
            checksum ^= b
    return b"\x02" + tag_hex.encode() + f"{checksum:02X}".encode() + b"\x03"


def test_rdm_formats_match_phoniebox_v2():
    # vectors from the v2 reader: raw 070067315809 / dec 0006762840 / float 103,12632
    f = frame("0700673158")
    assert f[1:13] == b"070067315809"
    assert parse_frame(f) == "070067315809"                 # default = raw, as in v2
    assert parse_frame(f, "raw") == "070067315809"
    assert parse_frame(f, "dec") == "0006762840"
    assert parse_frame(f, "float") == "103,12632"
    assert parse_frame(f, "hex") == "0700673158"
    with pytest.raises(ValueError):
        parse_frame(f, "octal")


@pytest.mark.parametrize("bad", [frame("0415026F42", 0x00), b"\x02" + b"ZZ" * 5 + b"00\x03",
                                 b"short", b"\x01" + frame("0415026F42")[1:]])
def test_rdm_rejects_bad_frames(bad):
    assert parse_frame(bad) is None


def test_rdm_buffer_resyncs_after_garbage_and_split_reads():
    buf = FrameBuffer()
    f = frame("0415026F42")
    out = buf.feed(b"\x00\xff" + f[:5])
    out += buf.feed(f[5:] + f)
    assert out == [f, f]


# -- GPIO ---------------------------------------------------------------------
class Rec:
    def __init__(self):
        self.out = []

    def __call__(self, name, args):
        self.out.append((name, args))


def test_simple_button_fires_on_press_only():
    r = Rec()
    b = Button(r, action="next")
    b.on_level(0, 0.0)
    b.on_level(0, 0.1)           # still pressed, no second event
    b.on_level(1, 0.2)
    assert r.out == [("next", {})]


def test_button_pull_down_polarity():
    r = Rec()
    b = Button(r, pull="down", action="next")
    b.on_level(0, 0.0)
    assert r.out == []
    b.on_level(1, 0.1)
    assert r.out == [("next", {})]


def test_button_short_vs_hold():
    r = Rec()
    b = Button(r, action="play_pause", hold_action="shutdown", hold_time=2.0)
    b.on_level(0, 0.0); b.tick(0.5); b.on_level(1, 0.6)         # short press
    assert r.out == [("play_pause", {})]
    r.out.clear()
    b.on_level(0, 10.0); b.tick(11.0); b.tick(12.1); b.tick(13.0); b.on_level(1, 13.1)
    assert r.out == [("shutdown", {})]                           # once, and no short press


def test_button_repeat_while_held():
    r = Rec()
    b = Button(r, action="volume_up", repeat=True, repeat_interval=0.5)
    b.on_level(0, 0.0)           # fires at once
    b.tick(0.5)                  # first repeat waits twice the interval
    assert len(r.out) == 1
    for t in (1.0, 1.5, 2.0):    # then every interval
        b.tick(t)
    assert len(r.out) == 4
    b.on_level(1, 2.1)
    b.tick(9.0)
    assert len(r.out) == 4       # nothing after release


def feed_cw(enc, detents):
    for _ in range(detents):
        for a, b in ((1, 0), (0, 0), (0, 1), (1, 1)):
            enc.on_level("a", a); enc.on_level("b", b)


def feed_ccw(enc, detents):
    for _ in range(detents):
        for a, b in ((0, 1), (0, 0), (1, 0), (1, 1)):
            enc.on_level("a", a); enc.on_level("b", b)


def test_rotary_one_action_per_detent():
    r = Rec()
    enc = RotaryEncoder(r, cw="volume_up", ccw="volume_down")
    feed_cw(enc, 3)
    feed_ccw(enc, 2)
    assert [n for n, _ in r.out] == ["volume_up"] * 3 + ["volume_down"] * 2


def test_rotary_ignores_contact_bounce():
    r = Rec()
    enc = RotaryEncoder(r, cw="volume_up", ccw="volume_down")
    for _ in range(10):                      # bounce on one channel only
        enc.on_level("a", 0); enc.on_level("a", 1)
    assert r.out == []


class FakeBackend:
    def __init__(self, chip, inputs, outputs):
        self.inputs, self.outputs = inputs, outputs
        self.pending, self.set = [], []

    def read_edges(self, timeout):
        out, self.pending = self.pending, []
        return out

    def set_output(self, pin, value):
        self.set.append((pin, value))

    def close(self):
        pass


def test_gpio_inputs_wiring_from_config():
    bus = EventBus()
    cfg = {"button": [{"pin": 26, "action": "next"}, {"pin": 16, "action": "volume_up", "repeat": True}],
           "rotary": [{"pin_a": 22, "pin_b": 23, "cw": "volume_up", "ccw": "volume_down"}],
           "led": [{"name": "status", "pin": 14}]}
    t = [0.0]
    g = GpioInputs(bus, cfg, backend_factory=FakeBackend, clock=lambda: t[0])
    assert g.backend.inputs == {26: "up", 16: "up", 22: "up", 23: "up"}
    assert g.backend.outputs == [14]
    g.backend.pending = [(26, 0), (26, 1)]
    g.step(0)
    g.leds["status"].on()
    assert g.backend.set == [(14, True)]
    seen = []
    bus.subscribe("*", seen.append)
    bus.drain(lambda e: None)
    assert [(e.name, e.data["name"]) for e in seen] == [("action", "next")]


# -- ADC ----------------------------------------------------------------------
def test_to_percent_clamps_and_scales():
    assert to_percent(0) == 0
    assert to_percent(-50) == 0
    assert to_percent(13200) == 50
    assert to_percent(99999) == 100
    with pytest.raises(ValueError):
        to_percent(1, 0)


def test_knob_deadband_and_no_event_at_boot():
    bus = EventBus()
    values = iter([13200, 13300, 13200 + 1000, 0])
    knob = VolumeKnob(bus, lambda: next(values), deadband=2)
    for _ in range(4):
        knob.step()
    seen = []
    bus.subscribe("*", seen.append)
    bus.drain(lambda e: None)
    sent = [e.data["args"]["value"] for e in seen]
    assert sent == [54, 0]       # first reading silent, +0.4 % ignored, then two real moves
