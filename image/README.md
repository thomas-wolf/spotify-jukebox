# Ready-made image

Builds an SD-card image of Raspberry Pi OS Lite (Trixie) with everything below the jukebox code already in
place, like a Dockerfile for the whole OS. Result: write the image, put a small file on the boot partition,
power on. Built with [pi-gen](https://github.com/RPi-Distro/pi-gen), the tool Raspberry Pi uses for its own images.

**Not run on real hardware yet (unverified).** The build and the first-boot script are tested only in pieces:
the first-boot logic by `tests/test_firstboot.py`, the stage script against a fake root file system. The
chroot part (`02-run-chroot.sh`), the Docker build and the first boot on a Pi have not been run.

## What is in the image

- Raspberry Pi OS Lite, Debian 13 "Trixie", 64-bit (arm64): Pi 3, 4, 5 and Zero 2 W. Not for the Pi Zero (W) and
  Pi 1, see "32-bit" below.
- Packages: `python3-libgpiod`, `python3-evdev`, `python3-pil`, `python3-spidev` (display), `mpv`, `alsa-utils`,
  `pipewire`, `pipewire-alsa`, `wireplumber`, `rclone`, `avahi-daemon`, `sudo`.
- The jukebox from the committed state of the repository in `/opt/jukebox/repo`, installed into `/opt/jukebox/venv`.
  `/opt/jukebox/VERSION` holds the git commit.
- go-librespot in a pinned version, checked against a SHA-256 sum (`stage-jukebox/00-jukebox/versions.env`).
- User `jukebox` (home `/var/lib/jukebox`) in the groups `audio gpio i2c spi dialout input`. Configuration lives
  in `/var/lib/jukebox/.config/jukebox/`, music in `/var/lib/jukebox/music`.
- Services `soloist`, `jukebox` and `jukebox-firstboot`, enabled, plus `soloist-update.timer` and the sudoers rule
  for `systemctl poweroff`. go-librespot is installed but off (`sudo systemctl enable --now go-librespot` and
  `backend = "go-librespot"` bring it back). Linger is on for `jukebox`: PipeWire runs in its user session at boot. The units are generated from `packaging/` (user and paths replaced at build time).

Not in the image: the Soloist binary (Spotify forbids passing it on; downloaded after the first boot), the API key and the Spotify login (once per box, see below), cards, music, Wi-Fi, user and password.

## Build

Needs Docker (or a Debian host with `NATIVE=1`), network and some disk space. From a clean checkout:

```
cd image
./build.sh
```

The result (`image_<date>-jukebox.img.xz`) ends up in `.build/pi-gen/deploy/` (with Podman pi-gen first drops it into `.build/pi-gen/`, `build.sh` moves it); `build.sh` prints where. Copy it out before you remove the container or the Podman VM. The image contains exactly the **committed** repository (the script
stops if there are uncommitted changes; `ALLOW_DIRTY=1` builds the last commit anyway). Pinned: the pi-gen
commit (`build.sh`), the jukebox commit (your checkout), go-librespot (`versions.env`). The Debian packages are
whatever Trixie has on the build day, so two builds on different days are not bit-identical.

Secrets and local choices go into `image/config.local` (not in git), e.g. `FIRST_USER_PASS`,
`PUBKEY_SSH_FIRST_USER`, `WPA_SSID`/`WPA_PASSWORD`. All variables: pi-gen's README.

`PREPARE_ONLY=1 ./build.sh` prepares the pi-gen tree without building.

## Set up a box

1. Write the image to the SD card (Raspberry Pi Imager: "Use custom"; set Wi-Fi, user and SSH there if you did
   not put them into `config.local`).
2. Mount the boot partition on your computer, copy `jukebox.toml.example` to `jukebox.toml` and edit it:

   ```toml
   box = "pferdeanhaenger"     # selects boxes/<box>/config.toml of the image
   # hostname = "pferdeanhaenger"   # optional, default: the box name
   ```

3. Insert the card and power on. The first boot reads the file once and then reboots by itself:
   - installs `boxes/<box>/config.toml` (and `hooks.py`) for the service user (links into the image),
   - sets the hostname (`<hostname>.local` in the network),
   - runs `jukebox setup --apply` (HiFiBerry overlay, on-board audio off, ...),
   - writes `/var/lib/jukebox/.firstboot-done` and reboots.
4. Soloist, once per box (the box needs network for this; user `jukebox` has no shell, so the commands run
   through `sudo -u jukebox`):
   ```
   sudo jukebox-soloist-update                       # downloads the binary into /opt/soloist
   sudo -u jukebox sh -c 'umask 077; printf "SOLOIST_API_KEY=...\nSOLOIST_NAME=Pferdeanhaenger\n" > /var/lib/jukebox/.config/jukebox/soloist.env'
   sudo -u jukebox env HOME=/var/lib/jukebox XDG_RUNTIME_DIR=/run/user/$(id -u jukebox) \
     /opt/soloist/soloist --device-name Pferdeanhaenger --api-key "..." --ws 127.0.0.1:9090 --pair
   sudo systemctl restart soloist jukebox
   ```
   The API key belongs to the Spotify account the box plays with ([INSTALL.md](../docs/INSTALL.md)). Pairing
   needs the Spotify app of that account in the same network. Check with `journalctl -u soloist -f` and
   `jukebox spotify-check`. The weekly `soloist-update.timer` keeps the 90-day build fresh.
5. Cards: `cards.toml` is not part of the image. Import (`jukebox import-v2`) or sync it, see
   [MIGRATION.md](../docs/MIGRATION.md) and [SYNC.md](../docs/SYNC.md).

The name must be lowercase letters, digits and `-` (maximum 63 characters). Anything else, an unknown key or
an unknown box stops the first boot with a message in `journalctl -u jukebox-firstboot`, and changes nothing.
The log also lists the boxes the image contains.

### A box that is not in the image

Put its files on the boot partition in a folder `jukebox/` (at least `config.toml`, optionally `hooks.py`)
next to `jukebox.toml`. They are copied instead of the box from the image. Better: add the box under `boxes/`
and rebuild.

### Run the first boot again

```
sudo rm /var/lib/jukebox/.firstboot-done
sudo reboot
```

`/boot/firmware/jukebox.toml` must still be there.

## Hostname and Raspberry Pi Imager

If you also set a hostname in the Imager, the one from `jukebox.toml` wins (it is set later). It is kept on
later boots because the first boot tells cloud-init to leave the hostname alone (`preserve_hostname`).
This depends on how the Pi OS release configures cloud-init **(unverified)**; if the hostname jumps back after
the first reboot, check `/etc/cloud/cloud.cfg.d/` and `user-data` on the boot partition.

## 32-bit (Pi Zero, Pi 1)

pi-gen builds 64-bit from its `arm64` branch (the default here) and 32-bit from `master`. For a 32-bit image
pin a `master` commit in `build.sh` and switch `GL_ASSET`/`GL_SHA256` in `versions.env` (both are in the file,
commented out). Not built or run **(unverified)**.

## Files

```
image/
  build.sh                      prepares pi-gen (pinned), adds the stage, builds
  config                        pi-gen settings
  stage-jukebox/                the pi-gen stage ("the Dockerfile")
    00-jukebox/00-packages      apt packages
    00-jukebox/01-run.sh        build host: code, go-librespot, units
    00-jukebox/02-run-chroot.sh in the image: user, venv, checks, enable services
    00-jukebox/files/           first-boot script and unit, drop-ins, sudoers, jukebox.toml.example
```
