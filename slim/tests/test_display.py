import threading

import pytest
from PIL import Image

from jukebox import events as ev
from jukebox.config import ConfigError, load_config
from jukebox.display import NullDisplay, ScreenDisplay, bind, build_display
from jukebox.display.ili9341 import ILI9341, MADCTL, rgb565
from jukebox.display.layout import Rect, fit_box, logical_size, plan, visible_rect, wrap
from jukebox.display.render import Renderer
from jukebox.display.settings import DisplaySettings
from jukebox.events import EventBus
from jukebox.players.base import PlayerError
from jukebox.players.trackinfo import SpotifyTrackPoller
from jukebox.cli import main


def test_logical_size_and_margins():
    assert logical_size(240, 320, 0) == (240, 320)
    assert logical_size(240, 320, 90) == (320, 240)
    assert logical_size(240, 320, 270) == (320, 240)
    assert visible_rect(320, 240, 10, 5, 20, 15) == Rect(10, 5, 290, 220)
    with pytest.raises(ValueError):
        visible_rect(320, 240, 150, 0, 150, 0)
    with pytest.raises(ValueError):
        logical_size(240, 320, 45)


def test_plan_wide_display_splits_and_respects_side():
    vis = Rect(0, 0, 480, 270)                       # 16:9
    cover, text = plan(vis, "auto", "left")
    assert cover == Rect(0, 0, 270, 270) and text.x > cover.x + cover.w - 1
    cover, text = plan(vis, "auto", "right")
    assert cover == Rect(210, 0, 270, 270) and text.x + text.w <= 210
    assert plan(vis, "cover") == (vis, None)


def test_plan_four_three_display_is_cover_only_unless_forced():
    vis = Rect(0, 0, 320, 240)
    assert plan(vis, "auto") == (vis, None)           # only 80 px left over: no room for text
    cover, text = plan(vis, "split")
    assert cover == Rect(0, 0, 240, 240) and text is not None


def test_plan_portrait():
    cover, text = plan(Rect(0, 0, 240, 320), "auto")
    assert cover == Rect(0, 0, 240, 240) and text.y >= 240
    cover, text = plan(Rect(0, 0, 240, 320), "auto", "bottom")
    assert cover.y == 80 and text.y + text.h <= 80


def test_fit_box():
    assert fit_box(400, 300, 200, 200, "contain") == (200, 150, 0, 25)     # 4:3 cover in a square: bars
    assert fit_box(400, 300, 200, 200, "cover") == (267, 200, -34, 0)      # cropped instead


def test_wrap():
    measure = lambda t: len(t) * 10
    assert wrap("one two three four", measure, 80, 4) == ["one two", "three", "four"]
    assert wrap("a b c d e f g h", measure, 30, 2)[-1].endswith("…")
    assert wrap("Supercalifragilistic", measure, 50, 1) == ["Super"] or len(wrap("Supercalifragilistic", measure, 50, 1)[0]) <= 5


def test_rgb565_known_values():
    assert rgb565(bytes([255, 255, 255])) == b"\xff\xff"
    assert rgb565(bytes([255, 0, 0])) == b"\xf8\x00"
    assert rgb565(bytes([0, 255, 0])) == b"\x07\xe0"
    assert rgb565(bytes([0, 0, 255])) == b"\x00\x1f"
    assert rgb565(bytes([255, 0, 0, 0, 0, 255])) == b"\xf8\x00\x00\x1f"


class FakeSpi:
    def __init__(self):
        self.cmds, self.data, self.closed = [], bytearray(), False

    def writebytes(self, b): self.cmds.append(b[0])
    def writebytes2(self, b): self.data += bytes(b)
    def close(self): self.closed = True


class FakeGpio:
    def __init__(self): self.log = []
    def set_output(self, pin, value): self.log.append((pin, value))
    def close(self): pass


def make_panel(**kw):
    s = DisplaySettings.from_section({"rotation": 90, "dc": 25, "reset": 17, "backlight": 24, **kw})
    spi, gpio = FakeSpi(), FakeGpio()
    return ILI9341(s, spi=spi, gpio=gpio, sleep=lambda _s: None), spi, gpio, s


def test_driver_init_rotation_and_pins():
    for rot in (0, 90, 180, 270):
        panel, spi, gpio, _ = make_panel(rotation=rot)
        assert 0x36 in spi.cmds and 0x29 in spi.cmds
        assert bytes([MADCTL[rot]]) in bytes(spi.data)
        w, h = logical_size(240, 320, rot)
        assert (17, False) in gpio.log and (24, True) in gpio.log           # reset pulse, backlight on
    assert len(MADCTL) == 4


def test_driver_show_sends_whole_frame():
    panel, spi, gpio, s = make_panel()
    spi.data.clear(); spi.cmds.clear()
    panel.show(Image.new("RGB", (320, 240), (255, 0, 0)))
    assert spi.cmds[-3:] == [0x2A, 0x2B, 0x2C]
    assert len(spi.data) >= 320 * 240 * 2 and bytes(spi.data).endswith(b"\xf8\x00" * 100)
    with pytest.raises(ValueError):
        panel.show(Image.new("RGB", (240, 320)))
    panel.close()
    assert spi.closed and (24, False) in gpio.log


def test_driver_without_reset_pin_uses_software_reset():
    _, spi, gpio, _ = make_panel(reset=-1)
    assert 0x01 in spi.cmds and not any(p == 17 for p, _ in gpio.log)


def test_settings_validation():
    for bad in ({"rotation": 45}, {"layout": "x"}, {"background": "red"}, {"cover_fit": "x"},
                {"margins": {"left": 200, "right": 200}}):
        with pytest.raises(ConfigError):
            DisplaySettings.from_section(bad)
    s = DisplaySettings.from_section({"margins": {"left": 4, "bottom": 9}})
    assert (s.margin_left, s.margin_bottom, s.margin_top) == (4, 9, 0)


def test_renderer_keeps_cover_inside_visible_area():
    s = DisplaySettings.from_section({"rotation": 90, "background": "#000000",
                                      "margins": {"left": 20, "right": 20, "top": 10, "bottom": 10}})
    r = Renderer(s)
    img = r.render(Image.new("RGB", (300, 300), (255, 255, 255)), "T", "A")
    assert img.size == (320, 240)
    assert img.getpixel((5, 120)) == (0, 0, 0) and img.getpixel((315, 120)) == (0, 0, 0)   # covered edges stay black
    assert img.getpixel((160, 120)) == (255, 255, 255)
    assert r.blank().getpixel((160, 120)) == (0, 0, 0)


def test_renderer_text_only_without_cover_and_blur_background():
    r = Renderer(DisplaySettings.from_section({"background": "blur"}))
    assert r.render(None, "Folder name", "").size == (320, 240)
    assert r.render(Image.new("RGB", (64, 64), (200, 30, 30)), "x", "y").size == (320, 240)
    assert r.test_pattern().size == (320, 240)


class FakeDriver:
    def __init__(self): self.frames, self.closed, self.seen = [], False, threading.Event()
    def show(self, img): self.frames.append(img); self.seen.set()
    def close(self): self.closed = True


def test_screen_display_renders_and_caches_cover():
    r = Renderer(DisplaySettings.from_section({}))
    fetched = []
    def fetch(url):
        fetched.append(url)
        return Image.new("RGB", (100, 100), (10, 200, 10))
    drv = FakeDriver()
    d = ScreenDisplay(r, drv, fetch=fetch)
    d.show_track("A", "B", "http://x/c.jpg")
    assert drv.seen.wait(3)
    drv.seen.clear()
    d.show_track("A2", "B", "http://x/c.jpg")                # same cover again: not downloaded again
    assert drv.seen.wait(3)
    d.close()
    assert drv.closed and fetched == ["http://x/c.jpg"] and len(drv.frames) == 2
    assert all(f.size == (320, 240) for f in drv.frames)


def test_screen_display_survives_cover_failure():
    drv = FakeDriver()
    d = ScreenDisplay(Renderer(DisplaySettings.from_section({})), drv, fetch=lambda u: 1 / 0)
    d.show_track("Title", "Artist", "http://x/y")
    assert drv.seen.wait(3)
    d.close()


def test_build_display_falls_back_to_null_display():
    assert isinstance(build_display({"rotation": 45}), NullDisplay)          # invalid
    assert isinstance(build_display({}), NullDisplay)                         # no spidev/gpiod here


def test_bind_connects_events():
    bus, calls = EventBus(), []
    class D(NullDisplay):
        def show_track(self, title, artist="", cover_url=None): calls.append(("track", title, artist, cover_url))
        def clear(self): calls.append(("clear",))
    bind(D(), bus)
    bus.post(ev.TRACK, title="T", artist="A", cover_url="u")
    bus.post(ev.PLAYING, target="folder:x", name="Folder")
    bus.post(ev.PLAYING)                       # without a name: ignored
    bus.post(ev.STOPPED)
    bus.drain(lambda e: None)
    assert calls == [("track", "T", "A", "u"), ("track", "Folder", "", None), ("clear",)]


def status(uri="spotify:track:1", paused=False, stopped=False):
    return {"paused": paused, "stopped": stopped, "track": {
        "uri": uri, "name": "Song", "artist_names": ["A", "B"], "album_cover_url": "http://c/1.jpg"}}


def test_poller_posts_on_change_and_resume():
    bus, seen, state = EventBus(), [], {"v": status()}
    bus.subscribe("track", seen.append)
    p = SpotifyTrackPoller(bus, lambda m, path, body: state["v"])
    p.poll_once(); p.poll_once()
    assert len(_drain(bus, seen)) == 1                                   # same track: once
    state["v"] = status(paused=True); p.poll_once()
    state["v"] = status(); p.poll_once()                                  # resumed: again
    state["v"] = status(uri="spotify:track:2"); p.poll_once()            # new track
    events = _drain(bus, seen)
    assert len(events) == 2 and events[0].data["artist"] == "A, B" and events[0].data["cover_url"] == "http://c/1.jpg"


def test_poller_ignores_errors_and_no_session():
    bus = EventBus()
    def boom(*a): raise PlayerError("down")
    SpotifyTrackPoller(bus, boom).poll_once()
    p = SpotifyTrackPoller(bus, lambda *a: None)
    p.poll_once()
    assert p._last is None


def _drain(bus, seen):
    bus.drain(lambda e: None)
    out, seen[:] = list(seen), []
    return out


def test_cli_display_test_saves_picture(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('[display]\nrotation = 270\nmargins = { left = 8, right = 8 }\n')
    out = tmp_path / "t.png"
    assert main(["-c", str(cfg), "display-test", "--save", str(out)]) == 0
    assert Image.open(out).size == (320, 240)
    cfg.write_text('[display]\nrotation = 33\n')
    assert main(["-c", str(cfg), "display-test", "--save", str(out)]) == 1
