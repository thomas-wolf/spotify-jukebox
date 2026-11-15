import json
import os

import pytest
from PIL import Image

from fakes import FakeMpv
from jukebox import events as ev
from jukebox.covers import CoverResolver, SearchError, SpotifySearch, best_album, find_cover_file
from jukebox.events import EventBus
from jukebox.players.local import LocalPlayer
from jukebox.players.trackinfo import LocalTrackPoller

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 20
ITEMS = [
    {"name": "Abbey Road (Remastered)", "artists": [{"name": "The Beatles"}], "images": [{"url": "https://i/big"}, {"url": "https://i/small"}]},
    {"name": "Abbey Road Sessions", "artists": [{"name": "Someone Else"}], "images": [{"url": "https://i/other"}]},
]


def test_find_cover_file_by_convention(tmp_path):
    assert find_cover_file(tmp_path) is None
    (tmp_path / "Folder.PNG").write_bytes(b"x")
    assert find_cover_file(tmp_path).name == "Folder.PNG"
    (tmp_path / "cover.jpg").write_bytes(b"x")
    assert find_cover_file(tmp_path).name == "cover.jpg"            # cover beats folder
    assert find_cover_file(tmp_path / "missing") is None


def test_best_album_requires_a_good_match():
    assert best_album(ITEMS, "Abbey Road", "The Beatles") == "https://i/big"
    assert best_album(ITEMS, "Abbey Road", "Beatles") == "https://i/big"      # artist contained in the name
    assert best_album(ITEMS, "Abbey Road", "Rolling Stones") is None          # wrong artist
    assert best_album(ITEMS, "Something Completely Different", "") is None
    assert best_album([{"name": "x", "images": []}], "x", "") is None


class FakeSearch:
    def __init__(self, result=None, error=None): self.result, self.error, self.calls = result, error, 0
    def find(self, album, artist=""):
        self.calls += 1
        if self.error: raise self.error
        return self.result


def resolver(tmp_path, search, **kw):
    return CoverResolver(tmp_path / "data", search, download=lambda url: JPEG, **kw)


def test_resolver_saves_found_cover_in_folder_then_uses_it(tmp_path):
    album = tmp_path / "music" / "Artist" / "Album"; album.mkdir(parents=True)
    s = FakeSearch("https://i/x")
    r = resolver(tmp_path, s)
    assert r.lookup(album) is None
    path = r.fetch(album, "Album", "Artist")
    assert path == str(album / "cover.jpg") and (album / "cover.jpg").read_bytes() == JPEG
    assert r.lookup(album) == path and s.calls == 1


def test_resolver_falls_back_to_data_dir_when_folder_not_writable(tmp_path):
    album = tmp_path / "ro"; album.mkdir()
    r = resolver(tmp_path, FakeSearch("https://i/x"), write_to_folder=False)
    path = r.fetch(album, "Album")
    assert path.startswith(str(tmp_path / "data" / "covers")) and r.lookup(album) == path
    assert not (album / "cover.jpg").exists()


def test_not_found_is_remembered_but_errors_are_not(tmp_path):
    album = tmp_path / "rare"; album.mkdir()
    clock = [1000.0]
    s = FakeSearch(None)
    r = resolver(tmp_path, s, now=lambda: clock[0])
    assert r.fetch(album, "Rare Album") is None and r.fetch(album, "Rare Album") is None
    assert s.calls == 1                                                  # the second time it is not asked again
    clock[0] += 31 * 86400
    r.fetch(album, "Rare Album")
    assert s.calls == 2                                                  # asked again after a month
    offline = FakeSearch(error=SearchError("offline"))
    r2 = resolver(tmp_path / "other", offline)
    assert r2.fetch(album, "A") is None and r2.fetch(album, "A") is None
    assert offline.calls == 2                                            # errors are retried


def test_download_must_be_a_picture_and_https(tmp_path):
    album = tmp_path / "a"; album.mkdir()
    r = CoverResolver(tmp_path / "d", FakeSearch("https://i/x"), download=lambda u: b"<html>")
    assert r.fetch(album, "A") is None
    r = CoverResolver(tmp_path / "d", FakeSearch("http://i/x"), download=lambda u: JPEG)
    assert r.fetch(album, "A") is None


def test_spotify_search_uses_session_token():
    seen = {}
    def get(url, headers):
        seen["url"], seen["headers"] = url, headers
        return json.dumps({"albums": {"items": ITEMS}}).encode()
    s = SpotifySearch(lambda: "TOKEN", get)
    assert s.find("Abbey Road", "The Beatles") == "https://i/big"
    assert seen["headers"]["Authorization"] == "Bearer TOKEN" and "type=album" in seen["url"] and "limit=10" in seen["url"]
    with pytest.raises(SearchError):
        SpotifySearch(lambda: None, get).find("x")
    def boom(): raise RuntimeError("down")
    with pytest.raises(SearchError):
        SpotifySearch(boom, get).find("x")


def test_local_player_reports_current_track(tmp_path):
    mpv = FakeMpv()
    player = LocalPlayer(mpv, tmp_path, tmp_path / "s.json")
    assert player.current_track() is None
    mpv.props.update({"path": "/m/a/1.mp3", "pause": False,
                      "metadata": {"ARTIST": "Band", "Album": "LP", "title": "Song"}})
    assert player.current_track() == {"path": "/m/a/1.mp3", "title": "Song", "artist": "Band", "album": "LP", "paused": False}


class FakePlayer:
    def __init__(self, info): self.info = info
    def current_track(self): return self.info


def test_local_poller_posts_folder_cover_or_searches_once(tmp_path):
    root = tmp_path / "music"; album = root / "Band" / "LP"; album.mkdir(parents=True)
    bus, seen = EventBus(), []
    bus.subscribe("track", seen.append)
    info = {"path": str(album / "01 Song.mp3"), "title": "", "artist": "", "album": "", "paused": False}
    s = FakeSearch("https://i/x")
    poller = LocalTrackPoller(bus, FakePlayer(info), resolver(tmp_path, s), root)
    poller.poll_once(); poller.poll_once()
    bus.drain(lambda e: None)
    assert [e.data["cover_url"] for e in seen] == [None, str(album / "cover.jpg")]    # first without, then found
    assert seen[0].data["title"] == "01 Song" and s.calls == 1
    seen.clear()
    info["path"] = str(album / "02.mp3")                                              # next track, same album
    poller.poll_once(); bus.drain(lambda e: None)
    assert [e.data["cover_url"] for e in seen] == [str(album / "cover.jpg")] and s.calls == 1


def test_local_poller_guesses_album_and_artist_from_folders(tmp_path):
    root = tmp_path / "music"; album = root / "Band" / "LP"; album.mkdir(parents=True)
    asked = []
    class S:
        def find(self, album, artist=""): asked.append((album, artist)); return None
    info = {"path": str(album / "1.mp3"), "title": "T", "artist": "", "album": "", "paused": False}
    LocalTrackPoller(EventBus(), FakePlayer(info), resolver(tmp_path, S()), root).poll_once()
    assert asked == [("LP", "Band")]
    top = root / "Loose"; top.mkdir()
    asked.clear()
    info["path"] = str(top / "1.mp3")
    LocalTrackPoller(EventBus(), FakePlayer(info), resolver(tmp_path / "x", S()), root).poll_once()
    assert asked == [("Loose", "")]


def test_renderer_fetch_reads_local_cover_file(tmp_path):
    from jukebox.display.render import fetch_cover
    f = tmp_path / "c.png"
    Image.new("RGB", (10, 10), (1, 2, 3)).save(f)
    assert fetch_cover(str(f)).size == (10, 10)
    with pytest.raises(ValueError):
        fetch_cover("ftp://x/y")
