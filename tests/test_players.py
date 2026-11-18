import json

import pytest

from fakes import FakeMpv, FakePlayer
from jukebox.players import PlayerError, PlayerRouter
from jukebox.players.local import LocalPlayer
from jukebox.players.spotify import ENDPOINTS, SpotifyPlayer


# -- Spotify --------------------------------------------------------------
class Transport:
    def __init__(self):
        self.calls = []
        self.reply = None

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        return self.reply


def test_spotify_play_sends_uri_and_rejects_others():
    t = Transport()
    p = SpotifyPlayer(t)
    p.play("spotify:playlist:abc")
    assert t.calls[-1] == (*ENDPOINTS["play"], {"uri": "spotify:playlist:abc"})
    with pytest.raises(PlayerError):
        p.play("folder:x")


def test_spotify_volume_clamped_and_seek_in_ms():
    t = Transport()
    p = SpotifyPlayer(t)
    p.set_volume(250)
    p.seek(-15)
    assert t.calls[0][2] == {"volume": 100}
    assert t.calls[1][2] == {"position": -15000, "relative": True}


def test_spotify_state_follows_status_and_survives_outage():
    t = Transport()
    p = SpotifyPlayer(t)
    p.play("spotify:album:x")
    t.reply = {"paused": True}
    assert p.is_playing() is False

    def down(*a):
        raise PlayerError("unreachable")
    p._call = down
    assert p.is_playing() is False                 # falls back to last known state


# -- Local ------------------------------------------------------------------
@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    book = root / "book"
    book.mkdir(parents=True)
    for n in ("10.mp3", "2.mp3", "1.mp3", "cover.jpg"):
        (book / n).write_text("x")
    return root


def make_local(music, tmp_path):
    mpv = FakeMpv()
    return LocalPlayer(mpv, music, tmp_path / "state" / "resume.json"), mpv


def test_folder_is_natural_sorted_and_filtered(music, tmp_path):
    p, _ = make_local(music, tmp_path)
    assert [f.name for f in p.resolve("folder:book")] == ["1.mp3", "2.mp3", "10.mp3"]


@pytest.mark.parametrize("target", ["folder:../etc", "folder:book/../../x", "file:../x.mp3"])
def test_path_traversal_blocked(music, tmp_path, target):
    p, _ = make_local(music, tmp_path)
    with pytest.raises(PlayerError):
        p.resolve(target)


def test_missing_and_empty_targets(music, tmp_path):
    (music / "empty").mkdir()
    p, _ = make_local(music, tmp_path)
    for t in ("folder:nope", "folder:empty", "file:book/none.mp3", "spotify:x", "folder:"):
        with pytest.raises(PlayerError):
            p.resolve(t)


def test_play_loads_playlist_and_unpauses(music, tmp_path):
    p, mpv = make_local(music, tmp_path)
    p.play("folder:book")
    cmds = [c for c in mpv.commands if c[0] == "loadfile"]
    assert [c[2] for c in cmds] == ["replace", "append", "append"]
    assert ("set_property", "pause", False) in mpv.commands
    assert p.is_playing()


def test_resume_position_saved_and_restored(music, tmp_path):
    p, mpv = make_local(music, tmp_path)
    p.play("folder:book")
    mpv.props.update({"playlist-pos": 1, "time-pos": 42.5})
    p.pause()
    saved = json.loads((tmp_path / "state" / "resume.json").read_text())
    assert saved["folder:book"] == {"index": 1, "time": 42.5}
    mpv.commands.clear()
    p.play("folder:book")
    assert ("set_property", "playlist-pos", 1) in mpv.commands
    assert ("seek", 42.5, "absolute") in mpv.commands


def test_corrupt_state_file_is_ignored(music, tmp_path):
    p, mpv = make_local(music, tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "resume.json").write_text("{not json")
    p.play("folder:book")                          # must not raise
    assert p.is_playing()


# -- Router -------------------------------------------------------------------
def test_router_volume_applied_to_new_backend_before_play():
    a, b = FakePlayer("a"), FakePlayer("b")
    r = PlayerRouter({"spotify": a, "folder": b})
    r.set_volume(40)
    r.play("folder:x")
    assert b.calls[-2:] == [("volume", 40), ("play", "folder:x")]


def test_router_unknown_scheme_and_empty_controls():
    r = PlayerRouter({"spotify": FakePlayer()})
    with pytest.raises(PlayerError):
        r.play("folder:x")
    with pytest.raises(PlayerError):
        r.pause()


def test_router_survives_failing_old_backend():
    a, b = FakePlayer("a"), FakePlayer("b")
    r = PlayerRouter({"spotify": a, "folder": b})
    r.play("spotify:x")
    a.fail = True
    r.play("folder:y")                             # stop() on a fails, play goes on
    assert ("play", "folder:y") in b.calls


# -- web radio -------------------------------------------------------------------
def test_stream_playback(tmp_path):
    mpv = FakeMpv()
    player = LocalPlayer(mpv, tmp_path, tmp_path / "s.json")
    player.play("stream:https://radio.example/live.mp3")
    assert ("loadfile", "https://radio.example/live.mp3", "replace") in mpv.commands
    assert player.is_playing()
    n = len(mpv.commands)
    player.next(); player.prev(); player.seek(15)                    # no meaning for a live stream
    assert len(mpv.commands) == n
    player.pause()                                                   # drops the stream ...
    assert mpv.commands[-1] == ("stop",) and not player.is_playing()
    player.resume()                                                  # ... and resume reloads it
    assert ("loadfile", "https://radio.example/live.mp3", "replace") == mpv.commands[-2]
    assert player.is_playing()


def test_stream_rejects_other_schemes(tmp_path):
    player = LocalPlayer(FakeMpv(), tmp_path, tmp_path / "s.json")
    for bad in ("stream:file:///etc/passwd", "stream:rtsp://x", "stream:"):
        with pytest.raises(PlayerError):
            player.play(bad)


def test_folder_after_stream_behaves_normally(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "a" / "1.mp3").write_text("x")
    mpv = FakeMpv()
    player = LocalPlayer(mpv, tmp_path, tmp_path / "s.json")
    player.play("stream:http://r/x")
    player.play("folder:a")
    player.seek(10)
    assert ("seek", 10, "relative") in mpv.commands


def test_current_track_of_a_stream(tmp_path):
    mpv = FakeMpv()
    mpv.props.update({"path": "http://r/x", "pause": False, "metadata": {"icy-title": "Band - Song", "icy-name": "Radio X"}})
    info = LocalPlayer(mpv, tmp_path, tmp_path / "s.json").current_track()
    assert info["stream"] and info["title"] == "Band - Song" and info["artist"] == "Radio X"


def test_router_start_volume_reaches_a_backend_that_was_not_ready_yet():
    """go-librespot may still be starting at boot: the volume is applied again before the first play."""
    a = FakePlayer("spotify", fail=True)
    r = PlayerRouter({"spotify": a})
    r.set_volume(30)                  # fails quietly, nothing raised
    a.fail = False
    r.play("spotify:x")
    assert a.calls[-2:] == [("volume", 30), ("play", "spotify:x")]
