"""Build detection after `jukebox-deploy`, and the "Update old -> new" message on the display."""

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from jukebox import events as ev
from jukebox.display import bind_update_notice
from jukebox.events import EventBus
from jukebox.version import check_update, installed_build

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "jukebox-deploy"


def test_installed_build_reads_first_line_and_tolerates_a_missing_file(tmp_path):
    f = tmp_path / "VERSION"
    f.write_text("5102d56\n")
    assert installed_build(f) == "5102d56"
    assert installed_build(tmp_path / "none") == ""
    f.write_text("")
    assert installed_build(f) == ""


def test_first_start_remembers_the_build_without_a_notice(tmp_path):
    assert check_update(tmp_path, "aaa1111") is None
    assert (tmp_path / "build.txt").read_text().strip() == "aaa1111"


def test_same_build_gives_no_notice_and_a_new_one_gives_old_and_new(tmp_path):
    check_update(tmp_path, "aaa1111")
    assert check_update(tmp_path, "aaa1111") is None
    assert check_update(tmp_path, "bbb2222") == ("aaa1111", "bbb2222")
    assert check_update(tmp_path, "bbb2222") is None          # shown once
    assert (tmp_path / "build.txt").read_text().strip() == "bbb2222"


def test_box_without_version_file_gives_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("JUKEBOX_VERSION_FILE", str(tmp_path / "missing"))
    assert check_update(tmp_path) is None
    assert not (tmp_path / "build.txt").exists()


class FakeDisplay:
    idle_picture = None

    def __init__(self):
        self.calls = []

    def show_track(self, title, artist="", cover_url=None): self.calls.append(("track", title))
    def show_idle(self): self.calls.append(("idle",))
    def clear(self): self.calls.append(("clear",))
    def close(self): pass


def run_bus(bus):
    bus.drain(lambda e: None)


def test_update_notice_is_shown_and_then_the_screen_is_cleared():
    bus, d = EventBus(), FakeDisplay()
    bind_update_notice(d, bus, seconds=0.05)
    bus.post(ev.UPDATED, old="aaa1111", new="bbb2222")
    run_bus(bus)
    assert d.calls[0] == ("track", "Update aaa1111 → bbb2222")
    import time
    time.sleep(0.2)
    assert d.calls[-1] == ("clear",)


def test_update_notice_does_not_cover_a_track_that_started_meanwhile():
    bus, d = EventBus(), FakeDisplay()
    bind_update_notice(d, bus, seconds=0.05)
    bus.post(ev.UPDATED, old="a", new="b")
    bus.post(ev.TRACK, title="Song", artist="", cover_url=None)
    run_bus(bus)
    import time
    time.sleep(0.2)
    assert ("clear",) not in d.calls and ("idle",) not in d.calls


def _build_of(tmp_path, top, ref="develop"):
    """Runs the part of jukebox-deploy that works out the build, with a tarball whose top folder is `top`."""
    tar = tmp_path / "jb.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        info = tarfile.TarInfo(top + "/README.md")
        info.size = 0
        t.addfile(info, io.BytesIO(b""))
    text = SCRIPT.read_text()
    snippet = text[text.index("top=$("):text.index("tar -xzf")]
    out = subprocess.run(["sh", "-c", f'tmp="{tmp_path}"; ref="{ref}"\n{snippet}\necho "$build"'],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_deploy_build_is_the_short_commit_hash_of_the_tarball(tmp_path):
    assert _build_of(tmp_path, "spotify-jukebox-5102d56a1b2c3d4e5f60718293a4b5c6d7e8f901") == "5102d56"


def test_deploy_build_falls_back_to_the_ref_without_a_hash(tmp_path):
    assert _build_of(tmp_path, "spotify-jukebox-develop", ref="develop") == "develop"
