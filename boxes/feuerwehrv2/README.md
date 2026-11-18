# Feuerwehr v2

Fire engine box. HiFiBerry MiniAmp, USB RFID reader (assumed: no RDM6300 in the wiring list), ILI9341 display,
rotary encoder, power button, two blue and two orange buttons with LEDs. Name rules: lowercase letters, digits and
`-` only (no dot), because the name is also the hostname and the folder name.

Install: see [../README.md](../README.md). Check with `jukebox -c boxes/feuerwehrv2/config.toml pins`.

## Pin table (physical pin -> BCM, from the user's wiring list)

| Pin | BCM | Part |
|---|---|---|
| 1 | 3V3 | MiniAmp VCC, display LED (backlight always on) |
| 2 | 5V | MiniAmp |
| 5 | 3 | power button (hold = shutdown, also wakes from halt) |
| 6, 14, 20, 25, 34, 39 | GND | block grounds (14: encoder GND + power button LED GND) |
| 7 | 4 | blue right button: previous |
| 8 | 14 | blue right LED (100 Ohm) |
| 10 | 15 | blue left button: next |
| 11 | 3V3 | display |
| 12, 35, 40 | 18, 19, 21 | MiniAmp (I2S) |
| 13 | 27 | encoder CLK |
| 15 | 22 | encoder DT |
| 16 | 23 | encoder push button: play / pause |
| 17 | 3V3 | encoder VCC |
| 18 | 24 | power button LED (1 kOhm) |
| 19 | 10 | display MOSI |
| 21 | 9 | display MISO |
| 22 | 25 | display RESET |
| 23 | 11 | display SCLK |
| 24 | 8 | display CS (CE0) |
| 26 | 7 | display DC (CE1 pin, freed with `dtoverlay=spi0-1cs`) |
| 29 | 5 | orange left LED (220 Ohm) |
| 31 | 6 | orange left button: siren |
| 32 | 12 | orange right LED (220 Ohm) |
| 33 | 13 | orange right button: blue light |
| 36 | 16 | blue left LED (100 Ohm) |

## Open

- `hooks.py` for the siren and blue light buttons (actions `sirene` and `blaulicht`) and for the LEDs.
- Unverified on the hardware: `spi0-1cs` really frees GPIO 7, display rotation, encoder direction, USB reader name,
  Soloist as backend, GPIO 14/15 as plain pins (UART must stay off, so no serial console on this box).
