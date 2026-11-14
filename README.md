# Spotify jukebox

An RFID jukebox for the Raspberry Pi: put a card on the reader, music plays.

This repository is a fork of [Phoniebox (RPi-Jukebox-RFID)](https://github.com/MiczFlor/RPi-Jukebox-RFID) v2.
The branch `rewrite/slim-core` replaces the Spotify edition with a slim rewrite in [`slim/`](slim/README.md):

- one Python process, configuration in TOML, no PHP, MPD, Mopidy or shell scripts
- Spotify through [go-librespot](https://github.com/devgianlu/go-librespot) (Premium required), local folders through mpv
- USB and RDM6300 card readers, GPIO buttons, rotary encoders, LEDs, volume potentiometer (ADS1115)
- device tree overlays (HiFiBerry MiniAmp, SPI, I2C) maintained by `jukebox setup`
- per-box pinout, startup sounds and LED animations without touching the code
- card IDs compatible with Phoniebox v2, so existing cards keep working

Some parts are not verified or not written yet (go-librespot REST endpoints, hardware glue, display driver).
The status table in [`slim/README.md`](slim/README.md#status) lists them.

## Documentation

| Document | Contents |
|---|---|
| [slim/README.md](slim/README.md) | Overview, status, quick start |
| [slim/docs/INSTALL.md](slim/docs/INSTALL.md) | From a blank Pi to a working box |
| [slim/docs/CONFIG.md](slim/docs/CONFIG.md) | All settings and actions |
| [slim/docs/HARDWARE.md](slim/docs/HARDWARE.md) | Overlays, pins, readers, potentiometer |
| [slim/docs/MIGRATION.md](slim/docs/MIGRATION.md) | Moving cards and settings over from v2 |
| [slim/docs/HOOKS.md](slim/docs/HOOKS.md) | Events, sounds, custom hooks |
| [slim/docs/TROUBLESHOOTING.md](slim/docs/TROUBLESHOOTING.md) | Fixing common problems |
| [slim/docs/DEVELOPMENT.md](slim/docs/DEVELOPMENT.md) | Architecture, tests, extending |

## The old code

Everything outside `slim/` is the unchanged Phoniebox v2 code and is not maintained here. The original
project's README is in the git history and upstream.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2017 Micz Flor and the Phoniebox contributors.
