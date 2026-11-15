# Spotify jukebox

An RFID jukebox for the Raspberry Pi: put a card on the reader, music plays. This is a slim rewrite of the
Spotify edition of Phoniebox v2 (starting point: `RPi-Jukebox-RFID` 2.10).

One Python process, configuration in TOML. No PHP, no MPD, no Mopidy and no shell scripts in the core.

## What it does

- **Spotify** through a local [go-librespot](https://github.com/devgianlu/go-librespot) daemon. It registers
  as a Spotify Connect device and offers a REST API on `localhost`. Spotify Premium is required.
- **Local folders** through mpv, resuming where you left off, and **web radio** streams (`stream:` cards).
- **Card readers:** USB readers (keyboard emulation) and RDM6300 (UART). Card IDs are compatible with
  Phoniebox v2, so existing cards keep working.
- **GPIO:** buttons (short, hold, repeat), rotary encoders and LEDs through libgpiod.
- **Volume potentiometer** on an ADS1115 (I2C).
- **Overlays:** `jukebox setup` maintains one marked block in `config.txt` (HiFiBerry MiniAmp profile, SPI,
  I2C), with a diff and a backup.
- **Web interface** (optional, no password): assign cards by putting them on the reader and pasting a Spotify link;
  basic controls.
- **Per-box customisation** without code changes: pinout and readers in `config.toml`, sounds per event,
  LED animations in your own `hooks.py`.

At runtime the core needs only Python >= 3.11 plus the programs `mpv` and `go-librespot`. `python3-evdev`
and `python3-libgpiod` come from apt and are needed only for USB readers and GPIO respectively.

## Status

| Part | State |
|---|---|
| Configuration, cards, actions, events, player selection, local playback, `config.txt` handling, hooks | tested (65 tests, no hardware needed) |
| Button, encoder, RDM6300 and potentiometer logic | tested against fakes |
| go-librespot REST calls (`players/spotify.py`) | endpoints and fields match go-librespot's `api-spec.yml` (v0.10.5). **Not yet run against a real daemon** from this code; `jukebox spotify-check` helps. |
| libgpiod glue, mpv glue, ADS1115, evdev, UART | **not yet run on hardware** |
| ILI9341 display (`display/`) | written, tested only without hardware (layout, colour conversion, command sequence against a fake SPI). Not run on a real panel. Covers: Spotify from go-librespot; local files from a `cover.jpg` in the folder, else a Spotify search (unverified). |
| Cover art and titles from Spotify | not wired up (go-librespot provides them over its WebSocket `/events`) |

**Known risk:** Spotify currently refuses audio keys to some accounts through the librespot family (go-librespot
issue 279). If your account is affected, Spotify cards will not play; local folders still work. See
[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#spotify).

Everything marked "unverified" is marked the same way in the documents.

## Quick start

The full guide is [docs/INSTALL.md](docs/INSTALL.md). Short version on a Pi running Raspberry Pi OS (Trixie):

```
sudo apt install -y python3-venv python3-libgpiod python3-evdev mpv alsa-utils git
git clone -b rewrite/slim-core https://github.com/thomas-wolf/spotify-jukebox
cd spotify-jukebox/slim
sudo python3 -m venv --system-site-packages /opt/jukebox/venv
sudo /opt/jukebox/venv/bin/pip install .
mkdir -p ~/.config/jukebox && cp examples/config.toml examples/cards.toml ~/.config/jukebox/
/opt/jukebox/venv/bin/jukebox setup        # shows the planned config.txt change
```

Then set up go-librespot, add cards and enable the service (see the installation guide).

## Documentation

| Document | Contents |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | Step by step from a blank Pi to a working box |
| [docs/CONFIG.md](docs/CONFIG.md) | Every setting in `config.toml` and `cards.toml`, every action |
| [docs/HARDWARE.md](docs/HARDWARE.md) | MiniAmp, overlays, pin assignment, RDM6300, ADS1115, display |
| [docs/MIGRATION.md](docs/MIGRATION.md) | Moving from Phoniebox v2: cards, folders, control cards |
| [docs/HOOKS.md](docs/HOOKS.md) | Events, startup sounds, per-box LED animations |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Troubleshooting |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Structure, tests, adding readers and players |

## License and origin

This directory is a new development next to the v2 code of the repository. The Phoniebox/RPi-Jukebox-RFID
project is MIT licensed; the repository's license file continues to apply. Spotify is a trademark of
Spotify AB. The integration uses the unofficial protocol of the librespot family and is not a product
supported by Spotify.
