# Migrating from Phoniebox v2

This page describes how to carry existing cards and settings over from the v2 Spotify Edition.
There is no import tool yet. The migration is manual work, but manageable.

## Switch off the old services

If the box still runs v2, the old services collide with the new jukebox (audio device, serial port, GPIO
pins, ports 6680/6600). Switch them off first:

```
sudo systemctl disable --now mopidy mpd lighttpd phoniebox-rfid-reader \
  phoniebox-gpio-control phoniebox-startup-scripts phoniebox-idle-watchdog 2>&1 | cat
```

systemd reports services that do not exist as errors. That is harmless. `systemctl list-units 'phoniebox*' mopidy* mpd*`
shows which services actually run on your box. A fresh SD card is the cleanest route.

## Card IDs

So that your cards keep working without being re-learned, the new jukebox produces the same IDs as v2:

| Reader | v2 | New |
|---|---|---|
| RDM6300 | default: raw, 12 characters with checksum (`070067315809`) | `id_format = "raw"` (default) |
| RDM6300 | `numberformat = card_id_dec` | `id_format = "dec"` |
| RDM6300 | `numberformat = card_id_float` | `id_format = "float"` |
| USB | digits and letters, letters lower case | the same (letters lower case) |

Two edge cases:

- The old USB code translated keys through a table for German keyboards in which **y and z are swapped**.
  Card IDs containing y or z (unusual for hex IDs) are now spelled differently.
- The jukebox compares IDs case-insensitively.

## Importing the cards automatically

`jukebox import-v2` reads your v2 data and writes `cards.toml`. You need the files, not the running v2 box:
a copy of the folders `shared/shortcuts` and `shared/audiofolders` (or just the folders that contain a
`spotify.txt`) and, for control cards, `settings/rfid_trigger_play.conf`. If you keep them in a Dropbox, it
is enough to point the command at the folder that contains them. It looks for `shared/shortcuts`,
`shared/audiofolders` and `settings/rfid_trigger_play.conf` below the folder you give it, or for
`shortcuts/`, `audiofolders/` and `rfid_trigger_play.conf` directly in it.

```
/opt/jukebox/venv/bin/jukebox import-v2 ~/Dropbox/phoniebox          # dry run, only reports
/opt/jukebox/venv/bin/jukebox import-v2 ~/Dropbox/phoniebox --apply  # appends to cards.toml
sudo systemctl restart jukebox
```

The dry run prints how many cards it found, how many are new, and for every card it had to skip the ID and
the reason. Cards that already exist in `cards.toml` are never changed, so you can run the import repeatedly.

What the import does with each kind of card:

| v2 | Result |
|---|---|
| `spotify.txt` with `spotify:...`, `spotify:user:NAME:playlist:ID` or an `open.spotify.com` link | `play = "spotify:<type>:<id>"` |
| Folder with audio files | `play = "folder:<name>"`. You still copy the files to `[local] root`, with the same folder names. |
| Control cards from `rfid_trigger_play.conf` | `action = ...` as in the table below. Unset entries (`%CMD...%`) are ignored. |
| Card ID never assigned (v2 wrote a shortcut with the ID as content on first use) | ignored, counted in the report |
| `livestream.txt` with a http(s) address | `play = "stream:<address>"` |
| `podcast.txt`, `url.txt`, `youtube.txt` | skipped, listed in the report |
| Folder missing in the copy | skipped, listed in the report |
| Control cards without an equivalent (random, timers, WLAN, ...) | skipped, listed in the report |

Check these things after the import, because the importer cannot know them:

- The IDs have to match what your reader produces. For the RDM6300 keep `id_format = "raw"` (see above);
  that is what v2 used unless you changed `numberformat`. Put one old card on the reader. If the log says
  `unknown card ...` although the card is in `cards.toml`, the format differs.
- Spotify links in the old Mopidy format are converted, but whether go-librespot plays every type
  (playlists, albums and tracks are the normal case; shows and episodes are untested) is not verified.
- Local folders: check that the folder names under `[local] root` match exactly, including upper and lower case.

The manual route below describes the same mapping and is useful for edge cases.

## Cards and folders

v2 stores a card in two parts (paths are relative to the v2 installation; the root is in
`settings/Audio_Folders_Path`):

1. `shared/shortcuts/<card ID>` is a file whose content is the folder name.
2. `shared/audiofolders/<folder name>/` contains either audio files or a text file with the source:
   `spotify.txt`, `podcast.txt`, `livestream.txt` or `url.txt`.

In `cards.toml` this becomes:

| v2 | New |
|---|---|
| Folder contains `spotify.txt` with `spotify:playlist:ID` | `play = "spotify:playlist:ID"` (same file content; v2 used the Mopidy format) |
| Folder with audio files | `play = "folder:<folder name>"`, copy the files to `[local] root` |
| `livestream.txt` with a http(s) address | `play = "stream:<address>"` (web radio) |
| `podcast.txt`, `url.txt`, `youtube.txt` | **not supported** |

Example: the file `shared/shortcuts/0123456789` contains `Good-Night`, and
`shared/audiofolders/Good-Night/spotify.txt` contains `spotify:playlist:37i9dQZF1DX0UrRvztWcAU`. Then:

```toml
[cards."0123456789"]
name = "Good-Night"
play = "spotify:playlist:37i9dQZF1DX0UrRvztWcAU"
```

Read the file contents with `cat` or a small loop, for example:

```
cd ~/RPi-Jukebox-RFID/shared/shortcuts
for id in *; do printf '%s -> %s\n' "$id" "$(cat "$id")"; done
cat ../audiofolders/Good-Night/spotify.txt
```

The path `~/RPi-Jukebox-RFID` is the v2 default and may differ on your box.

The resume position of local folders is not carried over; it starts afresh.

## Control cards

v2 keeps control cards in `settings/rfid_trigger_play.conf`, as lines like `CMDVOLUP="0123456789"`.
This mapping applies in the new jukebox:

| v2 variable | New action |
|---|---|
| `CMDVOLUP`, `CMDVOLDOWN` | `volume_up`, `volume_down` |
| `CMDVOL30` ... `CMDVOL100` | `volume_set` with `args = { value = 30 }` etc. |
| `CMDMUTE` | `mute` |
| `CMDNEXT`, `CMDPREV` | `next`, `prev` |
| `CMDPAUSE` | `play_pause` (in v2 this card toggled, it did not only pause) |
| `CMDPLAY` | `resume` |
| `CMDSTOP` | `stop` |
| `CMDSEEKFORW`, `CMDSEEKBACK` | `seek_forward`, `seek_back` (v2: 15 seconds, also 15 here) |
| `CMDSHUTDOWN` | `shutdown` |

Example of a "volume 50 %" card:

```toml
[cards."0123456790"]
action = "volume_set"
args = { value = 50 }
```

**Not available yet** (these cards are reported as unknown): random playback (`CMDSHUFFLE`,
`CMDRANDCARD`, `CMDRANDFOLD`, `CMDRANDTRACK`), restarting the playlist (`CMDREWIND`), maximum-volume cards
(`CMDMAXVOL...`), stop/shutdown timers (`STOPAFTER...`, `SHUTDOWNAFTER...`), reboot, switching WLAN,
Bluetooth and the audio interface, recording, synchronisation.

## GPIO settings

`settings/gpio_settings.ini` is not read. The equivalent lives in `config.toml`:

| v2 | New |
|---|---|
| `Type: Button`, `functionCall: functionCallPlayerNext` | `[[gpio.button]]`, `action = "next"` |
| `functionCallVolU` / `functionCallVolD` | `volume_up` / `volume_down` |
| `functionCallPlayerPause` | `play_pause` (in v2 this toggles) |
| `functionCallPlayerPauseForce` | `pause` |
| `functionCallPlayerPrev` / `functionCallPlayerNext` | `prev` / `next` |
| `functionCallVol0` | `mute` |
| `functionCallPlayerStop` | `stop` |
| `functionCallPlayerSeekFwd` / `SeekBack` | `seek_forward` / `seek_back`. v2 jumped 10 seconds here (`SeekFarFwd`/`FarBack`: 60); set `args = { seconds = 10 }`, otherwise 15 applies. |
| `functionCallShutdown` | `shutdown` |
| `hold_mode: Repeat` | `repeat = true` |
| `hold_mode: SecondFunc` with `functionCall2` | `hold_action` (and `hold_time`) |
| `Type: RotaryEncoder` | `[[gpio.rotary]]` with `cw`/`ccw` |
| `Type: ShutdownButton` | `[[gpio.button]]` with `hold_action = "shutdown"` |
| `Type: TwoButtonControl` | two single buttons (the double-press effect is gone) |
| `Type: StatusLED` | a `[[gpio.led]]` plus a hook, see [HOOKS.md](HOOKS.md) |

Compare the pins with the table in [HARDWARE.md](HARDWARE.md). With I2C (potentiometer), GPIO 3 can no
longer be used as a button.

## What is deliberately left out

The new jukebox is a Spotify and local-files box, not a replacement for the whole v2 package. Not included:
the v2 web interface (there is a small new one for cards and basic controls, see [CONFIG.md](CONFIG.md#web)), podcasts and YouTube downloads (web radio is supported through `stream:`), Samba share, WLAN hotspot, Bluetooth sink
switching, automatic shutdown on inactivity (idle watchdog), recording, synchronisation, RC522 and PN532 RFID
readers, and the HD44780 and MAX7219 displays (an ILI9341 cover display is new). Some of that could be added as a separate building block, see
[DEVELOPMENT.md](DEVELOPMENT.md).
