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


def test_unit_has_no_ordering_that_can_form_a_cycle():
    """cloud-final.service is After=multi-user.target; ordering this WantedBy=multi-user.target unit after it
    (or after anything that follows multi-user.target) makes systemd drop the job (seen on a real box)."""
    unit = SCRIPT.with_name("jukebox-firstboot.service").read_text()
    order = [line for line in unit.splitlines() if line.startswith("After=")]
    assert order, "expected an After= line"
    for line in order:
        for dep in line.removeprefix("After=").split():
            assert dep in {"local-fs.target"}, f"After={dep} may form a cycle with multi-user.target"
    assert "WantedBy=multi-user.target" in unit


# --- Wi-Fi as a plain NetworkManager profile (the cloud-init / netplan route lost it on real boxes) ---------------

def nm_file(paths):
    return paths.etc / "NetworkManager" / "system-connections" / "jukebox-wifi.nmconnection"


def test_no_wifi_keys_writes_no_profile(fb, paths):
    request(paths, f'box = "{real_box()}"\n')
    fb.provision(paths, reboot=False)
    assert not nm_file(paths).exists()


def test_wifi_profile_is_written_private_and_complete(fb, paths):
    request(paths, f'box = "{real_box()}"\nwifi_ssid = "HomeOffice"\nwifi_password = "secret-pass"\n'
                   'wifi_country = "DE"\n')
    fb.provision(paths, reboot=False)
    f = nm_file(paths)
    text = f.read_text()
    assert (f.stat().st_mode & 0o777) == 0o600
    assert "id=HomeOffice" in text and "ssid=HomeOffice" in text and "type=wifi" in text
    assert "key-mgmt=wpa-psk" in text and "psk=secret-pass" in text and "autoconnect=true" in text
    assert ["raspi-config", "nonint", "do_wifi_country", "DE"] in fb.calls
    assert ["nmcli", "connection", "reload"] in fb.calls
    # the Wi-Fi is set up before the overlays and the reboot
    assert fb.calls.index(["nmcli", "connection", "reload"]) < fb.calls.index(
        [str(paths.venv / "bin" / "jukebox"), "-c", str(paths.conf / "config.toml"), "setup", "--apply"])


def test_wifi_rerun_replaces_the_profile(fb, paths):
    request(paths, f'box = "{real_box()}"\nwifi_ssid = "Net"\nwifi_password = "password-one"\n')
    fb.provision(paths, reboot=False)
    uuid1 = [ln for ln in nm_file(paths).read_text().splitlines() if ln.startswith("uuid=")]
    request(paths, f'box = "{real_box()}"\nwifi_ssid = "Net"\nwifi_password = "password-two"\n')
    fb.provision(paths, reboot=False)
    text = nm_file(paths).read_text()
    assert "psk=password-two" in text and "password-one" not in text
    assert uuid1 == [ln for ln in text.splitlines() if ln.startswith("uuid=")]
    assert len(list(nm_file(paths).parent.iterdir())) == 1


def test_open_wifi_has_no_security_section(fb, paths):
    request(paths, f'box = "{real_box()}"\nwifi_ssid = "Cafe"\n')
    fb.provision(paths, reboot=False)
    assert "wifi-security" not in nm_file(paths).read_text()
    assert not any(c[:3] == ["raspi-config", "nonint", "do_wifi_country"] for c in fb.calls)


def test_wifi_special_characters_are_escaped(fb, paths):
    request(paths, f'box = "{real_box()}"\nwifi_ssid = " my\\\\net "\nwifi_password = "pa\\\\ss word#1"\n')
    fb.provision(paths, reboot=False)
    text = nm_file(paths).read_text()
    assert "ssid=\\smy\\\\net\\s" in text and "psk=pa\\\\ss word#1" in text


@pytest.mark.parametrize("extra", [
    'wifi_password = "password1"\n',                          # password without ssid
    'wifi_ssid = ""\n', 'wifi_ssid = 5\n', 'wifi_ssid = "' + "a" * 33 + '"\n', 'wifi_ssid = "a\\nb"\n',
    'wifi_ssid = "x"\nwifi_password = "short"\n', 'wifi_ssid = "x"\nwifi_password = "' + "a" * 64 + '"\n',
    'wifi_ssid = "x"\nwifi_password = "password1"\nwifi_country = "de"\n',
    'wifi_ssid = "x"\nwifi_password = "password1"\nwifi_country = "DEU"\n',
    'wifi_ssid = "x"\nwifi_pasword = "typo"\n',
])
def test_bad_wifi_changes_nothing(fb, paths, extra):
    request(paths, f'box = "{real_box()}"\n{extra}')
    assert fb.main(["--boot", str(paths.boot)]) == 1
    assert (paths.etc / "hostname").read_text() == "raspberrypi\n"
    assert not paths.marker.exists() and not fb.calls and not nm_file(paths).exists()


def test_wifi_64_hex_key_is_accepted(fb, paths):
    request(paths, f'box = "{real_box()}"\nwifi_ssid = "x"\nwifi_password = "{"ab12" * 16}"\n')
    fb.provision(paths, reboot=False)
    assert f"psk={'ab12' * 16}" in nm_file(paths).read_text()


def test_image_installs_the_wireplumber_volume_setting():
    """WirePlumber's default sink volume (0.40 in wpctl) made new boxes quiet; the image ships a setting for 1.0."""
    files = SCRIPT.parent
    conf = (files / "51-jukebox-volume.conf").read_text()
    assert "device.routes.default-sink-volume = 1.0" in conf
    run_sh = (files.parent / "01-run.sh").read_text()
    assert "files/51-jukebox-volume.conf" in run_sh and "/etc/wireplumber/wireplumber.conf.d/" in run_sh
