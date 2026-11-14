"""Command line: run the box, manage cards, set up boot overlays."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from . import boot
from .app import App
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
    if spotify["enabled"]:
        from .players.spotify import SpotifyPlayer, http_transport
        backends["spotify"] = SpotifyPlayer(http_transport(spotify["api_url"]))
    local = cfg.section("local")
    if local["enabled"]:
        try:
            from .players.local import LocalPlayer, MpvClient
            mpv = MpvClient(local["mpv"], cfg.section("audio")["start_volume"])
            player = LocalPlayer(mpv, expand(local["root"]), cfg.data_dir / "resume.json")
            backends["folder"] = backends["file"] = player
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
                                     rdm.get("id_format", "hex")))
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


def cmd_run(args) -> int:
    cfg, app, _ = build(args.config)
    install_sounds(app)
    threads = start_inputs(cfg, app)
    hooks = cfg.section("hooks").get("file")
    if hooks:
        load_user_hooks(app, (cfg.path.parent / hooks) if cfg.path else hooks)
    signal.signal(signal.SIGTERM, lambda *_: app.bus.stop())
    signal.signal(signal.SIGINT, lambda *_: app.bus.stop())
    app.start()
    log.info("%s is ready", cfg.section("box")["name"])
    try:
        app.bus.run(app.handle)
    finally:
        for t in threads:
            t.stop()
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


def cmd_setup(args) -> int:
    cfg = load_config(args.config)
    plan = boot.plan_from_config(cfg.section("boot"))
    path = Path(args.config_txt) if args.config_txt else boot.find_config_txt()
    old = path.read_text()
    new = boot.apply_plan(old, plan)
    if new == old:
        print(f"{path}: already up to date")
        return 0
    print(boot.diff(old, new, path.name))
    if args.apply:
        backup = boot.write_config(path, new)
        print(f"written {path}" + (f" (backup: {backup})" if backup else ""))
        print("Reboot to activate the overlays.")
    else:
        print("Dry run. Add --apply to write the change (needs root).")
    return 0


def cmd_spotify_check(args) -> int:
    from .players.spotify import ENDPOINTS, http_transport
    cfg = load_config(args.config)
    call = http_transport(cfg.section("spotify")["api_url"])
    method, path = ENDPOINTS["status"]
    try:
        print(call(method, path, None))
    except PlayerError as exc:
        print(f"FAILED: {exc}")
        return 1
    return 0


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
    setup = sub.add_parser("setup", help="write overlays to config.txt (dry run by default)")
    setup.add_argument("--apply", action="store_true")
    setup.add_argument("--config-txt", help="override the config.txt path")
    setup.set_defaults(fn=cmd_setup)
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
