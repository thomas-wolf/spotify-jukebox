# Open tasks

Status of the Pferdeanhänger box and the rewrite. Tick items off here when they are done.

## Next up

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
- [ ] Idle picture and startup sound: `~/.config/jukebox/idle.jpg`, `startup.mp3`.
- [ ] rclone sync against Dropbox (`[sync]` in `config.local.toml`, `config = "off"`).
- [ ] Check the rotation direction (180) and the overlay text size.

## Hardware

- [ ] GPIO 20 (previous-track button): owned by the I2S driver. Either a custom I2S overlay or re-solder to GPIO 3/7.

## Soloist

- [x] Soloist backend (code, tests), works on the Pferdeanhaenger by hand.
- [ ] Image with Soloist (units, wrapper, update timer, PipeWire, linger): written, NOT built or booted yet.
  Unverified: linger for the system user `jukebox` (`loginctl show-user jukebox`), PipeWire in the `jukebox`
  user session (`sudo -u jukebox XDG_RUNTIME_DIR=/run/user/$(id -u jukebox) wpctl status`), mpv through
  pipewire-alsa, first pairing as `jukebox`.
- [ ] Volume with Soloist is much quieter at `start_volume = 30` (PipeWire): measure and adjust, or add a curve.
- [ ] On the hardware: previous/next, `set_volume`, seek, cold boot without a phone.
- [ ] Pairing without a phone nearby (or a helper command), API key out of `ps` if Soloist can read it from a file.

## Repository

- [ ] Make the repo private: new private repo plus a deploy key on the Pi (a fork cannot be made private).
- [ ] Update the project doc `claude/design-decisions.md`.

## Other boxes

- [ ] Pinouts for Sanka, Feuerwehr and the sliding-potentiometer box, each in its own `boxes/<name>/`.

## Maybe later

- [ ] Podcasts, Cover Art Archive as a cover source, split `cli.py`, detect go-librespot stopping by itself.
