import fnmatch
import shutil
import threading
import time
from pathlib import Path

import pytest

from jukebox import events as ev
from jukebox.cli import main
from jukebox.config import Card, ConfigError, load_cards, render_cards
from jukebox.events import EventBus
from jukebox.sync import (SyncError, SyncSettings, SyncThread, Syncer, join_remote, merge_cards, same_cards)


class FakeRclone:
    """A stand-in for the rclone program; the 'cloud' is a folder on disk, addressed as fake:<path>."""

    def __init__(self, root: Path):
        self.root, self.calls, self.fail_on = root, [], None

    def path(self, s: str) -> Path:
        return self.root / s[len("fake:"):].lstrip("/") if s.startswith("fake:") else Path(s)

    def __call__(self, argv):
        self.calls.append(argv)
        cmd = next(a for a in argv if a in ("lsjson", "copyto", "copy", "sync", "lsf", "version"))
        i = argv.index(cmd)
        rest = argv[i + 1:]
        if self.fail_on == cmd:
            return 1, "", "boom: something broke"
        if cmd == "version":
            return 0, "rclone v1.65.0\n", ""
        if cmd == "lsf":
            return 0, "", ""
        if cmd == "lsjson":
            p = self.path(rest[-1])
            if not p.exists():
                return 4, "", "object not found"
            st = p.stat()
            return 0, '{"Path": "%s", "Name": "%s", "Size": %d, "ModTime": "%f", "IsDir": false}' % (p.name, p.name, st.st_size, st.st_mtime), ""
        if cmd == "copyto":
            src, dst = self.path(rest[0]), self.path(rest[1])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return 0, "", ""
        if cmd == "copy":
            src, dst = self.path(rest[0]), self.path(rest[1])
            if not src.exists():
                return 3, "", "directory not found"
            excludes = [rest[j + 1] for j, a in enumerate(rest) if a == "--exclude"]
            update = "--update" in rest
            for f in src.rglob("*"):
                if f.is_file() and not any(fnmatch.fnmatch(f.name, e) for e in excludes):
                    target = dst / f.relative_to(src)
                    if update and target.exists() and target.stat().st_mtime > f.stat().st_mtime:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, target)
            return 0, "", ""
        return 0, "", ""                      # sync: only recorded


def setup(tmp_path, **kw):
    cloud, conf = tmp_path / "cloud", tmp_path / "conf"
    cloud.mkdir(parents=True); conf.mkdir(parents=True)
    s = SyncSettings.from_section({"remote": "fake:Jukebox", **kw})
    fake = FakeRclone(cloud)
    syncer = Syncer(s, "kitchen", conf, conf / "cards.toml", tmp_path / "music", tmp_path / "data", runner=fake)
    return syncer, fake, cloud / "Jukebox", conf


def write_cards(path, *cards):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_cards(cards))


def C(id, name="", play="folder:a", **kw):
    return Card(id, name, play=play, **kw)


def calls_of(fake, cmd):
    return [c for c in fake.calls if cmd in c]


def test_settings_validation():
    for bad in ({}, {"remote": "nocolon"}, {"remote": "a:b", "cards": "x"}, {"remote": "a:b", "music": "both"},
                {"remote": "a:b", "interval_minutes": 0}):
        with pytest.raises(ConfigError):
            SyncSettings.from_section(bad)


def test_join_remote():
    assert join_remote("dropbox:Jukebox", "music") == "dropbox:Jukebox/music"
    assert join_remote("onedrive:", "cards.toml") == "onedrive:cards.toml"
    assert join_remote("a:b/", "boxes", "x") == "a:b/boxes/x"


def test_merge_cases():
    base = {"1": C("1", "one"), "2": C("2", "two"), "3": C("3", "three"), "4": C("4", "four")}
    local = {"1": C("1", "one"), "2": C("2", "two local"), "3": C("3", "three"), "5": C("5", "new local"), "4": C("4", "four local")}
    remote = {"1": C("1", "one remote"), "2": C("2", "two"), "4": C("4", "four remote"), "6": C("6", "new remote"), "3": C("3", "three")}
    merged, conflicts = merge_cards(base, local, remote)
    names = {k: v.name for k, v in merged.items()}
    assert names == {"1": "one remote", "2": "two local", "3": "three", "4": "four remote", "5": "new local", "6": "new remote"}
    assert conflicts == ["4"]                                      # changed on both sides: cloud wins


def test_merge_deletions():
    base = {"1": C("1"), "2": C("2")}
    merged, _ = merge_cards(base, {"1": C("1")}, base)             # deleted on the box
    assert list(merged) == ["1"]
    merged, _ = merge_cards(base, base, {"2": C("2")})             # deleted in the cloud
    assert list(merged) == ["2"]


def test_cards_first_sync_unions_both_sides(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path)
    write_cards(conf / "cards.toml", C("A", "box card"))
    write_cards(cloud / "cards.toml", C("B", "cloud card"))
    res = syncer.run_once(("cards",))
    assert not res.errors and res.cards_changed
    assert set(load_cards(conf / "cards.toml")) == {"A", "B"} and set(load_cards(cloud / "cards.toml")) == {"A", "B"}
    assert (conf / "cards.toml.sync.bak").exists()                 # old local file kept


def test_cards_second_run_changes_nothing_and_changes_flow_both_ways(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path)
    write_cards(cloud / "cards.toml", C("A", "one"))
    syncer.run_once(("cards",))
    fake.calls.clear()
    res = syncer.run_once(("cards",))
    assert not res.cards_changed
    assert not any(c[-1] == "fake:Jukebox/cards.toml" for c in fake.calls if "copyto" in c)   # nothing uploaded
    # edit on the box -> goes to the cloud
    write_cards(conf / "cards.toml", C("A", "one"), C("B", "from web ui"))
    res = syncer.run_once(("cards",))
    assert "B" in load_cards(cloud / "cards.toml") and not res.cards_changed
    # edit in the cloud -> comes to the box
    write_cards(cloud / "cards.toml", C("A", "one"), C("B", "from web ui"), C("C", "from phone"))
    res = syncer.run_once(("cards",))
    assert res.cards_changed and "C" in load_cards(conf / "cards.toml")


def test_cards_conflict_is_reported_and_cloud_wins(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path)
    write_cards(cloud / "cards.toml", C("A", "start"))
    syncer.run_once(("cards",))
    write_cards(conf / "cards.toml", C("A", "box edit"))
    write_cards(cloud / "cards.toml", C("A", "cloud edit"))
    res = syncer.run_once(("cards",))
    assert load_cards(conf / "cards.toml")["A"].name == "cloud edit"
    assert any("both sides" in m for m in res.messages)


def test_cards_pull_and_push_modes(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path, cards="pull")
    write_cards(cloud / "cards.toml", C("A", "cloud"))
    write_cards(conf / "cards.toml", C("A", "box"), C("X", "only on box"))
    syncer.run_once(("cards",))
    assert set(load_cards(conf / "cards.toml")) == {"A"} and load_cards(conf / "cards.toml")["A"].name == "cloud"
    syncer2, fake2, cloud2, conf2 = setup(tmp_path / "p", cards="push")
    write_cards(conf2 / "cards.toml", C("A", "box"))
    write_cards(cloud2 / "cards.toml", C("Z", "cloud"))
    syncer2.run_once(("cards",))
    assert set(load_cards(cloud2 / "cards.toml")) == {"A"}


def test_cards_per_box_and_dry_run(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path, cards_per_box=True)
    write_cards(conf / "cards.toml", C("A"))
    res = syncer.run_once(("cards",), dry_run=True)
    assert not (cloud / "boxes" / "kitchen" / "cards.toml").exists() and res.messages
    syncer.run_once(("cards",))
    assert (cloud / "boxes" / "kitchen" / "cards.toml").exists()


def test_config_pull_keeps_cards_and_flags_changes(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path)
    box = cloud / "boxes" / "kitchen"
    box.mkdir(parents=True)
    (box / "config.toml").write_text("[box]\nname = 'kitchen'\n")
    (box / "cards.toml").write_text("SHOULD NOT ARRIVE")
    (box / "sounds").mkdir(); (box / "sounds" / "boot.mp3").write_text("mp3")
    (conf / "cards.toml").write_text("local cards")
    res = syncer.run_once(("config",))
    assert res.config_changed and (conf / "config.toml").exists() and (conf / "sounds" / "boot.mp3").exists()
    assert (conf / "cards.toml").read_text() == "local cards"
    copy = calls_of(fake, "copy")[0]
    assert "--update" in copy and copy[copy.index("--exclude") + 1] == "cards.toml"
    assert not syncer.run_once(("config",)).config_changed


def test_music_copy_vs_sync(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path, bwlimit="2M")
    (cloud / "music").mkdir(parents=True)
    (cloud / "music" / "a.mp3").write_text("x")
    syncer.run_once(("music",))
    cmd = calls_of(fake, "copy")[0]
    assert "sync" not in cmd and "--bwlimit" in cmd and "2M" in cmd


def test_music_delete_mode_uses_sync_with_limit_and_refuses_missing_remote(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path, delete=True)
    res = syncer.run_once(("music",))
    assert res.errors and not calls_of(fake, "sync")                   # cloud folder missing: nothing deleted
    (cloud / "music").mkdir(parents=True)
    (cloud / "music" / "x").write_text("x")
    # lsjson --stat on a directory: the fake answers for existing paths
    res = syncer.run_once(("music",))
    sync_cmd = calls_of(fake, "sync")[0]
    assert "--max-delete" in sync_cmd and not res.errors


def test_failures_are_reported_not_raised(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path)
    fake.fail_on = "copy"
    res = syncer.run_once(("config", "music"))
    assert len(res.errors) == 2 and "boom" in res.errors[0]
    def missing(argv): raise SyncError("rclone not found: install rclone")
    s2 = Syncer(syncer.s, "k", conf, conf / "cards.toml", tmp_path / "m", tmp_path / "d", runner=missing)
    assert "install rclone" in s2.run_once(("cards",)).errors[0]


def test_off_modes_do_nothing(tmp_path):
    syncer, fake, *_ = setup(tmp_path, cards="off", config="off", music="off")
    res = syncer.run_once()
    assert not fake.calls and not res.errors


def test_sync_thread_reacts_to_saved_cards_and_reloads(tmp_path):
    syncer, fake, cloud, conf = setup(tmp_path)
    write_cards(cloud / "cards.toml", C("A", "cloud"))
    bus = EventBus()
    changed = threading.Event()
    bus.subscribe(ev.CARDS_CHANGED, lambda e: changed.set())
    t = SyncThread(syncer, bus, interval_s=3600, first_delay=0.01, settle=0)
    t.start()
    drain = threading.Thread(target=lambda: bus.run(lambda e: None), daemon=True)
    drain.start()
    assert changed.wait(5)                                              # first run pulled the cloud's card
    write_cards(conf / "cards.toml", C("A", "cloud"), C("B", "web"))
    bus.post(ev.CARDS_SAVED)
    for _ in range(100):
        if (cloud / "cards.toml").exists() and "B" in load_cards(cloud / "cards.toml"):
            break
        time.sleep(0.05)
    assert "B" in load_cards(cloud / "cards.toml")
    t.stop(); bus.stop()


def test_cli_sync_errors(tmp_path, capsys):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[sync]\nenabled = true\n")
    assert main(["-c", str(cfg), "sync", "--dry-run"]) == 1
    assert "remote is not set" in capsys.readouterr().out
    cfg.write_text('[sync]\nremote = "fake:x"\nrclone = "/nonexistent/rclone"\n')
    assert main(["-c", str(cfg), "sync", "--dry-run"]) == 1
    assert "install rclone" in capsys.readouterr().out
    assert main(["-c", str(cfg), "sync", "--check"]) == 1
    assert main(["-c", str(cfg), "sync", "--only", "nope"]) == 1


def test_app_replace_cards():
    from fakes import FakePlayer
    from jukebox.app import App
    from jukebox.config import load_config
    from jukebox.players import PlayerRouter
    app = App(load_config(None), {"A": C("A")}, PlayerRouter({"folder": FakePlayer()}), EventBus())
    app.replace_cards({"B": C("B")})
    assert list(app.cards) == ["B"] and "b" in app._cards_ci and "a" not in app._cards_ci
