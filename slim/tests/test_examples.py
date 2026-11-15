import tomllib
from pathlib import Path

EX = Path(__file__).resolve().parent.parent / "examples"


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
    cfg = tomllib.loads((EX / "pferdeanhaenger.toml").read_text())
    reserved = {4, 14, 15, 8, 9, 10, 11, 18, 19, 21}  # 17 is the SHIM button, on purpose
    assert not reserved & set(_pins(cfg))
    assert {cfg["display"]["dc"], cfg["display"]["reset"]} == {22, 25}


def test_pferdeanhaenger_hook_registers_action():
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("hp", EX / "hooks_pferdeanhaenger.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = SimpleNamespace(actions={}, cfg=SimpleNamespace(section=lambda n: {}))
    mod.setup(app)
    assert "pferdesound" in app.actions
    app.actions["pferdesound"]()  # folder missing: only logs a warning


def test_hold_only_button_ignores_short_press():
    from jukebox.inputs.gpio import Button

    sent = []
    b = Button(lambda n, a: sent.append(n), hold_action="shutdown", hold_time=2.0)
    b.on_level(0, 0.0); b.on_level(1, 0.5)
    assert sent == []
    b.on_level(0, 1.0); b.tick(3.1); b.on_level(1, 3.2)
    assert sent == ["shutdown"]
