import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
BOXES = ROOT / "boxes"


def _pins(cfg):
    g = cfg.get("gpio", {})
    pins = [b["pin"] for b in g.get("button", [])] + [l["pin"] for l in g.get("led", [])]
    for r in g.get("rotary", []):
        pins += [r["pin_a"], r["pin_b"]]
    return pins


def test_examples_parse_and_pins_are_unique():
    for f in EX.glob("*.toml"):
        pins = _pins(tomllib.loads(f.read_text()))
        assert len(pins) == len(set(pins)), f.name


def test_pferdeanhaenger_avoids_reserved_pins():
    cfg = tomllib.loads((BOXES / "pferdeanhaenger" / "config.toml").read_text())
    reserved = {4, 14, 15, 8, 9, 10, 11, 18, 19, 21}  # 17 is the SHIM button, on purpose
    assert not reserved & set(_pins(cfg))
    assert {cfg["display"]["dc"], cfg["display"]["reset"]} == {22, 25}


def test_pferdeanhaenger_hook_registers_action():
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("hp", BOXES / "pferdeanhaenger" / "hooks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = SimpleNamespace(actions={}, cfg=SimpleNamespace(section=lambda n: {}))
    mod.setup(app)
    assert "pferdesound" in app.actions and "motor" in app.actions
    app.actions["pferdesound"]()  # folder missing: only logs a warning
    app.actions["motor"]()        # file missing: only logs a warning


def test_pferdeanhaenger_motor_button_is_gpio2_and_plays_motor(tmp_path):
    import importlib.util
    from types import SimpleNamespace
    cfg = tomllib.loads((BOXES / "pferdeanhaenger" / "config.toml").read_text())
    assert {"pin": 2, "action": "motor"}.items() <= next(b for b in cfg["gpio"]["button"] if b["pin"] == 2).items()
    assert not any(l["pin"] == 2 for l in cfg["gpio"]["led"])        # GPIO 2 is an input now
    spec = importlib.util.spec_from_file_location("hp", BOXES / "pferdeanhaenger" / "hooks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "motor.mp3").write_text("x")
    import time
    for playing, expected in ((True, ["pause", "resume"]), (False, [])):
        done = []
        app = SimpleNamespace(actions={}, do_action=done.append, players=SimpleNamespace(is_playing=lambda p=playing: p),
                              cfg=SimpleNamespace(path=tmp_path / "config.toml",
                                                  section=lambda n: {"command": ["true"]} if n == "motor" else {}))
        mod.setup(app)
        app.actions["motor"]()
        for _ in range(50):
            if done == expected:
                break
            time.sleep(0.05)
        assert done == expected                                       # pause, sound, resume; nothing if it was silent


def test_hold_only_button_ignores_short_press():
    from jukebox.inputs.gpio import Button

    sent = []
    b = Button(lambda n, a: sent.append(n), hold_action="shutdown", hold_time=2.0)
    b.on_level(0, 0.0); b.on_level(1, 0.5)
    assert sent == []
    b.on_level(0, 1.0); b.tick(3.1); b.on_level(1, 3.2)
    assert sent == ["shutdown"]


def test_led_with_on_is_lit_at_start():
    from jukebox.events import EventBus
    from jukebox.inputs.gpio import GpioInputs

    class Backend:
        def __init__(self, *a):
            self.out = {}
        def set_output(self, pin, on):
            self.out[pin] = on
        def read_edges(self, timeout):
            return []

    holder = {}
    def factory(*a):
        holder["b"] = Backend()
        return holder["b"]

    GpioInputs(EventBus(), {"led": [{"name": "a", "pin": 27, "on": True}, {"name": "b", "pin": 23}]}, backend_factory=factory)
    assert holder["b"].out == {27: True}


def test_local_override_file_is_merged(tmp_path):
    from jukebox.config import load_config

    (tmp_path / "config.toml").write_text('[readers.rdm6300]\nenabled = true\n[box]\nname = "x"\n')
    (tmp_path / "config.local.toml").write_text('[readers.rdm6300]\nenabled = false\n[readers.usb]\nenabled = true\ndevice_name = "RFID"\n')
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.section("readers")["rdm6300"]["enabled"] is False
    assert cfg.section("readers")["usb"]["device_name"] == "RFID"
    assert cfg.section("box")["name"] == "x"


def test_spotify_backend_is_validated(tmp_path):
    import pytest
    from jukebox.config import ConfigError, load_config
    ok = tmp_path / "a.toml"
    ok.write_text('[spotify]\nbackend = "soloist"\n')
    assert load_config(str(ok)).section("spotify")["backend"] == "soloist"
    bad = tmp_path / "b.toml"
    bad.write_text('[spotify]\nbackend = "other"\n')
    with pytest.raises(ConfigError):
        load_config(str(bad))


def test_feuerwehrv1_hook_siren_and_mute():
    import importlib.util
    import time
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("hf1", BOXES / "feuerwehrv1" / "hooks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Led:
        def __init__(self):
            self.states = []

        def set(self, on):
            self.states.append(bool(on))

    calls = []
    leds = {n: Led() for n in ("blue_left", "blue_right", "yellow")}
    playing = {"v": True}
    app = SimpleNamespace(
        actions={}, leds=leds,
        cfg=SimpleNamespace(section=lambda n: {"sound": "/nonexistent.mp3", "rounds": 2, "step": 0}),
        players=SimpleNamespace(is_playing=lambda: playing["v"]),
        do_action=lambda name, **a: calls.append(name))
    mod.setup(app)
    assert {"sirene", "alarm_mute"} <= set(app.actions)

    def wait_idle():
        deadline = time.time() + 5
        while time.time() < deadline and "resume" not in calls:
            time.sleep(0.01)

    app.actions["sirene"]()            # music playing: pause, light show, resume
    wait_idle()
    assert calls == ["pause", "resume"]
    assert leds["blue_left"].states[-1] is False and leds["blue_right"].states[-1] is False
    assert leds["yellow"].states[0] is True and leds["yellow"].states[-1] is True   # front lights: on at start and after

    calls.clear()
    app.actions["alarm_mute"]()        # muted: the red button does nothing
    app.actions["sirene"]()
    time.sleep(0.05)
    assert calls == []
    app.actions["alarm_mute"]()        # unmuted, nothing playing: no resume
    playing["v"] = False
    app.actions["sirene"]()
    time.sleep(0.2)
    assert calls == []


def test_feuerwehrv1_front_lights_can_be_switched_off():
    import importlib.util
    import time
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("hf1b", BOXES / "feuerwehrv1" / "hooks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Led:
        def __init__(self):
            self.states = []

        def set(self, on):
            self.states.append(bool(on))

    calls = []
    leds = {n: Led() for n in ("blue_left", "blue_right", "yellow")}
    app = SimpleNamespace(
        actions={}, leds=leds,
        cfg=SimpleNamespace(section=lambda n: {"sound": "/nonexistent.mp3", "rounds": 1, "step": 0,
                                               "front_lights": False}),
        players=SimpleNamespace(is_playing=lambda: True),
        do_action=lambda name, **a: calls.append(name))
    mod.setup(app)
    app.actions["sirene"]()
    deadline = time.time() + 5
    while time.time() < deadline and "resume" not in calls:
        time.sleep(0.01)
    assert leds["yellow"].states[-1] is False   # dark again after the show
