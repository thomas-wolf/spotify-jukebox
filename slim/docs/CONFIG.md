# Configuration

The box reads two files from the same folder (default `~/.config/jukebox/`):

- `config.toml`: hardware and behaviour, **different on every box**
- `cards.toml`: card -> action, read at startup (restart the service after changes)

Other paths: `jukebox -c /path/to/config.toml ...`. `cards.toml` always sits next to `config.toml`.
A missing key falls back to the default in the tables below. Invalid values (for example a volume above
100) make startup fail with an error message.

A commented template is in `examples/config.toml`.

## config.toml

### `[box]`

| Key | Default | Meaning |
|---|---|---|
| `name` | `jukebox` | Name of the box, used in log messages only |
| `data_dir` | `~/.local/share/jukebox` | Where the resume state of local folders is kept (`resume.json`) |

### `[audio]`

All values are integers from 0 to 100. Volume is controlled in software (the MiniAmp has no hardware mixer).

| Key | Default | Meaning |
|---|---|---|
| `start_volume` | `30` | Volume when the box starts |
| `max_volume` | `80` | Hard upper limit. Applies to buttons, encoders, cards and the potentiometer. |
| `volume_step` | `5` | Step size for `volume_up` and `volume_down` |

### `[cards]`

| Key | Default | Meaning |
|---|---|---|
| `same_card` | `toggle` | What happens when the running card is presented again: `toggle` (pause/resume), `ignore`, `restart` (from the beginning), `next` (next track) |
| `same_card_delay` | `3.0` | Seconds during which the same card counts as a reader repeat and is ignored |

### `[spotify]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Spotify playback on or off |
| `api_url` | `http://127.0.0.1:3678` | Address of go-librespot's REST API (`server.port` there) |

### `[local]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Local folders on or off. If `mpv` cannot be found this part is switched off and the box keeps running with Spotify. |
| `root` | `~/music` | Root folder. Targets such as `folder:audiobooks/x` are relative to it. |
| `mpv` | `mpv` | Program name or path of mpv |

Folders are read recursively and sorted naturally (`2.mp3` before `10.mp3`). Recognised extensions: mp3,
flac, ogg, oga, opus, m4a, m4b, aac, wav, wma, aiff, ac3. Paths outside `root` are rejected.

### `[readers.usb]`

Keyboard emulation, as with most USB readers. Needs `python3-evdev`.

| Key | Meaning |
|---|---|
| `enabled` | `true` to activate |
| `device_name` | Part of the device name (case-insensitive). List the names with `python3 -c "import evdev; [print(evdev.InputDevice(p).name) for p in evdev.list_devices()]"`. |

The reader is grabbed exclusively, so the digits do not end up in a console. Letters in card IDs are
lower-cased (as in v2).

### `[readers.rdm6300]`

125 kHz reader on the serial port (9600 baud).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | `true` to activate |
| `port` | `/dev/serial0` | Serial port |
| `id_format` | `raw` | What the card ID looks like, see below |

Formats (for the same tag):

| `id_format` | Example | Note |
|---|---|---|
| `raw` | `070067315809` | 12 characters including checksum, **the default in Phoniebox v2** |
| `dec` | `0006762840` | 10 digits, like v2 `card_id_dec` and like the ID a USB reader types, so cards taught on either reader match |
| `float` | `103,12632` | like v2 `card_id_float`, matches the number printed on the tag |
| `hex` | `0700673158` | the 10 characters of the tag without checksum (new) |

A card is reported once per presentation. If you take it away (one second without a signal) and put it
back, that counts as a new presentation.

### `[gpio]`

GPIO numbers are BCM numbers (not the pin numbers on the header). Needs `python3-libgpiod` 2.x.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Set to `false` to switch GPIO off entirely without deleting the entries |
| `chip` | `/dev/gpiochip0` | GPIO chip. Older kernels on the Pi 5 use a different one (unverified); `gpiodetect` lists them. |

**Buttons: `[[gpio.button]]`** (as many as you like)

| Key | Default | Meaning |
|---|---|---|
| `pin` | | BCM number |
| `pull` | `up` | `up`: button to ground, internal pull-up. `down`: button to 3.3 V |
| `action` | | Action on a short press (list below) |
| `args` | `{}` | Arguments of the action, e.g. `args = { seconds = 30 }` |
| `hold_action` | | Action on a long hold. `action` then fires on release, but only if the button was not held. |
| `hold_time` | `1.0` | Seconds until `hold_action` fires |
| `repeat` | `false` | The action repeats while held (useful for volume) |

**Rotary encoder: `[[gpio.rotary]]`**

| Key | Default | Meaning |
|---|---|---|
| `pin_a`, `pin_b` | | BCM numbers of the two channels |
| `pull` | `up` | Pull for both pins |
| `cw`, `ccw` | | Action per detent clockwise / counter-clockwise |
| `cw_args`, `ccw_args` | `{}` | Arguments |

One detent is four valid transitions. Bounce on a single channel triggers nothing. If the encoder turns the
wrong way, swap `cw` and `ccw`.

**LED: `[[gpio.led]]`**

| Key | Meaning |
|---|---|
| `name` | Name under which the LED is reachable in a `hooks.py` as `app.leds["name"]` |
| `pin` | BCM number. The core does not drive LEDs itself, only hooks do. |

### `[adc]`: volume potentiometer on an ADS1115

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | `true` to activate (requires `[boot] i2c = true`) |
| `bus` | `1` | I2C bus (`/dev/i2c-1`) |
| `address` | `0x48` | I2C address of the ADS1115 |
| `channel` | `0` | Input A0 to A3 |
| `full_scale` | `26400` | Raw value at the top end of the potentiometer |

The position of the potentiometer at startup does not change the volume; only a move of at least two
percent does. You tune `full_scale` with `jukebox adc-check`: turn the potentiometer to both ends and enter
the raw value at the top end. The default applies to a potentiometer wired to 3.3 V in the +-4.096 V range.

### `[display]`

Shows cover, title and artist on an ILI9341 panel (SPI). Needs `python3-pil` and `python3-spidev` from apt, plus
`python3-libgpiod` 2.x. If anything is missing or the panel does not answer, the box logs an error and runs
on without a display.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | `true` to activate |
| `width`, `height` | `240`, `320` | Native size of the panel (portrait). Only change this for another panel size. |
| `rotation` | `90` | `0`, `90`, `180`, `270`: how the picture is turned, so that it is upright in your housing |
| `dc` | `25` | BCM pin for data/command |
| `reset` | `17` | BCM pin for reset. `-1` if it is not wired (software reset) |
| `backlight` | none | BCM pin that switches the backlight. Leave it out if the backlight is always on. |
| `spi_bus`, `spi_device` | `0`, `0` | SPI bus and chip select (`/dev/spidev0.0`) |
| `spi_speed_hz` | `32000000` | SPI clock. Lower it if the picture shows noise (unverified, depends on the wiring). |
| `gpio_chip` | `/dev/gpiochip0` | GPIO chip for the pins above |
| `margins` | all `0` | Pixels the housing hides: `{ left = 12, top = 10, right = 12, bottom = 10 }`. In the **rotated** picture, as you look at it. Nothing important is drawn there. |
| `layout` | `auto` | `cover`: the cover alone fills the visible area. `overlay`: the cover fills the whole screen (cropped) and title and artist are drawn on a dark gradient at the bottom. `split`: square cover plus text beside or below it. `auto`: split when the leftover space is big enough for text (wide displays), otherwise cover alone. |
| `cover_side` | `left` | Which side the square cover goes in `split`: `left` or `right` (wide pictures), `top` or `bottom` (tall ones) |
| `cover_fit` | `contain` | `contain`: the whole cover is visible, bars where the shape differs (4:3 cover in a square box). `cover`: the box is filled, the cover is cropped. |
| `background` | `average` | What fills the free areas: `average` (darkened average colour of the cover), `blur` (blurred cover), or a fixed color like `"#101010"` |
| `idle_image` | none | Picture shown at boot and whenever nothing plays (after `stop`). A relative path is taken relative to the real `config.toml`. **Convention:** without this key, `idle.jpg` (or `.jpeg`, `.png`, `.webp`) in the configuration folder `~/.config/jukebox/` is used. That folder is never part of the repository, so private photos belong there. Without a picture the screen goes black. |
| `idle_fit` | `cover` | `cover`: the picture fills the visible area and is cropped, `contain`: the whole picture is shown. Margins are respected. |
| `idle_on_pause` | `false` | `true`: the picture is also shown while playback is paused. |
| `font` | bundled | Path of a TrueType font. The default is the DejaVu Sans that ships with the package (umlauts, ß and most accents work). |
| `title_size`, `artist_size` | `22`, `16` | Text sizes in pixels |

A cover is usually square or 4:3. On a wide panel the square cover takes the left or right part of the visible
area and the title goes next to it, so nothing is stretched and the hidden edges cost nothing. On a 4:3 panel
the cover fills the picture.

Adjusting it: run `jukebox display-test` on the box. The red frame is the edge of the panel, the green frame
the visible area after `margins`, the yellow letters TL, TR, BL, BR mark the corners as drawn. Turn
`rotation` until TL is at the top left of your housing, then raise `margins` until the green frame sits where
the housing opens. `jukebox display-test --save test.png` writes the same picture to a file (no panel
needed), `--cover file.jpg` tries your own cover.

**Where the cover comes from**

- **Spotify:** Cover, title and artist come from go-librespot's `/status` (polled every two seconds).
- **Local files:** In this order:
  1. A picture in the folder of the file, found by name, upper or lower case: `cover`, `folder`, `front`,
     `albumart`, `album` or `artwork`, as `.jpg`, `.jpeg`, `.png` or `.webp`.
  2. A copy saved earlier (see 3).
  3. Spotify: the album is searched by the tags of the file (album and artist; read from mpv), or, without tags,
     by the folder name as album and the folder above it (inside the music root) as artist. A hit is only taken
     when album name and artist match closely; a wrong cover is worse than none. The picture is saved as
     `cover.jpg` in the folder, or in `[box] data_dir/covers/` if the folder is not writable or
     `write_to_folder = false`.
  4. Nothing found: no cover, the title is shown as text. "Spotify does not know it" is remembered for 30 days so
     rare albums are not searched at every track. Failed searches (offline, not logged in) are retried.

The title of a local file comes from its tags, otherwise from the file name.

### `[covers]`

| Key | Default | Meaning |
|---|---|---|
| `spotify_search` | `true` | Search missing covers of local files on Spotify (needs `[spotify]` enabled and go-librespot logged in) |
| `write_to_folder` | `true` | Save the found picture as `cover.jpg` next to the music. `false`: keep it in the data folder. |

The search uses the token of the go-librespot session (`POST /token`), so no developer account is needed. That
this token is accepted by Spotify's search is **unverified**. Spotify's Web API terms on storing album pictures
were not reviewed; the saved pictures stay on your box.

### `[sync]`

Keeps cards, configuration and music in sync with a cloud folder through rclone. Everything is described in
[SYNC.md](SYNC.md).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Run the sync in the background |
| `remote` | | rclone remote and folder, e.g. `"dropbox:Jukebox"` (required) |
| `interval_minutes` | `30` | How often to sync |
| `cards` | `both` | `both`, `pull`, `push`, `off` |
| `config` | `pull` | `pull` or `off` |
| `music` | `pull` | `pull` or `off` |

More keys (`delete`, `bwlimit`, `cards_per_box`, `first_run_delay`, `rclone`, `rclone_config`) in SYNC.md.

### `[web]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | `true` to start the web interface |
| `host` | `0.0.0.0` | Address to listen on. `127.0.0.1` makes it reachable from the box itself only. |
| `port` | `8080` | Port |

The page shows what is playing (with previous, play/pause, next, stop and volume), the ID of the last card
that was presented, a form to assign a card (Spotify link, local folder or action) and the list of all cards
with search, edit, delete and a test button.

- **No authentication.** Anybody who can reach the port can change cards and control playback. Use it in a
  trusted home network only.
- Changes are active immediately and are written to `cards.toml`. That rewrites the file: **comments in it are
  lost**. The first rewrite keeps the old file as `cards.toml.jukebox.bak`.
- A Spotify link pasted into the form is converted to the `spotify:<type>:<id>` form.
- The list of local folders in the form shows folders under `[local] root` (three levels deep) that contain
  audio files.
- Changing a request needs the content type `application/json`, so a foreign web page cannot change cards just
  by sending a form.

### `[sounds]`

| Key | Default | Meaning |
|---|---|---|
| `command` | `["mpv", "--no-video", "--really-quiet"]` | Program that plays event sounds. The file name is appended. |

**`[sounds.events]`** assigns files to events:

```toml
[sounds.events]
boot = "~/sounds/startup.mp3"
shutdown = "~/sounds/shutdown.mp3"
card_unknown = "~/sounds/error.mp3"
```

Valid event names are listed in [HOOKS.md](HOOKS.md). If the file is missing there is a warning in the log,
otherwise nothing happens.

### `[system]`

| Key | Default | Meaning |
|---|---|---|
| `shutdown_command` | `["systemctl", "poweroff"]` | Command of the `shutdown` action. See [INSTALL.md](INSTALL.md) for the sudo variant. |

### `[hooks]`

| Key | Meaning |
|---|---|
| `file` | Python file with custom code for this box, relative to `config.toml`. See [HOOKS.md](HOOKS.md). |

### `[boot]`: overlays

Read only by `jukebox setup`, not during normal operation.

| Key | Meaning |
|---|---|
| `audio` | Audio profile: `hifiberry-miniamp`, `hifiberry-dac` (both `dtoverlay=hifiberry-dac`) or `pirate-audio` (additionally `gpio=25=op,dh`, as in the v2 script). All switch `dtparam=audio=on` off. |
| `spi` | `true` writes `dtparam=spi=on` (for the display) |
| `i2c` | `true` writes `dtparam=i2c_arm=on` (for the ADS1115) |
| `uart` | `true` writes `enable_uart=1` (for the RDM6300) |
| `power` | `"onoff-shim"`: overlay that lets the Pimoroni OnOff SHIM cut the power after shutdown |
| `extra` | More lines. Either text or `{ model = "pi5", line = "..." }` for lines that apply to one Pi model only (config.txt filter `[pi5]`) |

Details and background in [HARDWARE.md](HARDWARE.md).

## cards.toml

```toml
[cards."0123456789"]
name = "Good night"                      # optional, for your overview only
play = "spotify:playlist:37i9dQZF1DX0UrRvztWcAU"

[cards."0123456790"]
play = "folder:audiobooks/pumuckl"

[cards."0123456791"]
action = "seek_forward"
args = { seconds = 30 }
```

Exactly one of `play` or `action` per card. IDs are compared case-insensitively. You can also add cards by
command: `jukebox cards add ID --play ... | --action ... [--name ...]`. Many cards from a Phoniebox v2 setup: `jukebox import-v2`, see [MIGRATION.md](MIGRATION.md).

**Targets (`play`)**

| Form | Meaning |
|---|---|
| `spotify:playlist:ID`, `spotify:album:ID`, `spotify:track:ID`, ... | Spotify URI |
| `folder:relative/path` | Folder under `[local] root`, recursive, played with resume |
| `file:relative/path.mp3` | A single file under `root` |
| `stream:https://host/path` | A web radio or other stream, played by mpv (see below) |

**Web radio (`stream:`)**

```toml
[cards."0123456792"]
name = "Bayern 2"
play = "stream:http://br-br2-nord.cast.addradio.de/br/br2/nord/mp3/56/stream.mp3"
```

- Needs mpv, so `[local] enabled = true`. Only `http://` and `https://` addresses are accepted. mpv also reads
  playlist addresses (`.m3u`, `.pls`); that is mpv's job and not tested here.
- A live stream has no position: `next`, `prev` and `seek_*` do nothing. `pause` drops the stream and `resume`
  loads it again, so you come back to the live programme, not to where you stopped.
- With a display, the station name and the current song (the stream's own title information, if the station sends
  it) are shown. There is no cover for streams. Which tag names mpv reports for the song title (`icy-title`) is
  from memory and **unverified**.
- The web interface (`[web]`) has its own choice "Play a web radio / stream" for the address.

When switching between Spotify, local playback and streams, the other player is stopped. Volume applies to both.

**Actions (`action`, also for buttons, encoders and hooks)**

| Action | Arguments | Meaning |
|---|---|---|
| `play_pause` | | Toggle pause/resume |
| `pause`, `resume`, `stop` | | As named. With Spotify, `stop` only pauses. |
| `next`, `prev` | | Next / previous track |
| `seek_forward`, `seek_back` | `seconds` (15) | Seek forward or back |
| `volume_up`, `volume_down` | | Change by `volume_step` |
| `volume_set` | `value` | Set the volume (limited to `max_volume`) |
| `mute` | | Mute, and back to the previous volume |
| `shutdown` | | Shut the box down (`[system] shutdown_command`) |

Unknown actions and wrong arguments are reported in the log and do not disturb operation. Player errors
(for example go-librespot unreachable) are logged as well and raise the `error` event.

## Local overrides

If a file `config.local.toml` sits next to the configuration file, it is merged on top (tables are merged key by
key, a list such as `[[gpio.button]]` is replaced as a whole). Use it for things that differ on one device without
touching the file in the repository, for example a USB reader for a test:

```toml
[readers.rdm6300]
enabled = false

[readers.usb]
enabled = true
device_name = "SYC"
```

The file lives in `~/.config/jukebox/` next to the (linked) `config.toml`. It is not part of `boxes/`.
