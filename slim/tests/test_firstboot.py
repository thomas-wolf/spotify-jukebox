"""jukebox-firstboot: hostname and box configuration from the boot partition (no root, no hardware)."""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

SLIM = Path(__file__).resolve().parents[1]
SCRIPT = SLIM / "image" / "stage-jukebox" / "00-jukebox" / "files" / "jukebox-firstboot"


@pytest.fixture
def fb(monkeypatch):
    loader = importlib.machinery.SourceFileLoader("jukebox_firstboot", str(SCRIPT))
    spec = importlib.util.spec_from_loader("jukebox_firstboot", loader)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)  # dataclasses looks the module up
    loader.exec_module(mod)
    calls = []
    monkeypatch.setattr(mod, "run", lambda cmd, check=True: calls.append(cmd) or 0)
    mod.calls = calls
    return mod


@pytest.fixture
def paths(fb, tmp_path):
    (tmp_path / "boot").mkdir()
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "hosts").write_text("127.0.0.1\tlocalhost\n127.0.1.1\traspberrypi\n")
    (tmp_path / "etc" / "hostname").write_text("raspberrypi\n")
    return fb.Paths(boot=tmp_path / "boot", home=tmp_path / "home", repo=SLIM, venv=tmp_path / "venv",
                    etc=tmp_path / "etc")


def request(paths, text):
    (paths.boot / "jukebox.toml").write_text(text)


def real_box():
    boxes = sorted(p.name for p in (SLIM / "boxes").iterdir() if (p / "config.toml").is_file())
    assert boxes, "no box in boxes/"
    return boxes[0]


def test_box_from_image_sets_hostname_and_config(fb, paths):
    box = real_box()
    request(paths, f'box = "{box}"\n')
    assert fb.provision(paths) == 0
    assert (paths.etc / "hostname").read_text() == f"{box}\n"
    hosts = (paths.etc / "hosts").read_text()
    assert f"127.0.1.1\t{box}" in hosts and "raspberrypi" not in hosts and "localhost" in hosts
    cfg = paths.conf / "config.toml"
    assert cfg.is_symlink() and cfg.resolve() == (SLIM / "boxes" / box / "config.toml").resolve()
    assert paths.marker.is_file() and f"box={box}" in paths.marker.read_text()
    assert ["hostnamectl", "set-hostname", box] in fb.calls
    assert [str(paths.venv / "bin" / "jukebox"), "-c", str(cfg), "setup", "--apply"] in fb.calls
    assert fb.calls[-1] == ["systemctl", "reboot"]


def test_hostname_differs_from_box(fb, paths):
    request(paths, f'box = "{real_box()}"\nhostname = "kueche"\n')
    fb.provision(paths, reboot=False)
    assert (paths.etc / "hostname").read_text() == "kueche\n"
    assert ["systemctl", "reboot"] not in fb.calls


def test_shutdown_override_written_unless_box_sets_it(fb, paths):
    request(paths, f'box = "{real_box()}"\n')
    fb.provision(paths, reboot=False)
    local = paths.conf / "config.local.toml"
    box_cfg = (SLIM / "boxes" / real_box() / "config.toml").read_text()
    if "shutdown_command" in box_cfg:
        assert not local.exists()
    else:
        assert '"sudo", "systemctl", "poweroff"' in local.read_text()


def test_boot_partition_folder_wins_and_is_copied(fb, paths):
    d = paths.boot / "jukebox"
    d.mkdir()
    (d / "config.toml").write_text('[box]\nname = "x"\n[system]\nshutdown_command = ["true"]\n')
    (d / "hooks.py").write_text("# hooks\n")
    request(paths, 'box = "anything-new"\n')
    fb.provision(paths, reboot=False)
    assert not (paths.conf / "config.toml").is_symlink()
    assert (paths.conf / "hooks.py").read_text() == "# hooks\n"
    assert not (paths.conf / "config.local.toml").exists()


def test_cloud_init_hostname_is_pinned(fb, paths):
    (paths.etc / "cloud").mkdir()
    request(paths, f'box = "{real_box()}"\n')
    fb.provision(paths, reboot=False)
    assert "preserve_hostname: true" in (paths.etc / "cloud" / "cloud.cfg.d" / "99-jukebox-hostname.cfg").read_text()


def test_rerun_is_idempotent(fb, paths):
    request(paths, f'box = "{real_box()}"\n')
    fb.provision(paths, reboot=False)
    fb.provision(paths, reboot=False)
    assert (paths.etc / "hosts").read_text().count("127.0.1.1") == 1


@pytest.mark.parametrize("text", [
    'box = "Kitchen"\n', 'box = "küche"\n', 'box = "a b"\n', 'box = "../etc"\n', 'box = "-x"\n',
    'box = "' + "a" * 64 + '"\n', "box = 3\n", "", 'box = "ok"\nhostname = "Bad_Name"\n',
    'box = "ok"\nhostnam = "typo"\n', "box = [",
])
def test_bad_request_changes_nothing(fb, paths, text):
    request(paths, text)
    assert fb.main(["--boot", str(paths.boot)]) == 1
    assert (paths.etc / "hostname").read_text() == "raspberrypi\n"
    assert not paths.marker.exists() and not fb.calls


def test_unknown_box_lists_available_ones(fb, paths):
    request(paths, 'box = "no-such-box"\n')
    with pytest.raises(fb.FirstBootError, match="no-such-box") as exc:
        fb.provision(paths)
    assert real_box() in str(exc.value)
    assert (paths.etc / "hostname").read_text() == "raspberrypi\n"


def test_setup_failure_leaves_no_marker(fb, paths, monkeypatch):
    import subprocess

    def failing(cmd, check=True):
        if cmd[-2:] == ["setup", "--apply"]:
            raise subprocess.CalledProcessError(1, cmd)
        return 0

    monkeypatch.setattr(fb, "run", failing)
    request(paths, f'box = "{real_box()}"\n')
    with pytest.raises(subprocess.CalledProcessError):
        fb.provision(paths)
    assert not paths.marker.exists()
