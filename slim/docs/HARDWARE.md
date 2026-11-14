# Hardware and overlays

## HiFiBerry MiniAmp

- Overlay: `dtoverlay=hifiberry-dac`. The on-board audio output must be off as well (remove or comment out
  `dtparam=audio=on`). `jukebox setup` does both for the `hifiberry-miniamp` profile.
- The MiniAmp has **no hardware mixer**. Volume is therefore controlled in software by go-librespot and mpv.
  That fits the jukebox's volume logic; there is no ALSA softvol configuration to maintain.
- The DAC occupies the I2S pins GPIO 18 to 21. No button or LED may use these pins.
- After the reboot `aplay -l` shows a card `sndrpihifiberry`.

Whether go-librespot plays on the DAC without further settings (`audio_device: default`) depends on the DAC
being the only card. With the on-board audio switched off that should be the case **(check on the box)**.
Otherwise enter the ALSA name from `aplay -L` in `go-librespot/config.yml`.

### Overlays and Pi versions

Overlays depend on the Pi model and the kernel. That is why the choice lives in each box's `config.toml`
(`[boot]`) and not in the code:

```toml
[boot]
audio = "hifiberry-miniamp"
spi = true
i2c = true
extra = [
  "dtoverlay=something",
  { model = "pi5", line = "dtparam=pciex1" },   # applies on the Pi 5 only
]
```

`jukebox setup` writes everything into one marked block of `config.txt`:

```
# >>> jukebox managed block (do not edit) >>>
dtoverlay=hifiberry-dac
dtparam=spi=on
# <<< jukebox managed block <<<
```

- The command is **idempotent**: running it repeatedly gives the same result; changes in `config.toml` replace the block.
- Lines outside the block are left alone, apart from commenting out `dtparam=audio=on`.
- Before the first change, `config.txt.jukebox.bak` is created **once**.
- The tool finds the path itself: `/boot/firmware/config.txt` (current Raspberry Pi OS), otherwise `/boot/config.txt`.
- With `i2c = true` it also writes `/etc/modules-load.d/jukebox.conf` containing `i2c-dev`, so that `/dev/i2c-1` exists.
- Without `--apply` it only shows the diff.

Other audio hardware: another profile is one line in `AUDIO_PRESETS` in `src/jukebox/boot.py`, or leave
`audio` out and put the overlay in `extra`.

## Pin assignment (BCM)

These pins are taken by hardware or overlays. The example configuration avoids them.

| Pins | Used by | Note |
|---|---|---|
| 18, 19, 20, 21 | I2S of the MiniAmp | do not use |
| 14 (TX), 15 (RX) | UART (RDM6300) | only if the RDM6300 is used |
| 2 (SDA), 3 (SCL) | I2C (ADS1115) | only with the potentiometer. **GPIO 3 was often the shutdown button in v2. That does not work with I2C.** |
| 7, 8, 9, 10, 11 | SPI0 (display) | only with a display |
| 17, 25 | Display DC and RESET | suggestion for the ILI9341 (driver not written yet) |

Free and used in the example: 5, 22, 23, 24, 26, 27.

## Buttons, encoders, LEDs

- Wire buttons to ground and leave `pull = "up"` (the default). The internal pull-up is enough.
- Rotary encoder: common pin to ground, A and B to two GPIOs. If it turns the wrong way, swap `cw` and
  `ccw` in the configuration.
- LED: GPIO -> series resistor (e.g. 330 ohm) -> LED -> ground. It is driven only through hooks, see [HOOKS.md](HOOKS.md).
- The service runs as a user in the group `gpio`. Pins held by another process (for example an old Phoniebox
  service that is still running) cannot be opened.

## RDM6300 (125 kHz reader)

Wiring:

| RDM6300 | Raspberry Pi |
|---|---|
| 5V | 5 V (pin 2 or 4) |
| GND | GND |
| TX | RXD, GPIO 15 (pin 10) |

**Voltage level:** The reader is powered with 5 V. Whether its TX output is 3.3 V depends on your module.
Measure it, or use a level shifter or voltage divider before connecting it to the Pi. The Pi's GPIO inputs
tolerate 3.3 V.

Enable the serial port: `sudo raspi-config` -> Interface Options -> Serial Port. Answer "No" to the login
shell question and "Yes" to the serial hardware question **(menu text unverified)**. Then reboot. The port is
then called `/dev/serial0`.

Quick test: `sudo cat /dev/serial0` shows characters when you put a card on the reader (binary characters
with the text of the card ID in between). On models with Bluetooth, `/dev/serial0` may point to the mini UART.
At 9600 baud that should be enough **(unverified)**.

The `id_format` setting controls the card ID format, see [CONFIG.md](CONFIG.md). For existing v2 cards keep `raw`.

## USB reader

Works if the reader identifies itself as a keyboard and ends the card ID with Enter. The device name for
`device_name` is shown by:

```
python3 -c "import evdev; [print(evdev.InputDevice(p).name) for p in evdev.list_devices()]"
```

RC522 and PN532 (SPI/I2C), which v2 supported, are not supported yet.

## Volume potentiometer with ADS1115

| ADS1115 | Connection |
|---|---|
| VDD | 3.3 V |
| GND | GND |
| SDA | GPIO 2 (pin 3) |
| SCL | GPIO 3 (pin 5) |
| ADDR | GND -> address `0x48` |
| A0 | wiper of the potentiometer |

The two outer terminals of the potentiometer go to 3.3 V and GND. In `config.toml`: `[adc] enabled = true`
and `[boot] i2c = true`, then `jukebox setup --apply` and reboot. Whether the chip answers is shown by
`sudo apt install -y i2c-tools && i2cdetect -y 1` (expect `48`). Calibration is done with
`jukebox adc-check`, see [CONFIG.md](CONFIG.md).

## Display (ILI9341 over SPI)

**Not implemented yet.** Only the interface exists (`src/jukebox/display/`): a driver receives title and cover
URL through the `track` event. Still open are the driver itself and wiring up the cover data from go-librespot
(the WebSocket `/events` provides `album_cover_url`). For the driver I need resolution, rotation and the pins
for DC and RESET.
