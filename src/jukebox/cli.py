"""Command line: run the box, manage cards, set up boot overlays."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from . import boot
from . import events as ev
from .app import App
from . import importer
from .config import ConfigError, add_card, expand, load_cards, load_config
from .events import EventBus
from .hooks import install_sounds, load_user_hooks
from .players import PlayerError, PlayerRouter

log = logging.getLogger("jukebox")
DEFAULT_CONFIG = "~/.config/jukebox/config.toml"


def build(cfg_path: str):
    cfg = load_config(cfg_path)
    cards_path = cfg.path.with_name("cards.toml") if cfg.path else expand("~/.config/jukebox/cards.toml")
    bus = EventBus()
    backends = {}
    spotify = cfg.section("spotify")
    if spotify["enabled"] and spotify["backend"] == "soloist":
        from .players.soloist import SoloistClient, SoloistPlayer, parse_ws
        try:
            client = SoloistClient(*parse_ws(spotify["soloist_ws"]))
        except PlayerError as exc:
            raise ConfigError(str(exc)) from None
        client.start()
        backends["spotify"] = SoloistPlayer(client)
    elif spotify["enabled"]:
        from .players.spotify import SpotifyPlayer, http_transport
        backends["spotify"] = SpotifyPlayer(http_transport(spotify["api_url"]))
    local = cfg.section("local")
    if local["enabled"]:
        try:
            from .players.local import LocalPlayer, MpvClient
            mpv = MpvClient(local["mpv"], cfg.section("audio")["start_volume"])
            player = LocalPlayer(mpv, expand(local["root"]), cfg.data_dir / "resume.json")
            backends["folder"] = backends["file"] = backends["stream"] = player
        except PlayerError as exc:
            log.error("local player disabled: %s", exc)
    app = App(cfg, load_cards(cards_path), PlayerRouter(backends), bus)
    app.leds = {}  # filled by GPIO setup, used by hook files
    return cfg, app, cards_path


def start_inputs(cfg, app):
    threads = []
    readers = cfg.section("readers")
    usb = readers.get("usb", {})
    if usb.get("enabled"):
        from .inputs.usb_reader import UsbReader
        threads.append(UsbReader(app.bus, usb["device_name"]))
    rdm = readers.get("rdm6300", {})
    if rdm.get("enabled"):
        from .inputs.rdm6300 import Rdm6300Reader
        threads.append(Rdm6300Reader(app.bus, rdm.get("port", "/dev/serial0"),
                                     rdm.get("id_format", "raw")))
    gpio_cfg = cfg.section("gpio")
    if gpio_cfg and gpio_cfg.get("enabled", True):
        from .inputs.gpio import GpioInputs
        gpio = GpioInputs(app.bus, gpio_cfg)
        app.leds = gpio.leds
        threads.append(gpio)
    adc = cfg.section("adc")
    if adc.get("enabled"):
        from .inputs.adc import Ads1115, VolumeKnob
        chip = Ads1115(adc.get("bus", 1), adc.get("address", 0x48))
        channel = adc.get("channel", 0)
        threads.append(VolumeKnob(app.bus, lambda: chip.read_raw(channel),
                                  full_scale=adc.get("full_scale", 26400)))
    for t in threads:
        t.start()
    return threads


def build_syncer(cfg, cards_path):
    from .config import ConfigError
    from .sync import Syncer, SyncSettings
    try:
        settings = SyncSettings.from_section(cfg.section("sync"))
    except ConfigError as exc:
        log.error("sync disabled: %s", exc)
        return None
    config_dir = cfg.path.parent if cfg.path else expand("~/.config/jukebox")
    return Syncer(settings, cfg.section("box")["name"], config_dir, cards_path,
                  expand(cfg.section("local")["root"]), cfg.data_dir)


def cmd_sync(args) -> int:
    cfg = load_config(args.config)
    cards_path = cfg.path.with_name("cards.toml") if cfg.path else expand("~/.config/jukebox/cards.toml")
    if not cfg.section("sync").get("remote"):
        print('error: [sync] remote is not set (for example remote = "dropbox:Jukebox")')
        return 1
    syncer = build_syncer(cfg, cards_path)
    if syncer is None:
        return 1
    from .sync import SyncError
    if args.check:
        try:
            print(syncer.rclone.check("version").splitlines()[0])
            syncer.rclone.check("lsf", syncer.s.remote, "--max-depth", "1")
            print(f"ok: {syncer.s.remote} is reachable")
        except SyncError as exc:
            print(f"FAILED: {exc}")
            return 1
        return 0
    parts = tuple(p for p in args.only.split(",") if p) if args.only else ("cards", "config", "music")
    bad = [p for p in parts if p not in ("cards", "config", "music")]
    if bad:
        print(f"error: unknown part {bad[0]!r} (cards, config, music)")
        return 1
    res = syncer.run_once(parts, dry_run=args.dry_run)
    for m in res.messages:
        print(m)
    for e in res.errors:
        print(f"error: {e}")
    if args.dry_run:
        print("dry run: nothing was changed")
    elif res.cards_changed:
        print("cards changed: restart the service (or wait for the next sync of the running box)")
    return 1 if res.errors else 0


def fix_runtime_dir(environ=None, uid: int | None = None) -> None:
    """Point XDG_RUNTIME_DIR at /run/user/<our uid> (PipeWire/Pulse socket for mpv and the sounds).

    The units used to set it with %U, which a *system* unit resolves to 0 (root), so mpv looked in
    /run/user/0 ("Failed to create secure directory (/run/user/0/pulse)"). A value that names another
    user's directory is replaced; a deliberate other value is left alone."""
    environ = os.environ if environ is None else environ
    uid = os.getuid() if uid is None else uid
    if uid == 0:
        return
    if environ.get("XDG_RUNTIME_DIR") in (None, "", "/run/user/0"):
        environ["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"


def cmd_run(args) -> int:
    fix_runtime_dir()
    cfg, app, cards_path = build(args.config)
    from .pins import check_pins
    for problem in check_pins(cfg).problems:
        logging.getLogger("jukebox.pins").warning("%s", problem.message)
    install_sounds(app)
    threads = start_inputs(cfg, app)
    hooks = cfg.section("hooks").get("file")
    if hooks:
        load_user_hooks(app, (cfg.path.parent / hooks) if cfg.path else hooks)
    display = None
    if cfg.section("display").get("enabled"):
        from .display import bind, build_display
        display = build_display(cfg.section("display"), cfg.path.resolve().parent if cfg.path else None,
                                cfg.path.parent if cfg.path else None)
        bind(display, app.bus)
        from .display import bind_update_notice
        bind_update_notice(display, app.bus)
    app.display = display                    # hooks may show a short message (see boxes/pferdeanhaenger/hooks.py)
    # Track information (title, cover) is reported whether or not the box has a display: the web page and Home
    # Assistant use it too.
    spotify_cfg = cfg.section("spotify")
    soloist = spotify_cfg["backend"] == "soloist"
    if spotify_cfg["enabled"] and soloist:
        from .players.trackinfo import SoloistTrackReporter
        app.players.backend("spotify").client.listeners.append(SoloistTrackReporter(app.bus).on_state)
    elif spotify_cfg["enabled"]:
        from .players.spotify import http_transport
        from .players.trackinfo import SpotifyTrackPoller
        poller = SpotifyTrackPoller(app.bus, http_transport(spotify_cfg["api_url"]))
        poller.start()
        threads.append(poller)
    local_player = app.players.backend("folder")
    if local_player is not None and hasattr(local_player, "current_track"):
        from .covers import CoverResolver, SpotifySearch
        from .players.trackinfo import LocalTrackPoller
        covers_cfg = cfg.section("covers")
        search = None
        # the search needs go-librespot's token endpoint; Soloist offers none
        if covers_cfg["spotify_search"] and spotify_cfg["enabled"] and not soloist:
            from .players.spotify import http_transport
            call = http_transport(cfg.section("spotify")["api_url"])
            search = SpotifySearch(lambda: (call("POST", "/token", None) or {}).get("token"))
        resolver = CoverResolver(cfg.data_dir, search, write_to_folder=covers_cfg["write_to_folder"])
        local_poller = LocalTrackPoller(app.bus, local_player, resolver, expand(cfg.section("local")["root"]))
        local_poller.start()
        threads.append(local_poller)
    if cfg.section("sync").get("enabled"):
        from .sync import SyncThread
        syncer = build_syncer(cfg, cards_path)
        if syncer is not None:
            from . import events as ev
            app.bus.subscribe(ev.CARDS_CHANGED, lambda _e: app.replace_cards(load_cards(cards_path)))
            sync_thread = SyncThread(syncer, app.bus)
            sync_thread.start()
            threads.append(sync_thread)
    web = None
    web_cfg = cfg.section("web")
    if web_cfg["enabled"]:
        from .web import Web
        try:
            web = Web(app, cards_path, expand(cfg.section("local")["root"]), web_cfg["host"], web_cfg["port"])
            web.start()
        except OSError as exc:
            log.error("web interface disabled: %s", exc)
    from .playtime import Playtime
    app.playtime = Playtime(cfg.data_dir / "playtime.json")  # read by build_metrics
    app.playtime.bind(app.bus)
    from .history import PlayHistory
    app.history = PlayHistory(cfg.data_dir / "history.json")  # read by build_metrics
    app.history.bind(app.bus)
    mqtt_cfg = cfg.section("mqtt")
    if mqtt_cfg["enabled"]:
        from .metrics import build_metrics, soloist_build_date
        from .mqtt_export import MqttExporter, make_paho_client
        box = cfg.section("box")["name"]
        try:
            client = make_paho_client(mqtt_cfg["host"], mqtt_cfg["port"], mqtt_cfg["username"],
                                      mqtt_cfg["password"], box)
        except RuntimeError as exc:
            log.error("%s", exc)
        else:
            exporter = MqttExporter(client, lambda: build_metrics(app, soloist_built=soloist_build_date()), box,
                                    backend=cfg.section("spotify")["backend"],
                                    discovery_prefix=mqtt_cfg["discovery_prefix"],
                                    topic_prefix=mqtt_cfg["topic_prefix"], interval=float(mqtt_cfg["interval"]),
                                    host=mqtt_cfg["host"], port=int(mqtt_cfg["port"]))
            exporter.start()
            threads.append(exporter)
    signal.signal(signal.SIGTERM, lambda *_: app.bus.stop())
    signal.signal(signal.SIGINT, lambda *_: app.bus.stop())
    app.start()
    from .version import check_update, installed_build
    update = check_update(cfg.data_dir)
    log.info("%s is ready (build %s)", cfg.section("box")["name"], installed_build() or "unknown")
    if update:
        log.warning("updated from build %s to %s", *update)
        app.bus.post(ev.UPDATED, old=update[0], new=update[1])
    try:
        app.bus.run(app.handle)
    finally:
        for t in threads:
            t.stop()
        if web:
            web.stop()
        if display:
            display.close()
        app.players.close()
    return 0


def cmd_cards(args) -> int:
    cfg = load_config(args.config)
    cards_path = cfg.path.with_name("cards.toml") if cfg.path else expand("~/.config/jukebox/cards.toml")
    if args.cards_cmd == "list":
        for card in load_cards(cards_path).values():
            print(f"{card.id}\t{card.name}\t{card.play or 'action:' + (card.action or '')}")
    else:
        add_card(cards_path, args.id, name=args.name or "", play=args.play, action=args.action)
        print(f"added {args.id}")
    return 0


def cmd_import_v2(args) -> int:
    cfg = load_config(args.config)
    cards_path = cfg.path.with_name("cards.toml") if cfg.path else expand("~/.config/jukebox/cards.toml")
    try:
        res = importer.convert(Path(args.source).expanduser())
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1
    existing = {k.lower() for k in load_cards(cards_path)}
    fresh = [e for e in res.entries if e.id.lower() not in existing]
    dup = len(res.entries) - len(fresh)
    print(f"{len(res.entries)} cards found: {len(fresh)} new, {dup} already in {cards_path}")
    print(f"{len(res.unused)} ids in v2 were never assigned (ignored)")
    for card_id, why in res.skipped:
        print(f"skipped {card_id}: {why}")
    if not args.apply:
        print("dry run; add --apply to write the cards")
        return 0
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cards_path, "a", encoding="utf-8") as fh:
        fh.write("\n" + importer.render(fresh))
    print(f"written to {cards_path}; restart the service")
    return 0


def cmd_display_test(args) -> int:
    """Draw a calibration picture: red = edge of the panel, green = visible area, yellow = corners."""
    from .display.settings import DisplaySettings
    cfg = load_config(args.config)
    try:
        settings = DisplaySettings.from_section(cfg.section("display"))
        from .display.render import Renderer
        renderer = Renderer(settings)
        cover = None
        if args.cover:
            from PIL import Image
            cover = Image.open(args.cover).convert("RGB")
        picture = renderer.ruler() if args.ruler else renderer.test_pattern(cover)
    except (ConfigError, ImportError, OSError) as exc:
        print(f"error: {exc}")
        return 1
    if args.save:
        picture.save(args.save)
        print(f"saved {args.save} ({picture.size[0]}x{picture.size[1]})")
        return 0
    from .display.ili9341 import ILI9341
    try:
        panel = ILI9341(settings)
    except Exception as exc:
        print(f"error: {exc}")
        return 1
    panel.show(picture)
    print("test picture shown; press Ctrl-C to clear")
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        panel.close()
    return 0


def cmd_setup(args) -> int:
    cfg = load_config(args.config)
    plan = boot.plan_from_config(cfg.section("boot"))
    path = Path(args.config_txt) if args.config_txt else boot.find_config_txt()
    modules_path = Path(args.modules_file) if args.modules_file else boot.MODULES_FILE
    old = path.read_text()
    new = boot.apply_plan(old, plan)
    modules = boot.modules_text(plan)
    modules_current = modules_path.read_text() if modules_path.exists() else None
    missing = boot.overlay_missing(plan, path)
    changes = new != old or (modules is not None and modules != modules_current) or bool(missing)
    if not changes:
        print(f"{path}: already up to date")
        return 0
    if new != old:
        print(boot.diff(old, new, path.name))
    if modules is not None and modules != modules_current:
        print(f"{modules_path} (new): {modules.strip().splitlines()[-1]}")
    for name in missing:
        print(f"{boot.overlay_target(path)}/{name}.dtbo: to be built with dtc")
    if args.apply:
        try:
            for name in missing:
                print(f"built {boot.build_overlay(name, boot.overlay_target(path))}")
            if new != old:
                backup = boot.write_config(path, new)
                print(f"written {path}" + (f" (backup: {backup})" if backup else ""))
            if modules is not None and modules != modules_current:
                modules_path.write_text(modules)
                print(f"written {modules_path}")
        except boot.BootConfigError as exc:
            print(f"error: {exc}")
            return 1
        except PermissionError as exc:
            print(f"error: {exc.filename or exc}: permission denied. Writing the boot files needs root. Run:\n"
                  f"  sudo {sys.executable} -m jukebox -c {cfg.path or DEFAULT_CONFIG} setup --apply")
            return 1
        print("Reboot to activate the overlays.")
    else:
        print("Dry run. Add --apply to write the change (needs root).")
    return 0


def cmd_pins(args) -> int:
    from .pins import check_pins, format_report
    cfg = load_config(args.config)
    report = check_pins(cfg)
    print(format_report(report, cfg))
    return 1 if report.errors else 0


def cmd_spotify_check(args) -> int:
    cfg = load_config(args.config)
    if cfg.section("spotify")["backend"] == "soloist":
        return _soloist_check(cfg)
    from .players.spotify import ENDPOINTS, http_transport
    call = http_transport(cfg.section("spotify")["api_url"])
    method, path = ENDPOINTS["status"]
    try:
        print(call(method, path, None))
    except PlayerError as exc:
        print(f"FAILED: {exc}")
        return 1
    return 0


def _soloist_check(cfg) -> int:
    """Connect to Soloist, wait for login state and the playback state, print both."""
    import time
    from .players.soloist import SoloistClient, parse_ws, track_from_state
    try:
        client = SoloistClient(*parse_ws(cfg.section("spotify")["soloist_ws"]))
    except PlayerError as exc:
        print(f"FAILED: {exc}")
        return 1
    client.start()
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline and (client.state is None or client.logged_in is None):
        time.sleep(0.1)
    reachable = client.connected or client.state is not None or client.logged_in is not None
    state, logged_in = client.state, client.logged_in
    client.stop()
    if not reachable:
        print(f"FAILED: Soloist is not reachable at {client.host}:{client.port} (is it started with --ws?)")
        return 1
    print(f"logged in: {logged_in}")
    if state:
        print(f"status: {state.get('status')}  volume: {state.get('volume')}  active: {state.get('is_active')}")
        print(f"track: {track_from_state(state)}")
    return 0 if logged_in else 1


def cmd_adc_check(args) -> int:
    import time
    from .inputs.adc import Ads1115, to_percent
    cfg = load_config(args.config)
    adc = cfg.section("adc")
    chip = Ads1115(adc.get("bus", 1), adc.get("address", 0x48))
    full = adc.get("full_scale", 26400)
    print("Turn the knob to both ends; Ctrl-C to stop.")
    try:
        while True:
            raw = chip.read_raw(adc.get("channel", 0))
            print(f"raw={raw:6d}  -> {to_percent(raw, full):3d}%", end="\r")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jukebox")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    cards = sub.add_parser("cards")
    csub = cards.add_subparsers(dest="cards_cmd", required=True)
    csub.add_parser("list")
    add = csub.add_parser("add")
    add.add_argument("id")
    add.add_argument("--name")
    target = add.add_mutually_exclusive_group(required=True)
    target.add_argument("--play", help="spotify:... | folder:path | file:path")
    target.add_argument("--action")
    cards.set_defaults(fn=cmd_cards)
    imp = sub.add_parser("import-v2", help="import cards from a Phoniebox v2 copy (dry run by default)")
    imp.add_argument("source", help="v2 root, its shared/ folder, or a folder with copies of shortcuts/ and audiofolders/")
    imp.add_argument("--apply", action="store_true")
    imp.set_defaults(fn=cmd_import_v2)
    sy = sub.add_parser("sync", help="synchronise cards, config and music with the cloud (rclone) once")
    sy.add_argument("--dry-run", action="store_true", help="show what would be done")
    sy.add_argument("--check", action="store_true", help="only test that rclone and the remote work")
    sy.add_argument("--only", metavar="PARTS", help="comma separated: cards,config,music")
    sy.set_defaults(fn=cmd_sync)
    dt = sub.add_parser("display-test", help="show a calibration picture (rotation, covered edges)")
    dt.add_argument("--save", metavar="PNG", help="write the picture to a file instead of the panel")
    dt.add_argument("--cover", metavar="IMAGE", help="use this picture as the cover")
    dt.add_argument("--ruler", action="store_true",
                    help="numbered frames from each edge: the lowest number you can read per side = pixels hidden there")
    dt.set_defaults(fn=cmd_display_test)
    setup = sub.add_parser("setup", help="write overlays to config.txt (dry run by default)")
    setup.add_argument("--apply", action="store_true")
    setup.add_argument("--config-txt", help="override the config.txt path")
    setup.add_argument("--modules-file", help="override /etc/modules-load.d/jukebox.conf")
    setup.set_defaults(fn=cmd_setup)
    sub.add_parser("pins", help="list the pin assignment and report conflicts").set_defaults(fn=cmd_pins)
    sub.add_parser("spotify-check").set_defaults(fn=cmd_spotify_check)
    sub.add_parser("adc-check").set_defaults(fn=cmd_adc_check)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return args.fn(args)
    except (ConfigError, boot.BootConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
