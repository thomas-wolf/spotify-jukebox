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

## go-librespot: `invalid config override format: onfig_dir`

The unit passes `-config_dir ...` and go-librespot v0.10.5 reads it as `-c onfig_dir`. Remove that option from
`ExecStart`; the default folder `~/.config/go-librespot` of the service user is what the guide uses anyway:

```
sudo sed -i 's| -config_dir [^ ]*||' /etc/systemd/system/go-librespot.service
sudo systemctl daemon-reload && sudo systemctl restart go-librespot
```

## Spotify

**`jukebox spotify-check` reports `FAILED: go-librespot not reachable`:**
Check `systemctl status go-librespot`; the go-librespot configuration must contain `server.enabled: true`.
`server.port` and `[spotify] api_url` must match.

**The daemon runs, but the card starts nothing:** Collect three things:

```
curl -s localhost:3678/                 # {"playback_ready": true} when go-librespot is ready
curl -si localhost:3678/status | head   # 204 = no active session
curl -si -X POST -H 'Content-Type: application/json' -d '{"uri":"spotify:track:4uLU6hMCjMI75M1A2tKUQC"}' localhost:3678/player/play
```

and the logs of both services (`journalctl -u jukebox -u go-librespot -n 60`). A line like
`go-librespot POST /player/play: HTTP 400` in the jukebox log means go-librespot rejected the request. The
endpoints in `src/jukebox/players/spotify.py` (`ENDPOINTS`) match go-librespot's `api-spec.yml`, so the cause is
more likely the login (not done, expired) or the audio output.

**Log shows `failed retrieving aes key with code 1` / `Spotify refused the audio key`:** The jukebox did its job:
go-librespot received the play request, logged in, and then Spotify refused to hand out the decryption key for the
tracks, so every track is skipped. This is a known problem of the librespot family, open in
[go-librespot issue 279](https://github.com/devgianlu/go-librespot/issues/279) (see also issue 235 and
librespot issue 1649). Reports say Spotify refuses the key per account, also for Premium accounts (Duo and
family plans are mentioned), and that it does not matter where the player runs. Nothing in this jukebox can fix it.
What you can try (none of it is a confirmed fix):

1. Update go-librespot and read the current state of issue 279; fixes would appear there first.
2. Try the same box with another Spotify account (for example a plain individual Premium account) to see
   whether the refusal follows the account.
3. Check in the Spotify app that the account really is Premium and not in a restricted state.
4. Use local folders for the cards that matter (`folder:...`) until Spotify works again.

On the author's box, one account of a family plan was refused and another account played, so the refusal does
follow the account. Playlists of another account play as long as that account can open them (public playlists,
playlists you follow); private playlists of the account you do not log in with will not.

**Login errors (`INVALID_CREDENTIALS`, `login5`):** A report from August 2026 describes go-librespot
0.7.1 on Volumio aborting with this message when logging in by token, but working in plain zeroconf mode.
In the Mopidy forum users reported the same error with the Spotify plugin. So this error belongs to the family
of login problems of the librespot projects, not to this jukebox. What helps:

1. Update go-librespot to the latest version.
2. Log in again: stop the service, remove the stored credentials in the go-librespot configuration folder
   (per go-librespot's README the login and player state are in `state.json` there, **not checked on a box**; the `lockfile` next to it only prevents a second instance), start it and repeat the code login
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

## Cloud sync

- `jukebox sync --check` says what is wrong: rclone missing (`sudo apt install rclone`), or the remote is not
  reachable (log in again with `rclone config`, see [SYNC.md](SYNC.md)).
- Run `jukebox sync --dry-run` to see what would happen without changing anything.
- Cards come back after being deleted, or vanish: with `cards = "both"` a card deleted on only one side is deleted
  on the other at the next sync, and a card changed on both sides keeps the cloud version. Check
  `journalctl -u jukebox | grep sync` and the backup `cards.toml.sync.bak`.
- The sync runs as the user of the service, so the rclone login (`~/.config/rclone/rclone.conf`) must belong to
  that user, not to root.

## Resetting `config.txt`

The first `jukebox setup --apply` creates `config.txt.jukebox.bak` next to `config.txt`. To go back:

```
sudo cp /boot/firmware/config.txt.jukebox.bak /boot/firmware/config.txt
```

(on an older system under `/boot/`). You can simply delete the file `/etc/modules-load.d/jukebox.conf`.

## Reporting problems

With a problem, include: Raspberry Pi model, `cat /etc/os-release`, `uname -m`, excerpts from
`journalctl -u jukebox` and `journalctl -u go-librespot`, and your `config.toml` without personal data.

## Slow boot: Spotify is ready only after ~19 s

`systemd-analyze critical-chain go-librespot.service` on a Pi 4 with Wi-Fi: `NetworkManager.service` ~8 s, then
`NetworkManager-wait-online` ~6 s. The jukebox itself does not wait for this (display, buttons, sounds and local
folders are up after ~5 s); only go-librespot needs the network.

Measured: the warning `Permissions for /lib/netplan/00-network-manager-all.yaml are too open` is *not* the cause.
`sudo chmod 600 /lib/netplan/00-network-manager-all.yaml` (done by the image build) silences it, but NetworkManager
still needs ~7 s between "ifupdown: interfaces file doesn't exist" and "dhcp: init". Cause not found yet.
