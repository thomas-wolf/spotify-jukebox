# Open tasks

Status of the Pferdeanhänger box and the rewrite. Tick items off here when they are done.

## Next up

- [ ] **Try the Wi-Fi from `jukebox.toml` on a real card** (`wifi_ssid`, `wifi_password`, `wifi_country`, written by
  `jukebox-firstboot` as a NetworkManager profile, see [image/README.md](../image/README.md#wi-fi)). Replaces the
  `network-config` route, whose profile was lost on real boxes. Then also check that `user-data` still gives the user.
- [ ] **Card reader (RDM6300, UART):** connect it, check that `id_format = "dec"` produces the same ids as the
  old v2 cards (`0013167757` style). If not, try `hex` or `float`, see [HARDWARE.md](HARDWARE.md).
- [ ] **Copy the audio folders** for the local-file cards (the four folders the import skipped, probably excluded by
  the filtered rclone copy; check with `rclone lsf`).
- [ ] **Make the old cards work:** import the remaining cards (`import-v2`), then scan every card once. One podcast
  folder is unsupported (no podcast support yet).

## On the box

- [ ] Spotify account: test an old account (a new one gets `refused the audio key`, see
  [TROUBLESHOOTING.md](TROUBLESHOOTING.md)).
- [ ] Shutdown button: sudoers entry (`/etc/sudoers.d/jukebox`), hold the SHIM button for 2 s; if the box does not
  power off, compare `pinctrl get 17` idle and pressed (polarity).
- [x] Startup time: the jukebox no longer waits for the network (ready after ~5 s). Spotify is ready after ~19 s;
  ~6 s of that are four systemd reloads triggered from `NetworkManager.service` at start (cause not found, see
  [TROUBLESHOOTING.md](TROUBLESHOOTING.md)). Parked.
- [x] Web UI: "Play" in the card list started a card only 20 to 40 s later while the USB reader was instant (the
  code path after the event is the same). Suspects: Wi-Fi power save of the Pi, lost SYNs with HTTP/1.0 (fixed in
  the code: keep-alive). Check on the box: `iw dev wlan0 get power_save`, `iw dev wlan0 link`; if power save is on,
  `nmcli connection modify HomeOffice 802-11-wireless.powersave 2` and reconnect. The log now shows each card
  with its source. Deployed 2026-11-19 (`f7ed4b0`): the user reports it is far better and the problem solved.
  Which part helped (keep-alive, lazy loading, polling) was not isolated; Wi-Fi power save was not checked.
- [ ] Idle picture and startup sound: put `idle.jpg`, `startup.mp3` into `Jukebox2.0/boxes/<box name>/` in Dropbox; the box
  pulls them (`config = "pull"`, now in the box configs). Needs a restart after the first pull. Not yet seen on the box.
- [ ] rclone sync against Dropbox (`[sync]` in `config.local.toml`, `config = "off"`).
- [ ] Check the rotation direction (180) and the overlay text size.

## Hardware

- [x] GPIO 20 (previous button): own overlay `jukebox-i2s-free-gpio20` (`[boot] i2s_free_gpio20`). Checked on the
  Pferdeanhaenger box (Pi 4): `pinctrl get 20` shows a plain input, the sound still works, the green button gives
  "previous". Pi 5 variant not written.

## Soloist

- [x] Soloist backend (code, tests), works on the Pferdeanhaenger by hand.
- [ ] Image with Soloist (units, wrapper, update timer, PipeWire, linger): written, NOT built or booted yet.
  Unverified: linger for the system user `jukebox` (`loginctl show-user jukebox`), PipeWire in the `jukebox`
  user session (`sudo -u jukebox XDG_RUNTIME_DIR=/run/user/$(id -u jukebox) wpctl status`), mpv through
  pipewire-alsa, first pairing as `jukebox`.
- [ ] Volume with Soloist is much quieter at `start_volume = 30` (PipeWire): the Pferdeanhaenger box now uses 80 (the
  cap `max_volume` is 80 as well); measure properly or add a curve if other boxes need it.
- [ ] On the hardware: previous/next, `set_volume`, seek, cold boot without a phone.
- [ ] Pairing without a phone nearby (or a helper command), API key out of `ps` if Soloist can read it from a file.

## Repository

- [ ] Make the repo private: new private repo plus a deploy key on the Pi (a fork cannot be made private).
- [ ] Update the project doc `claude/design-decisions.md`.

## Other boxes

- [ ] Pinouts for Sanka and the sliding-potentiometer box, each in its own `boxes/<name>/` (`feuerwehrv1` and `feuerwehrv2` exist).

## Maybe later

- [ ] Podcasts, Cover Art Archive as a cover source, split `cli.py`, detect go-librespot stopping by itself.
