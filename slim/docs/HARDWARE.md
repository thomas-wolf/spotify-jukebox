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
uart = true                 # enable_uart=1, for the RDM6300 on the serial port
power = "onoff-shim"        # Pimoroni OnOff SHIM, see below
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

Serial console: `jukebox setup` writes `enable_uart=1` (`uart = true`), but the login shell on the serial port
must be off as well. `sudo raspi-config nonint do_serial_cons 1` does that **(command unverified, the menu route
above is the safe one)**.

**Card IDs on the UART reader:** the RDM6300 reports the same 125 kHz chips as the USB reader, but the ID can be
written differently. Before trusting `id_format = "raw"`, put a card that is already in your v2 list on the
reader. The web interface (or `jukebox cards`) shows the ID that arrived. If it differs from the entry in the
old `shortcuts` file, try `dec`, `float` or `hex` until it matches, see [CONFIG.md](CONFIG.md).

## Pimoroni OnOff SHIM

The SHIM's button is on GPIO 17 (pin 11) and the power-off signal on GPIO 4 (pin 7). `power = "onoff-shim"`
writes `dtoverlay=gpio-poweroff,gpiopin=4,active_low=1,input=1` so that the SHIM cuts the power after the Pi has
halted (line taken from Pimoroni's forum, **not verified on this box**). The button stays with the jukebox:

```toml
[[gpio.button]]
pin = 17
hold_action = "shutdown"
hold_time = 2.0
```

A short press does nothing, holding for 2 seconds shuts down. Do **not** also use the `gpio-shutdown` overlay on
GPIO 17, it would hold the pin and the jukebox could no longer open it. If `cleanshutd` (Pimoroni's daemon) is
still installed from v2, remove it, it uses the same pins.

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

Settings in [CONFIG.md](CONFIG.md#display). Everything is configurable: pins, rotation, the edges hidden by
the housing, and how the cover is arranged.

Wiring (BCM numbers, the data lines are fixed by the SPI0 bus):

| Display | Raspberry Pi |
|---|---|
| VCC | 3.3 V |
| GND | GND |
| CS | GPIO 8 (CE0) |
| SCK | GPIO 11 |
| MOSI (SDI) | GPIO 10 |
| DC | `dc` (default GPIO 25) |
| RESET | `reset` (default GPIO 17) |
| LED / backlight | 3.3 V, or a GPIO (`backlight`) if the box should switch it |

MISO (GPIO 9) is not needed. Enable SPI with `[boot] spi = true` and `jukebox setup --apply`.
Packages: `sudo apt install -y python3-pil python3-spidev`. Test: `jukebox display-test`.

**Not yet run on a real panel.** The initialisation sequence and the rotation values are written from memory of the
Adafruit ILI9341 library. If the picture is mirrored, upside down or shows colour errors (red and blue swapped),
tell me what you see.

## Example: one complete box ("Pferdeanhänger")

`boxes/pferdeanhaenger/config.toml` is the full pinout of one box (Marie's horse trailer). Other boxes have
other pinouts; only that file is specific to it.

| Part | Physical pin | BCM | In the config |
|---|---|---|---|
| Button top blue (next) | 37 | 26 | `gpio.button` next |
| Button top green (prev) | 38 | 20 | `gpio.button` prev |
| Button top yellow (pause) | 32 | 12 | `gpio.button` play_pause |
| SHIM button (shutdown, hold 2 s) | 11 | 17 | `gpio.button`, hold only |
| Encoder CLK / DT / push | 31 / 29 / 33 | 6 / 5 / 13 | `gpio.rotary`, button `mute` |
| Back button (horse sound) | 36 | 16 | `pferdesound`, see `boxes/pferdeanhaenger/hooks.py` |
| LED top red | 18 | 24 | `status` |
| LEDs back white / red | 13 / 16 | 27 / 23 | `back_white`, `back_red` |
| Button LED red | 3 | 2 | `button_red` |
| Display DC / RESET / CS | 15 / 22 / 24 | 22 / 25 / 8 | `[display]` dc=22, reset=25 |
| Display MOSI / MISO / SCLK | 19 / 21 / 23 | 10 / 9 / 11 | SPI0 |
| RDM6300 (reader) | 8 / 10 | 14 / 15 | UART, `/dev/serial0` |
| Amplifier (MiniAmp) | 12, 35, 40 (+ 17 power) | 18, 19, 21 | I2S |
| SHIM power-off signal | 7 | 4 | `[boot] power = "onoff-shim"` |

The pins match the v2 `gpio.ini` of this box (shutdown 17, encoder 6/5, prev/next 20/26, mute 13, pause 12,
horse sound 16).

Things to check on that box:

- **GPIO 20 (prev button)** is the I2S data-in pin. The `hifiberry-dac` overlay may claim it. If the button
  does nothing, move it to a free pin.
- **GPIO 2 (red button LED)** is the I2C SDA pin with a fixed pull-up on the board. It works as an output
  while `i2c = false`.
- **GPIO 4** belongs to the SHIM. Do not assign it to anything else.
- The reader is a serial (UART) module in the roof, assumed to be an RDM6300. Its TX goes to the Pi's RX (pin 10, GPIO 15). Check the card IDs, see above.

## Checking the pins

`jukebox pins` lists the BCM pins a configuration uses and reports collisions: a pin used twice, pins that
belong to SPI (display), UART (RDM6300), I2C (ADS1115) or I2S (audio overlay), and pins that do not exist on the
header. Hardware the jukebox does not drive (a SHIM, say) is declared in the box configuration:

```toml
[gpio.reserved]
4 = "OnOff SHIM power-off signal"
```

The same check runs when the box starts (as log warnings) and in the tests for every `boxes/*/config.toml`.
