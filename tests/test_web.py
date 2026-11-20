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


def test_dropped_connections_are_not_logged(caplog):
    from jukebox.web import _Server
    srv = _Server.__new__(_Server)
    try:
        raise ConnectionResetError(104, "reset")
    except ConnectionResetError:
        srv.handle_error(None, ("127.0.0.1", 1))
    assert not caplog.records


def test_keep_alive_serves_several_requests_on_one_connection(web):
    import http.client
    w, *_ = web
    c = http.client.HTTPConnection("127.0.0.1", w.port)
    for _ in range(3):
        c.request("GET", "/api/state")
        r = c.getresponse()
        assert r.status == 200 and r.version == 11
        json.loads(r.read())
    # a rejected POST must not leave its body behind and confuse the next request on the same connection
    c.request("POST", "/api/cards/A/play", body=b'{"x": 1}', headers={"Content-Type": "text/plain"})
    r = c.getresponse(); r.read()
    assert r.status == 400
    c.request("GET", "/api/state")
    r = c.getresponse()
    assert r.status == 200
    c.close()


def test_oversized_body_is_refused_and_closes_the_connection(web):
    import http.client
    w, *_ = web
    c = http.client.HTTPConnection("127.0.0.1", w.port)
    c.putrequest("POST", "/api/action")
    c.putheader("Content-Type", "application/json")
    c.putheader("Content-Length", str(10 * 1024 * 1024))
    c.endheaders()
    r = c.getresponse()
    assert r.status == 400
    c.close()


def test_gzip_only_when_asked_and_worth_it(web):
    import gzip
    import http.client
    w, app, *_ = web
    for i in range(60):
        app.set_card(Card(f"C{i}", f"Card number {i}", play="spotify:playlist:abcdefghij"))
    c = http.client.HTTPConnection("127.0.0.1", w.port)
    c.request("GET", "/api/cards", headers={"Accept-Encoding": "gzip"})
    r = c.getresponse()
    raw = r.read()
    assert r.getheader("Content-Encoding") == "gzip"
    assert len(json.loads(gzip.decompress(raw))) == 61
    c.request("GET", "/api/cards")
    r = c.getresponse()
    assert r.getheader("Content-Encoding") is None and len(json.loads(r.read())) == 61
    c.request("GET", "/api/state", headers={"Accept-Encoding": "gzip"})
    r = c.getresponse(); r.read()
    assert r.getheader("Content-Encoding") is None   # tiny: not worth compressing
    c.close()


def test_folder_list_is_cached_briefly(web):
    w, *_ = web
    assert jcall(w, "GET", "/api/folders")[1] == ["books/x"]
    (w.local_root / "new").mkdir()
    (w.local_root / "new" / "1.mp3").write_text("x")
    assert jcall(w, "GET", "/api/folders")[1] == ["books/x"]      # still the cached walk
    w._folders = None
    assert jcall(w, "GET", "/api/folders")[1] == ["books/x", "new"]


def test_state_reports_the_card_count(web):
    w, app, *_ = web
    assert jcall(w, "GET", "/api/state")[1]["cards"] == 1
    app.set_card(Card("B", "x", play="spotify:playlist:b"))
    assert jcall(w, "GET", "/api/state")[1]["cards"] == 2


def test_play_from_the_web_is_logged_with_its_source(web, caplog):
    import logging
    w, app, bus, _ = web
    with caplog.at_level(logging.INFO, logger="jukebox.app"):
        assert jcall(w, "POST", "/api/cards/A/play", {})[0] == 200
        bus.drain(app.handle)
    assert any("card A (Bedtime) via web" in r.getMessage() for r in caplog.records)


def _state(w):
    return jcall(w, "GET", "/api/state")[1]


def test_spotify_cover_is_passed_on_as_an_address(web):
    w, app, bus, _ = web
    assert _state(w)["cover"] == ""
    bus.post(ev.TRACK, title="T", artist="A", cover_url="https://i.scdn.co/image/abc")
    bus.drain(app.handle)
    assert _state(w)["cover"] == "https://i.scdn.co/image/abc"
    assert jcall(w, "GET", "/api/cover")[0] == 404          # nothing local to serve
    bus.post(ev.TRACK, title="T2", artist="A", cover_url="javascript:alert(1)")
    bus.drain(app.handle)
    assert _state(w)["cover"] == ""                           # only http(s) addresses and local pictures


def test_local_cover_is_served_from_the_file_the_player_reported(web):
    w, app, bus, tmp = web
    pic = tmp / "cover.jpg"
    pic.write_bytes(b"\xff\xd8jpegdata" * 500)                # over 1 KB: still not gzipped
    bus.post(ev.TRACK, title="T", artist="A", cover_url=str(pic))
    bus.drain(app.handle)
    url = _state(w)["cover"]
    assert url.startswith("/api/cover?v=")
    req = urllib.request.Request(f"http://127.0.0.1:{w.port}{url}", headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req) as r:
        assert r.headers["Content-Type"] == "image/jpeg" and r.headers.get("Content-Encoding") is None
        assert r.read() == pic.read_bytes() and "max-age" in r.headers["Cache-Control"]
    bus.post(ev.TRACK, title="T", artist="A", cover_url=str(pic))      # same file again: same address
    bus.drain(app.handle)
    assert _state(w)["cover"] == url
    pic.write_bytes(b"\xff\xd8other" * 10)                              # replaced: new address
    bus.post(ev.TRACK, title="T", artist="A", cover_url=str(pic))
    bus.drain(app.handle)
    assert _state(w)["cover"] != url


def test_cover_survives_playing_events_and_goes_with_stop_or_a_track_without_cover(web):
    w, app, bus, tmp = web
    pic = tmp / "folder.png"
    pic.write_bytes(b"\x89PNG" + b"x" * 20)
    bus.post(ev.TRACK, title="T", artist="A", cover_url=str(pic))
    bus.drain(app.handle)
    assert _state(w)["cover"]
    bus.post(ev.PAUSED); bus.drain(app.handle)
    assert _state(w)["cover"]                                           # paused: still the same track
    # Soloist reports the track before the box posts `playing` for the card: that must not wipe the cover
    bus.post(ev.PLAYING, target="folder:x", name="X"); bus.drain(app.handle)
    assert _state(w)["cover"]
    bus.post(ev.TRACK, title="T2", artist="A", cover_url=None); bus.drain(app.handle)
    assert _state(w)["cover"] == "" and jcall(w, "GET", "/api/cover")[0] == 404
    bus.post(ev.TRACK, title="T", artist="A", cover_url=str(pic)); bus.post(ev.STOPPED)
    bus.drain(app.handle)
    assert _state(w)["cover"] == ""


def test_cover_refuses_other_files_and_big_ones(web, monkeypatch):
    w, app, bus, tmp = web
    secret = tmp / "secret.txt"
    secret.write_text("no")
    big = tmp / "big.jpg"
    big.write_bytes(b"\xff\xd8" + b"x" * 100)
    monkeypatch.setattr("jukebox.web.COVER_MAX", 50)
    for src in (str(secret), str(big), "relative/cover.jpg", str(tmp / "missing.jpg")):
        bus.post(ev.TRACK, title="T", artist="A", cover_url=src)
        bus.drain(app.handle)
        assert _state(w)["cover"] == "", src
        assert jcall(w, "GET", "/api/cover")[0] == 404


def test_page_has_cover_and_a_shutdown_button_that_asks_first(web):
    w, *_ = web
    page = call(w, "GET", "/")[1].decode()
    assert 'id="cover"' in page and 'id="shutdown"' in page and "confirm(" in page


def test_shutdown_action_goes_through_the_bus(web):
    w, app, bus, _ = web
    seen = []
    bus.subscribe("*", seen.append)
    assert jcall(w, "POST", "/api/action", {"name": "shutdown"})[0] == 200
    bus.drain(lambda e: None)                       # not app.handle: that would run the real command
    assert [(e.name, e.data["name"]) for e in seen] == [(ev.ACTION, "shutdown")]
