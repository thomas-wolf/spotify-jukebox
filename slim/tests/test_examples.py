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
    reserved = {4, 17, 14, 15, 8, 9, 10, 11, 18, 19, 21}
    assert not reserved & set(_pins(cfg))
    assert {cfg["display"]["dc"], cfg["display"]["reset"]} == {22, 25}
