# Ready-made image

Builds an SD-card image of Raspberry Pi OS Lite (Trixie) with everything below the jukebox code already in
place, like a Dockerfile for the whole OS. Result: write the image, put a small file on the boot partition,
power on. Built with [pi-gen](https://github.com/RPi-Distro/pi-gen), the tool Raspberry Pi uses for its own images.

**Not run on real hardware yet (unverified).** The build and the first-boot script are tested only in pieces:
the first-boot logic by `tests/test_firstboot.py`, the stage script against a fake root file system. The
chroot part (`02-run-chroot.sh`), the Docker build and the first boot on a Pi have not been run.

## What is in the image

- Raspberry Pi OS Lite, Debian 13 "Trixie", 32-bit (armhf, runs on every Pi including the Zero).
- Packages: `python3-libgpiod`, `python3-evdev`, `mpv`, `alsa-utils`, `rclone`, `avahi-daemon`, `sudo`.
- The jukebox from the committed state of `slim/` in `/opt/jukebox/repo`, installed into `/opt/jukebox/venv`.
  `/opt/jukebox/VERSION` holds the git commit.
- go-librespot in a pinned version, checked against a SHA-256 sum (`stage-jukebox/00-jukebox/versions.env`).
- User `jukebox` (home `/var/lib/jukebox`) in the groups `audio gpio i2c spi dialout input`. Configuration lives
  in `/var/lib/jukebox/.config/jukebox/`, music in `/var/lib/jukebox/music`.
- Services `go-librespot`, `jukebox` and `jukebox-firstboot`, all enabled, plus the sudoers rule for
  `systemctl poweroff`. The units are generated from `packaging/` (user and paths replaced at build time).

Not in the image: Spotify login (once per box, see below), cards, music, Wi-Fi, user and password.

## Build

Needs Docker (or a Debian host with `NATIVE=1`), network and some disk space. From a clean checkout:

```
cd slim/image
./build.sh
```

The result is in `.build/pi-gen/deploy/`. The image contains exactly the **committed** `slim/` (the script
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
4. Spotify login, once per box: `journalctl -u go-librespot -f` shows a code, enter it at
   <https://www.spotify.com/pair>.
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

## 64-bit

pi-gen builds 32-bit from `master` and 64-bit from its `arm64` branch. For a 64-bit image pin an `arm64`
commit in `build.sh` and set `GL_ASSET=go-librespot_linux_arm64.tar.gz` plus its checksum in `versions.env`
(that file name is **unverified**).

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
