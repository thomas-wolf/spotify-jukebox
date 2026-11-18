import json
import time

import pytest

from jukebox import events as ev
from jukebox.players import PlayerError, soloist
from jukebox.players.soloist import SoloistClient, SoloistPlayer, parse_ws, track_from_state
from jukebox.players.trackinfo import SoloistTrackReporter

# playback_state as sent by soloist 1.3.10.79 (macOS), shortened to the fields that matter
STATE = json.loads("""{"type":"playback_state","status":"playing","item":{"uri":"spotify:track:4zd9RlMM0M43UE0ZoRFH6h",
"entity_type":"track","decorations":{"identity":{"name":"BLACK (feat. Jazeek)"},"visual_identity":{"cover":[
{"url":"https://i.scdn.co/image/small","size":"small"},{"url":"https://i.scdn.co/image/default","size":"default"},
{"url":"https://i.scdn.co/image/large","size":"large"}]},"parent":{"entity":{"uri":"spotify:album:0znA",
"entity_type":"album","decorations":{"identity":{"name":"BLACK"}}}},"creators":[
{"entity":{"uri":"spotify:artist:1","entity_type":"artist","decorations":{"identity":{"name":"Bantu Nation"}}}},
{"entity":{"uri":"spotify:artist:2","entity_type":"artist","decorations":{"identity":{"name":"Nu51"}}}}],
"playback":{"duration_ms":173857}}},"context":{"uri":"spotify:playlist:37i9dQZEVXbJiZcmkrIHGU","entity_type":"playlist",
"decorations":{"identity":{"name":"Top 50"}}},"position":{"position_ms":65055,"timestamp_ms":1794947753044,"speed":1},
"volume":30,"is_active":false}""")


class FakeWs:
    def __init__(self):
        self.sent = []

    def send_text(self, text):
        self.sent.append(json.loads(text))

    def close(self):
        pass


def connected_client():
    client = SoloistClient("127.0.0.1", 9090)
    client._ws, client.connected = FakeWs(), True
    return client


def test_parse_ws():
    assert parse_ws("127.0.0.1:9090") == ("127.0.0.1", 9090)
    assert parse_ws("ws://localhost:1234/") == ("localhost", 1234)
    with pytest.raises(PlayerError):
        parse_ws("nonsense")


def test_track_from_the_real_state():
    assert track_from_state(STATE) == {"title": "BLACK (feat. Jazeek)", "artist": "Bantu Nation, Nu51",
                                       "cover_url": "https://i.scdn.co/image/default",
                                       "uri": "spotify:track:4zd9RlMM0M43UE0ZoRFH6h"}
    assert track_from_state({"type": "playback_state", "status": "idle"}) is None


def test_player_commands():
    c = connected_client()
    p = SoloistPlayer(c)
    p.play("spotify:playlist:x")
    p.pause()
    p.resume()
    p.next()
    p.prev()
    p.set_volume(250)
    cmds = [(m["command"], {k: v for k, v in m.items() if k not in ("type", "command")}) for m in c._ws.sent]
    assert cmds == [("play", {"uri": "spotify:playlist:x"}), ("pause", {}), ("play", {}), ("skip_next", {}),
                    ("skip_prev", {}), ("set_volume", {"volume": 100})]
    assert all(m["type"] == "command" for m in c._ws.sent)


def test_play_rejects_foreign_targets():
    with pytest.raises(PlayerError):
        SoloistPlayer(connected_client()).play("folder:x")


def test_not_reachable_and_not_logged_in():
    p = SoloistPlayer(SoloistClient("127.0.0.1", 9090))
    with pytest.raises(PlayerError, match="not reachable"):
        p.pause()
    c = connected_client()
    c.handle({"type": "auth_state", "logged_in": False})
    with pytest.raises(PlayerError, match="not logged in"):
        SoloistPlayer(c).pause()
    c.handle({"type": "auth_state", "logged_in": True})
    SoloistPlayer(c).pause()


def test_is_playing_follows_the_state():
    c = connected_client()
    p = SoloistPlayer(c)
    assert not p.is_playing()
    c.handle(STATE)
    assert p.is_playing()
    c.handle({**STATE, "status": "paused"})
    assert not p.is_playing()


def test_seek_is_relative_to_the_reported_position():
    c = connected_client()
    c.handle({**STATE, "status": "paused"})
    SoloistPlayer(c).seek(15)
    assert c._ws.sent[-1]["command"] == "seek" and c._ws.sent[-1]["position_ms"] == 80055
    with pytest.raises(PlayerError):
        SoloistPlayer(connected_client()).seek(5)


def test_events_ask_for_a_fresh_state():
    c = connected_client()
    c.handle({"type": "volume_changed"})
    c.handle({"type": "playback_changed"})
    c.handle({"type": "command_result", "command": "pause"})
    assert [m["command"] for m in c._ws.sent] == ["get_state", "get_state"]


def test_volume_is_sent_again_after_play_when_soloist_reports_another_one():
    c = connected_client()
    p = SoloistPlayer(c)
    p.set_volume(30)
    p.play("spotify:playlist:x")
    c._ws.sent.clear()
    c.handle({**STATE, "is_active": False, "volume": 100})      # not active yet: nothing to fix
    assert c._ws.sent == []
    c.handle({**STATE, "is_active": True, "volume": 100})        # PipeWire started at 100
    assert c._ws.sent == [{"type": "command", "command": "set_volume", "volume": 30}]
    c.handle({**STATE, "is_active": True, "volume": 100})        # not again within a second
    assert len(c._ws.sent) == 1


def test_volume_is_not_enforced_outside_the_window():
    c = connected_client()
    SoloistPlayer(c).set_volume(30)
    c._ws.sent.clear()
    c.handle({**STATE, "is_active": True, "volume": 90})         # someone used the phone: leave it
    assert c._ws.sent == []


def test_reporter_posts_when_playing_and_changes():
    bus = ev.EventBus()
    seen = []
    bus.subscribe(ev.TRACK, seen.append)
    r = SoloistTrackReporter(bus)
    r.on_state({**STATE, "status": "paused"})                     # restored session at boot: no cover
    r.on_state(STATE)                                              # resumed
    r.on_state(STATE)                                              # same again
    other = json.loads(json.dumps(STATE).replace("4zd9RlMM0M43UE0ZoRFH6h", "other"))
    r.on_state(other)
    bus.drain(lambda e: None)
    assert [e.data["uri"] for e in seen] == ["spotify:track:4zd9RlMM0M43UE0ZoRFH6h", "spotify:track:other"]
    assert seen[0].data["title"] == "BLACK (feat. Jazeek)"


def test_client_thread_reads_state_over_a_real_websocket():
    from tests.test_websocket import make_pair, server_frame, read_client_frame
    ws, server = make_pair(extra=server_frame(1, b'{"type":"auth_state","logged_in":true}'))
    client = SoloistClient("h", 1, connect=lambda host, port: ws)
    client.start()
    assert read_client_frame(server)[1].decode().count("get_state") == 1     # asked on connect
    server.sendall(server_frame(1, json.dumps(STATE).encode()))
    deadline = time.monotonic() + 3
    while client.state is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert client.state and client.state["status"] == "playing" and client.logged_in
    client.stop()
