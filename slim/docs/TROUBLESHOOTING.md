# Troubleshooting

Look at the logs first:

```
journalctl -u jukebox -f          # the jukebox
journalctl -u go-librespot -f     # Spotify daemon
/opt/jukebox/venv/bin/jukebox -v run     # in the foreground with debug messages (stop the service first)
```

## No sound

1. Is the sound card there? `aplay -l` must show `sndrpihifiberry`. If not, the overlay is not in
   `config.txt` or the box was not rebooted: `grep -n hifiberry /boot/firmware/config.txt`
   (on an older system `/boot/config.txt`).
2. Is the on-board audio still running? `dtparam=audio=on` must be switched off. `jukebox setup` comments the
   line out.
3. Does the card work at all? `speaker-test -t sine -f 440 -l 1`.
4. Is the volume 0 or muted? The log shows `volume` events. See `start_volume` in `config.toml`.
5. Local files do not play? Try `mpv --no-video /path/file.mp3` directly.
6. Spotify plays in the app but not on the box? Check `audio_device` in the go-librespot configuration
   (`aplay -L` lists the names).

## Card is not recognised

- The log says `unknown card <ID>`: the card has not been added. Copy the ID and run
  `jukebox cards add <ID> --play ...`. Then restart the service, because `cards.toml` is read at startup.
- The ID looks different from v2: for the RDM6300 check `id_format` (default `raw`).
- No message at all when presenting a card: see "Reader finds nothing".

## Reader finds nothing

**USB:** The service user must be in the group `input` (`groups`). `device_name` must occur in a device
name (command in [HARDWARE.md](HARDWARE.md)). While the reader is missing, the log shows
`USB reader ... not found` every five seconds. Other programs that also grab the reader (the old Phoniebox
service) block it.

**RDM6300:** Is the serial port enabled (login shell off, hardware on)? `ls -l /dev/serial0`.
The user needs the group `dialout`. `sudo cat /dev/serial0` must show characters when a card is presented.
If nothing happens, check the wiring (reader TX to Pi RX) and the voltage.

## Service does not start: `status=217/USER`

The unit file names a user that does not exist (the templates say `pi`). Check with
`grep -n 'User=\|/home' /etc/systemd/system/{go-librespot,jukebox}.service` and fix both files:

```
sudo sed -i "s|/home/pi|$HOME|g; s|^User=pi|User=$USER|" /etc/systemd/system/go-librespot.service /etc/systemd/system/jukebox.service
sudo systemctl daemon-reload && sudo systemctl restart go-librespot jukebox
```

## Spotify

**`jukebox spotify-check` reports `FAILED: go-librespot not reachable`:**
Check `systemctl status go-librespot`; the go-librespot configuration must contain `server.enabled: true`.
`server.port` and `[spotify] api_url` must match.

**The daemon runs, but the card starts nothing:** The jukebox log then shows something like
`go-librespot POST /player/play: HTTP 404`. The endpoints in `src/jukebox/players/spotify.py` (`ENDPOINTS`)
are my assumption and have not been checked against go-librespot's specification. Compare them with the file
`api-spec.yml` in the go-librespot repository and adjust the table. The request field names (`uri`,
`volume`, `position`) come from the same assumption.

**Login errors (`INVALID_CREDENTIALS`, `login5`):** A report from August 2026 describes go-librespot
0.7.1 on Volumio aborting with this message when logging in by token, but working in plain zeroconf mode.
In the Mopidy forum users reported the same error with the Spotify plugin. So this error belongs to the family
of login problems of the librespot projects, not to this jukebox. What helps:

1. Update go-librespot to the latest version.
2. Log in again: stop the service, remove the stored credentials in the go-librespot configuration folder
   (which file is named in go-librespot's README **(not verified)**), start it and repeat the code login
   at spotify.com/pair.
3. For diagnosis only, try `credentials.type: zeroconf` and select the box from the Spotify app.

**Does not play although the login is fine:** Spotify Premium is required.

## GPIO and buttons

- `ModuleNotFoundError: gpiod` or `AttributeError: ... request_lines`: `python3-libgpiod` 1.x is installed,
  or the venv cannot see the apt packages. Check `python3 -c "import gpiod; print(gpiod.request_lines)"`. On
  Bookworm 2.x is only available through `bookworm-backports`. The venv needs `--system-site-packages`.
- `Permission denied`: add the user to the group `gpio`, then log in again or restart the service.
- `Device or resource busy`: the pin is already in use, for example by an old Phoniebox service that is still
  running, or by an overlay. `gpioinfo` shows who owns the lines.
- A button fires several times or not at all: check `pull`. Buttons to ground need `pull = "up"`.
- The encoder counts backwards: swap `cw` and `ccw`.
- The log reports `unknown action`: typo in the name. The names are listed in [CONFIG.md](CONFIG.md).

## Potentiometer

- `/dev/i2c-1` is missing: I2C is not enabled. `[boot] i2c = true`, `jukebox setup --apply`, reboot. The module
  `i2c-dev` comes from `/etc/modules-load.d/jukebox.conf`.
- `i2cdetect -y 1` does not show `48`: check the wiring and the ADDR pin.
- Volume does not reach 100 % or reaches it too early: run `jukebox adc-check` and adjust `full_scale`.
- The volume does not jump to the potentiometer position after startup. That is intentional; only a move
  counts.

## Shutdown does not work

The service often is not allowed to run `systemctl poweroff`. Create the sudo rule and change
`shutdown_command` (see [INSTALL.md](INSTALL.md) step 7).

## Resetting `config.txt`

The first `jukebox setup --apply` creates `config.txt.jukebox.bak` next to `config.txt`. To go back:

```
sudo cp /boot/firmware/config.txt.jukebox.bak /boot/firmware/config.txt
```

(on an older system under `/boot/`). You can simply delete the file `/etc/modules-load.d/jukebox.conf`.

## Reporting problems

With a problem, include: Raspberry Pi model, `cat /etc/os-release`, `uname -m`, excerpts from
`journalctl -u jukebox` and `journalctl -u go-librespot`, and your `config.toml` without personal data.
