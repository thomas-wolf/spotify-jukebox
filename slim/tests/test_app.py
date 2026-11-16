import pytest

from fakes import Clock, FakePlayer
from jukebox import events as ev
from jukebox.app import App
from jukebox.config import Card, load_config
from jukebox.events import EventBus
from jukebox.players import PlayerRouter


@pytest.fixture
def env(tmp_path):
    cfg = load_config(None)
    spotify, local = FakePlayer("spotify"), FakePlayer("local")
    router = PlayerRouter({"spotify": spotify, "folder": local})
    bus, clock, ran = EventBus(), Clock(), []
    cards = {
        "A": Card("A", "Bedtime", play="spotify:playlist:a"),
        "B": Card("B", "Book", play="folder:books/x"),
        "VOL": Card("VOL", action="volume_up"),
        "SEEK": Card("SEEK", action="seek_forward", args={"seconds": 30}),
    }
    app = App(cfg, cards, router, bus, clock=clock, run=ran.append)
    seen = []
    bus.subscribe("*", lambda e: seen.append(e))

    def feed(event_name, /, **data):
        bus.post(event_name, **data)
        bus.drain(app.handle)

    return app, feed, spotify, local, seen, clock, ran


def names(seen):
    return [e.name for e in seen]


def test_card_plays_and_emits(env):
    app, feed, spotify, _, seen, *_ = env
    feed(ev.CARD, id="A")
    assert ("play", "spotify:playlist:a") in spotify.calls
    assert ev.PLAYING in names(seen)


def test_unknown_card_event(env):
    _, feed, _, _, seen, *_ = env
    feed(ev.CARD, id="ZZZ")
    unknown = [e for e in seen if e.name == ev.CARD_UNKNOWN]
    assert unknown and unknown[0].data["id"] == "ZZZ"


def test_same_card_toggles_after_delay_but_not_before(env):
    app, feed, spotify, _, _, clock, _ = env
    feed(ev.CARD, id="A")
    clock.now += 1
    feed(ev.CARD, id="A")                     # reader repeat -> ignored
    assert ("pause",) not in spotify.calls
    clock.now += 10
    feed(ev.CARD, id="A")                     # real second swipe -> pause
    assert ("pause",) in spotify.calls
    clock.now += 10
    feed(ev.CARD, id="A")
    assert ("resume",) in spotify.calls


def test_switching_card_stops_other_backend(env):
    _, feed, spotify, local, *_ = env
    feed(ev.CARD, id="A")
    feed(ev.CARD, id="B")
    assert ("stop",) in spotify.calls
    assert ("play", "folder:books/x") in local.calls


def test_action_card_with_args(env):
    _, feed, spotify, *_ = env
    feed(ev.CARD, id="A")
    feed(ev.CARD, id="SEEK")
    assert ("seek", 30) in spotify.calls


def test_volume_clamped_to_max_and_muting(env):
    app, feed, spotify, _, seen, *_ = env
    app.start()
    app.bus.drain(app.handle)
    for _ in range(30):
        feed(ev.CARD, id="VOL")
    assert app.players.volume == app.max_volume == 80
    feed(ev.ACTION, name="mute")
    assert app.players.volume == 0
    feed(ev.ACTION, name="mute")
    assert app.players.volume == 80
    feed(ev.ACTION, name="volume_set", args={"value": 500})
    assert app.players.volume == 80


def test_player_error_becomes_event_not_crash(env):
    app, feed, spotify, _, seen, *_ = env
    spotify.fail = True
    feed(ev.CARD, id="A")
    assert ev.ERROR in names(seen)


def test_nothing_loaded_is_an_error_event(env):
    _, feed, _, _, seen, *_ = env
    feed(ev.ACTION, name="next")
    assert ev.ERROR in names(seen)


def test_unknown_action_and_bad_args_do_not_raise(env):
    _, feed, *_ = env
    feed(ev.ACTION, name="dance")
    feed(ev.ACTION, name="volume_up", args={"nope": 1})


def test_shutdown_runs_command(env):
    _, feed, _, _, seen, _, ran = env
    feed(ev.ACTION, name="shutdown")
    assert ran == [["systemctl", "poweroff"]]
    assert ev.SHUTDOWN in names(seen)


def test_card_lookup_ignores_case(env):
    _, feed, spotify, *_ = env
    feed(ev.CARD, id="a")                      # configured as "A"
    assert ("play", "spotify:playlist:a") in spotify.calls


def test_same_card_restart_plays_from_the_beginning(env):
    app, feed, spotify, _, seen, clock, _ = env
    app.cfg.raw["cards"]["same_card"] = "restart"
    feed(ev.CARD, id="A")
    clock.now += 10
    feed(ev.CARD, id="A")
    assert spotify.calls.count(("play", "spotify:playlist:a")) == 2
    assert ("pause",) not in spotify.calls
