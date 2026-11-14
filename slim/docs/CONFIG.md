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
| `dec` | `0006762840` | 10 digits, like v2 `card_id_dec` |
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
command: `jukebox cards add ID --play ... | --action ... [--name ...]`.

**Targets (`play`)**

| Form | Meaning |
|---|---|
| `spotify:playlist:ID`, `spotify:album:ID`, `spotify:track:ID`, ... | Spotify URI |
| `folder:relative/path` | Folder under `[local] root`, recursive, played with resume |
| `file:relative/path.mp3` | A single file under `root` |

When switching between Spotify and local playback, the other player is stopped. Volume applies to both.

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
