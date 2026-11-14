# Spotify jukebox (v3 rewrite of the Phoniebox v2 Spotify edition)

RFID card in, music out. One Python process, TOML configuration, no PHP, no
MPD, no Mopidy, no shell scripts.

- **Spotify** through a local [go-librespot](https://github.com/devgianlu/go-librespot) daemon (Spotify Connect receiver with a REST API on localhost). Premium account required.
- **Local folders** through mpv (resume position per folder).
- **Readers:** keyboard-style USB readers and RDM6300 (UART).
- **GPIO:** buttons (short/hold/repeat), rotary encoders, LEDs, via libgpiod.
- **Potentiometer** on an ADS1115 (I2C) as volume knob.
- **Overlays:** `jukebox setup` manages one marked block in `config.txt` (HiFiBerry MiniAmp preset, SPI, I2C).
- **Per-box customisation** without touching the code: pinout and readers in `config.toml`, event sounds, and a `hooks.py` for LED animations.

Core runtime dependencies: none beyond Python >= 3.11 (`evdev` for USB readers, `gpiod` for GPIO, `mpv` and `go-librespot` as programs).

## Status

| Part | State |
|---|---|
| Config, cards, actions, events, router, local player logic, boot editing, hooks | tested (62 tests, no hardware needed) |
| Button/encoder/RDM6300/ADC logic | tested with fakes |
| go-librespot endpoints (`players/spotify.py`) | **unverified**: only REST + WebSocket existence is confirmed. Check against its `api-spec.yml`; `jukebox spotify-check` helps. |
| `GpiodBackend`, `MpvClient`, `Ads1115`, evdev/termios code | **not run on hardware yet** |
| ILI9341 display driver | not written; `display/` has the interface, boxes run with `NullDisplay` |
| Track/cover events from Spotify | not wired (needs go-librespot's WebSocket `/events`, which carries `album_cover_url`) |

## Try it

    pip install -e '.[dev]' && pytest
    mkdir -p ~/.config/jukebox && cp examples/config.toml examples/cards.toml ~/.config/jukebox/
    jukebox setup            # dry run: shows the config.txt change
    sudo jukebox setup --apply
    jukebox cards add 0415026F42 --play spotify:playlist:... --name Bedtime
    jukebox run

`packaging/` has systemd units and a go-librespot config template.
