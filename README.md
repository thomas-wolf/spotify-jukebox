# Spotify jukebox

An RFID jukebox for the Raspberry Pi: put a card on the reader, music plays.

This repository started as a fork of [Phoniebox (RPi-Jukebox-RFID)](https://github.com/MiczFlor/RPi-Jukebox-RFID) v2
and has been rewritten from scratch. Everything lives in [`slim/`](slim/README.md):

- one Python process, configuration in TOML, no PHP, MPD, Mopidy or shell scripts
- Spotify through [Soloist](https://developer.spotify.com/) (Spotify's own headless client) or [go-librespot](https://github.com/devgianlu/go-librespot) (Premium required), local folders and web radio through mpv
- USB and RDM6300 card readers, GPIO buttons, rotary encoders, LEDs, volume potentiometer (ADS1115)
- cover display (ILI9341) with configurable pins, rotation and hidden edges
- cloud sync of cards, config and music (Dropbox, OneDrive, ... through rclone)
- a small web interface for assigning cards and basic controls (optional, no password)
- device tree overlays (HiFiBerry MiniAmp, SPI, I2C) maintained by `jukebox setup`
- per-box pinout, startup sounds and LED animations without touching the code
- card IDs compatible with Phoniebox v2, so existing cards keep working

Not everything is verified on real hardware yet. The status table in [`slim/README.md`](slim/README.md#status) lists them.

## Documentation

| Document | Contents |
|---|---|
| [slim/README.md](slim/README.md) | Overview, status, quick start |
| [slim/docs/INSTALL.md](slim/docs/INSTALL.md) | From a blank Pi to a working box |
| [slim/docs/SYNC.md](slim/docs/SYNC.md) | Cards, config and music through Dropbox/OneDrive |
| [slim/docs/CONFIG.md](slim/docs/CONFIG.md) | All settings and actions |
| [slim/docs/HARDWARE.md](slim/docs/HARDWARE.md) | Overlays, pins, readers, potentiometer |
| [slim/docs/MIGRATION.md](slim/docs/MIGRATION.md) | Moving cards and settings over from v2 |
| [slim/docs/HOOKS.md](slim/docs/HOOKS.md) | Events, sounds, custom hooks |
| [slim/docs/TROUBLESHOOTING.md](slim/docs/TROUBLESHOOTING.md) | Fixing common problems |
| [slim/docs/DEVELOPMENT.md](slim/docs/DEVELOPMENT.md) | Architecture, tests, extending |

## History

The Phoniebox v2 code this started from was removed from the tree. It is still in the git history
(the last commit before the rewrite is `42d5023`) and upstream.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2017 Micz Flor and the Phoniebox contributors.
