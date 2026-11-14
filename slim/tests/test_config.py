import pytest

from jukebox.config import ConfigError, add_card, load_cards, load_config


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_defaults_and_override(tmp_path):
    p = write(tmp_path, "config.toml", "[audio]\nmax_volume = 60\n")
    cfg = load_config(p)
    assert cfg.section("audio")["max_volume"] == 60
    assert cfg.section("audio")["volume_step"] == 5      # default kept
    assert cfg.section("spotify")["api_url"].startswith("http://127.0.0.1")


@pytest.mark.parametrize("text", ["[audio]\nmax_volume = 150\n", "[audio]\nstart_volume = 'x'\n",
                                  "[cards]\nsame_card = 'dance'\n"])
def test_invalid_values_rejected(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "c.toml", text))


def test_missing_and_broken_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "bad.toml", "[audio\n"))


def test_cards_roundtrip(tmp_path):
    p = tmp_path / "cards.toml"
    add_card(p, "123", name='Der "Mond"', play="spotify:playlist:abc")
    add_card(p, "456", action="stop")
    cards = load_cards(p)
    assert cards["123"].play == "spotify:playlist:abc"
    assert cards["123"].name == 'Der "Mond"'
    assert cards["456"].action == "stop"
    with pytest.raises(ConfigError):
        add_card(p, "123", play="spotify:x")           # duplicate


def test_card_needs_exactly_one_target(tmp_path):
    for body in ('name = "x"', 'play = "a"\naction = "b"'):
        p = write(tmp_path, "cards.toml", f'[cards."1"]\n{body}\n')
        with pytest.raises(ConfigError):
            load_cards(p)


def test_missing_cards_file_is_empty(tmp_path):
    assert load_cards(tmp_path / "none.toml") == {}
