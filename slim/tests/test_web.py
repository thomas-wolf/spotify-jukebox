import json
import urllib.error
import urllib.request

import pytest

from fakes import FakePlayer
from jukebox import events as ev
from jukebox.app import App
from jukebox.config import Card, load_cards, load_config
from jukebox.events import EventBus
from jukebox.players import PlayerRouter
from jukebox.web import Web, list_folders


@pytest.fixture
def web(tmp_path):
    cfg = load_config(None)
    bus = EventBus()
    app = App(cfg, {"A": Card("A", "Bedtime", play="spotify:playlist:a")},
              PlayerRouter({"spotify": FakePlayer("spotify"), "folder": FakePlayer("local")}), bus)
    root = tmp_path / "music"
    (root / "books" / "x").mkdir(parents=True)
    (root / "books" / "x" / "1.mp3").write_text("x")
    (root / "empty").mkdir()
    w = Web(app, tmp_path / "cards.toml", root, "127.0.0.1", 0)
    w.start()
    yield w, app, bus, tmp_path
    w.stop()


def call(w, method, path, body=None, ctype="application/json"):
    req = urllib.request.Request(f"http://127.0.0.1:{w.port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": ctype} if body is not None else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jcall(*a, **k):
    code, raw = call(*a, **k)
    return code, json.loads(raw)


def test_page_and_cards(web):
    w, *_ = web
    code, raw = call(w, "GET", "/")
    assert code == 200 and b"Jukebox" in raw
    code, cards = jcall(w, "GET", "/api/cards")
    assert cards[0]["id"] == "A"


def test_put_card_normalises_link_saves_and_is_live(web):
    w, app, _, tmp = web
    code, _ = jcall(w, "PUT", "/api/cards/NEW1", {"name": "Link", "play": "https://open.spotify.com/album/XY12?si=q"})
    assert code == 200
    assert app._cards_ci["new1"].play == "spotify:album:XY12"          # active without restart
    saved = load_cards(tmp / "cards.toml")
    assert saved["NEW1"].play == "spotify:album:XY12" and "A" in saved


def test_put_replaces_case_insensitively_and_delete(web):
    w, app, *_ = web
    jcall(w, "PUT", "/api/cards/a", {"play": "folder:books/x"})
    assert list(app.cards) == ["a"]
    assert jcall(w, "DELETE", "/api/cards/a")[0] == 200
    assert jcall(w, "DELETE", "/api/cards/a")[0] == 404


@pytest.mark.parametrize("body", [
    {"play": "folder:../etc"}, {"play": "folder:/abs"}, {"play": "http://example.com/x"},
    {"play": "x", "action": "next"}, {}, {"action": "nope"}, {"action": "volume_set", "args": {"a b": 1}},
    {"play": "radio:x"},
])
def test_rejects_bad_cards(web, body):
    w, *_ = web
    assert jcall(w, "PUT", "/api/cards/X", body)[0] == 400


def test_action_card_with_args_roundtrips(web):
    w, _, _, tmp = web
    assert jcall(w, "PUT", "/api/cards/V", {"action": "volume_set", "args": {"value": 40}})[0] == 200
    assert load_cards(tmp / "cards.toml")["V"].args == {"value": 40}


def test_odd_text_in_names_is_escaped(web):
    w, _, _, tmp = web
    jcall(w, "PUT", "/api/cards/Q", {"name": 'He said "hi" \\ ok', "play": "folder:a"})
    assert load_cards(tmp / "cards.toml")["Q"].name == 'He said "hi" \\ ok'


def test_mutations_need_json_content_type(web):
    w, *_ = web
    assert call(w, "PUT", "/api/cards/X", {"play": "folder:a"}, ctype="text/plain")[0] == 400
    assert call(w, "POST", "/api/action", {"name": "next"}, ctype="application/x-www-form-urlencoded")[0] == 400


def test_action_and_play_go_through_the_bus(web):
    w, app, bus, _ = web
    seen = []
    bus.subscribe("*", seen.append)
    assert jcall(w, "POST", "/api/action", {"name": "next"})[0] == 200
    assert jcall(w, "POST", "/api/action", {"name": "bogus"})[0] == 400
    assert jcall(w, "POST", "/api/cards/A/play", {})[0] == 200
    bus.drain(app.handle)
    names = [e.name for e in seen]
    assert ev.ACTION in names and ev.CARD in names and ev.PLAYING in names


def test_state_tracks_events_and_last_card(web):
    w, app, bus, _ = web
    bus.post(ev.CARD, id="ZZ9"); bus.post(ev.CARD_UNKNOWN, id="ZZ9"); bus.post(ev.VOLUME, value=33)
    bus.drain(app.handle)
    _, s = jcall(w, "GET", "/api/state")
    assert s["last_card"] == "ZZ9" and not s["last_card_known"] and s["volume"] == 33
    bus.post(ev.CARD, id="a"); bus.drain(app.handle)
    _, s = jcall(w, "GET", "/api/state")
    assert s["last_card_known"] and s["last_card_name"] == "Bedtime" and s["playing"]


def test_list_folders(web):
    w, *_ = web
    assert jcall(w, "GET", "/api/folders")[1] == ["books/x"]
    assert list_folders(w.local_root / "nope") == []


def test_web_accepts_streams_only_over_http(web):
    w, app, *_ = web
    assert jcall(w, "PUT", "/api/cards/R1", {"play": "stream:https://radio.example/live.mp3"})[0] == 200
    assert app._cards_ci["r1"].play == "stream:https://radio.example/live.mp3"
    for bad in ("stream:file:///etc/passwd", "stream:ftp://x", "stream:https://a b"):
        assert jcall(w, "PUT", "/api/cards/R2", {"play": bad})[0] == 400
