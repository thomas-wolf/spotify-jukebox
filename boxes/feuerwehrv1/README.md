# Feuerwehr v1

Fire engine box, the very first draft. Compared with the other boxes it is more fragile (hand-soldered perfboard,
see below) and its parts differ: no display, no power button LED, volume only by rotary encoder, one red siren button.
Name rules: lowercase letters, digits and `-` only, because the name is also the hostname and the folder name.

Install: see [../README.md](../README.md). Check with `jukebox -c boxes/feuerwehrv1/config.toml pins`.

## Parts (from the project documentation, may be old)

- Toy fire engine, 45 x 16 x 14 cm. Roof of cab and trailer removable; the driver's bench is in the way but can be
  unscrewed. Trailer inside: 17 x 12 x 4.5 cm, side doors open.
- Raspberry Pi (documented as 9 x 6.3 x 1.5 cm, model not stated) with HiFiBerry MiniAmp, USB card reader
  (9.5 x 6.2 x 1.1 cm), power bank (about 10000 mAh, USB), speaker (not chosen: mounted on the outside of the housing).
- Two blue LED buttons (100 Ohm), two yellow LED buttons (220 Ohm), one red siren button, one rotary encoder.

## Pin table (physical pin -> BCM, from the documentation)

| Pin | BCM | Part |
|---|---|---|
| 1, 2, 6 | 3V3, 5V, GND | MiniAmp power |
| 12, 35, 40 | 18, 19, 21 | MiniAmp (I2S) |
| 38 | 20 | blue left button: previous (works with `i2s_free_gpio20`, see below) |
| 9 | GND | blue left button and blue left LED |
| 37 | 26 | blue right button: next |
| 30 | GND | blue right button and blue right LED |
| 18 | 24 | blue left LED (100 Ohm) |
| 16 | 23 | blue right LED (100 Ohm) |
| 33 | 13 | yellow left button: stop |
| 5 | 3 | yellow right button: shutdown, hold 2 s (also wakes the Pi from halt) |
| 25 | GND | both yellow buttons, yellow LEDs |
| 22 | 25 | both yellow LEDs in parallel (220 Ohm each) |
| 13 | 27 | red button: siren (needs `hooks.py`) |
| 14 | GND | red button |
| 31 | 6 | encoder CLK |
| 29 | 5 | encoder DT |
| 17 | 3V3 | encoder + |
| 34 | GND | encoder GND |
| 15 | 22 | encoder push button (optional, not enabled) |

The perfboard plan in the documentation uses the same pins (38, 9, 18, 37, 30, 16, 33, 22, 5, 25).

## Differences from the other boxes

- **No display:** `[display] enabled = false`, `[boot] spi = false`.
- **GPIO 20 (pin 38)** is the I2S data-in pin. The documentation warns that HiFiBerry boards occupy GPIO 18 to 21
  (and GPIO 16 / 26 on boards with a mute / shutdown line). The MiniAmp does not need I2S data-in, so the box uses
  `[boot] i2s_free_gpio20 = true` like the Pferdeanhänger (confirmed there: GPIO 20 and GPIO 26 work with a MiniAmp).
  Not yet tried on this box.
- **GPIO 3 (pin 5)** is the shutdown button and also an I2C pin; I2C stays off.
- **LEDs** are only driven by hooks; without a `hooks.py` they stay dark.

## Open

- `hooks.py` for the siren (action `sirene`), the blue lights ("Blaulicht") and the yellow lights ("Fernlicht"). The
  documentation says "programming needed" for the red button.
- Unverified on the hardware: USB reader name, Soloist as backend (assumption), encoder direction, `i2s_free_gpio20`
  on this box, whether the encoder push button is wired (pin 15), Pi model.
- Documentation to-dos that are hardware only: speaker (sound, volume, interference), case for the Pi with the
  HiFiBerry on top, charging socket on the outside, final soldering of the perfboard.
