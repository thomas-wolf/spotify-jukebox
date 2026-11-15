import pytest

from fakes import FakePlayer
from jukebox import boot
from jukebox.app import App
from jukebox.config import load_config
from jukebox.events import Event, EventBus
from jukebox.hooks import install_sounds, load_user_hooks
from jukebox.players import PlayerRouter

PI_CONFIG = """\
# For more options see the docs
dtparam=audio=on
dtparam=i2c_arm=off
arm_64bit=1

[cm4]
otg_mode=1

[all]
"""


def plan(**kw):
    return boot.plan_from_config(kw)


def test_miniamp_preset_uses_documented_overlay_and_disables_onboard_audio():
    new = boot.apply_plan(PI_CONFIG, plan(audio="hifiberry-miniamp", spi=True))
    assert "dtoverlay=hifiberry-dac" in new
    assert "dtparam=spi=on" in new
    assert "#dtparam=audio=on  # disabled by jukebox setup" in new
    assert "arm_64bit=1" in new and "[cm4]\notg_mode=1" in new   # rest untouched


def test_apply_is_idempotent_and_replaces_block():
    p = plan(audio="hifiberry-miniamp", spi=True)
    once = boot.apply_plan(PI_CONFIG, p)
    assert boot.apply_plan(once, p) == once
    changed = boot.apply_plan(once, plan(audio="hifiberry-miniamp"))
    assert "dtparam=spi=on" not in changed
    assert changed.count(boot.BEGIN) == 1


def test_model_specific_lines_use_filters_and_return_to_all():
    p = plan(extra=["dtoverlay=a", {"model": "pi5", "line": "dtparam=pciex1"}])
    block = boot.render_block(p)
    assert block.index("dtoverlay=a") < block.index("[pi5]") < block.index("dtparam=pciex1") < block.index("[all]")


def test_i2c_requests_module_and_spi_flag():
    p = plan(i2c=True)
    assert "dtparam=i2c_arm=on" in p.lines and p.modules == ["i2c-dev"]


def test_invalid_boot_config_rejected():
    with pytest.raises(boot.BootConfigError):
        plan(audio="nonsense")
    with pytest.raises(boot.BootConfigError):
        plan(extra=["bad\nline"])
    with pytest.raises(boot.BootConfigError):
        plan(extra=[42])


def test_write_creates_single_backup(tmp_path):
    f = tmp_path / "config.txt"
    f.write_text(PI_CONFIG)
    first = boot.write_config(f, "one\n")
    assert first is not None and first.read_text() == PI_CONFIG
    assert boot.write_config(f, "two\n") is None           # backup of the original stays
    assert first.read_text() == PI_CONFIG and f.read_text() == "two\n"


def test_empty_config_txt():
    assert boot.apply_plan("", plan(audio="hifiberry-dac")).startswith(boot.BEGIN)


# -- hooks ----------------------------------------------------------------------
def make_app(extra=""):
    cfg = load_config(None)
    return App(cfg, {}, PlayerRouter({"spotify": FakePlayer()}), EventBus())


def test_sounds_play_on_event_and_missing_file_is_harmless(tmp_path):
    app = make_app()
    sound = tmp_path / "start.mp3"
    sound.write_text("x")
    app.cfg.raw["sounds"]["events"] = {"boot": str(sound), "playing": str(tmp_path / "gone.mp3")}
    launched = []
    install_sounds(app, popen=lambda cmd, **kw: launched.append(cmd))
    app.bus.dispatch(Event("boot"))
    app.bus.dispatch(Event("playing"))
    assert launched == [["mpv", "--no-video", "--really-quiet", str(sound)]]


def test_user_hooks_subscribe(tmp_path):
    hooks = tmp_path / "hooks.py"
    hooks.write_text("def setup(app):\n    app.bus.subscribe('playing', lambda e: app.seen.append(e.name))\n")
    app = make_app()
    app.seen = []
    load_user_hooks(app, hooks)
    app.bus.dispatch(Event("playing"))
    assert app.seen == ["playing"]


@pytest.mark.parametrize("body", ["def setup(app):\n    raise RuntimeError('x')\n", "this is not python(", "x = 1\n"])
def test_broken_hooks_never_raise(tmp_path, body):
    hooks = tmp_path / "hooks.py"
    hooks.write_text(body)
    load_user_hooks(make_app(), hooks)


def test_failing_handler_does_not_stop_others():
    bus = EventBus()
    got = []
    bus.subscribe("x", lambda e: 1 / 0)
    bus.subscribe("x", lambda e: got.append(1))
    bus.dispatch(Event("x"))
    assert got == [1]


def test_missing_hooks_file_is_harmless(tmp_path):
    load_user_hooks(make_app(), tmp_path / "none.py")


def test_modules_file_only_when_needed():
    assert boot.modules_text(plan(audio="hifiberry-miniamp")) is None
    assert boot.modules_text(plan(i2c=True)) == "# written by jukebox setup\ni2c-dev\n"


def test_hook_can_register_custom_action(tmp_path):
    hooks = tmp_path / "hooks.py"
    hooks.write_text("def setup(app):\n    app.actions['nachtmodus'] = lambda: app.set_volume(10)\n")
    app = make_app()
    load_user_hooks(app, hooks)
    app.handle(Event("action", {"name": "nachtmodus", "args": {}}))
    assert app.players.volume == 10


def test_expand_uses_sudo_users_home(monkeypatch):
    import os, pwd
    from jukebox import config
    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(pwd, "getpwnam", lambda n: type("P", (), {"pw_dir": "/home/alice"})())
    assert str(config.expand("~/.config/jukebox/config.toml")) == "/home/alice/.config/jukebox/config.toml"
    assert str(config.expand("/etc/x")) == "/etc/x"
    monkeypatch.setattr(os, "geteuid", lambda: 1000)             # not root: normal behaviour
    assert config.expand("~/x") == config.Path("~/x").expanduser()


def test_setup_apply_without_root_explains(tmp_path, monkeypatch, capsys):
    from jukebox import boot
    from jukebox.cli import main
    cfg = tmp_path / "c.toml"
    cfg.write_text('[boot]\naudio = "hifiberry-miniamp"\n')
    txt = tmp_path / "config.txt"
    txt.write_text("dtparam=audio=on\n")

    def deny(path, text):
        raise PermissionError(13, "Permission denied", str(path) + ".jukebox.bak")
    monkeypatch.setattr(boot, "write_config", deny)
    assert main(["-c", str(cfg), "setup", "--apply", "--config-txt", str(txt),
                 "--modules-file", str(tmp_path / "m.conf")]) == 1
    out = capsys.readouterr().out
    assert "needs root" in out and "-m jukebox" in out and "setup --apply" in out


def test_power_and_uart_presets():
    p = plan(power="onoff-shim", uart=True)
    assert "dtoverlay=gpio-poweroff,gpiopin=4,active_low=1,input=1" in p.lines
    assert "enable_uart=1" in p.lines
    with pytest.raises(boot.BootConfigError):
        plan(power="nope")
