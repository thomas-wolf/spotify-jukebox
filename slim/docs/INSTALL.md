# Installation

This guide takes a blank Raspberry Pi to a working box. Steps I have not tried on real hardware are marked
**(unverified)**.

## Requirements

- Raspberry Pi with a 40-pin header and Wi-Fi or Ethernet.
- **Raspberry Pi OS based on Debian 13 "Trixie"** (Lite is enough). Reason: the GPIO code uses the Python
  bindings of libgpiod 2. Trixie ships `python3-libgpiod` 2.2.1, Bookworm only 1.6.3, which has a different
  API. On Bookworm, 2.1.3 is available from `bookworm-backports`.
- A **Spotify Premium account**. Playback does not work with a free account.
- HiFiBerry MiniAmp (or another DAC profile, see [HARDWARE.md](HARDWARE.md)).
- A computer with SSH to set the box up.

**Pi Zero (ARMv6):** The MiniAmp is built for the Pi Zero. I have not checked whether go-librespot offers
prebuilt binaries for it **(unverified)**. Look at the
[release page](https://github.com/devgianlu/go-librespot/releases/latest). If `uname -m` prints `armv6l` and
there is no binary, you have to build the program yourself.

## 1. Prepare the system

Use the Raspberry Pi Imager to write Raspberry Pi OS Lite (Trixie) to the SD card. In the Imager settings,
set hostname, user, Wi-Fi and SSH. This guide assumes the user `pi`. If your user has another name, replace
`pi` in the commands and in the files under `packaging/`.

```
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv python3-libgpiod python3-evdev mpv alsa-utils git
```

You only need `python3-evdev` for USB readers. I have not checked the package name **(unverified)**; if apt
cannot find it, search with `apt search evdev`.

## 2. Install the jukebox

```
git clone -b rewrite/slim-core https://github.com/thomas-wolf/spotify-jukebox ~/spotify-jukebox
cd ~/spotify-jukebox/slim
sudo python3 -m venv --system-site-packages /opt/jukebox/venv
sudo /opt/jukebox/venv/bin/pip install .
```

`--system-site-packages` makes the apt-installed modules `gpiod` and `evdev` visible inside the venv. Check:

```
/opt/jukebox/venv/bin/jukebox --help
```

## 3. Create the configuration

```
mkdir -p ~/.config/jukebox ~/music
cp examples/config.toml examples/cards.toml ~/.config/jukebox/
nano ~/.config/jukebox/config.toml
```

At least adjust these parts: the reader (`[readers.usb]` or `[readers.rdm6300]`, set unused ones to
`enabled = false`), the `[[gpio.*]]` entries (remove hardware you do not have) and `[boot]`. All keys are
explained in [CONFIG.md](CONFIG.md).

The example cards in `cards.toml` are placeholders. Delete or replace them later.

## 4. Set the overlays and reboot

`jukebox setup` first only shows what it would change:

```
/opt/jukebox/venv/bin/jukebox setup
```

For the MiniAmp (`audio = "hifiberry-miniamp"`) the diff looks like this: `dtparam=audio=on` is commented
out and a marked block with `dtoverlay=hifiberry-dac` (plus `dtparam=spi=on` if `spi = true`) is added. The
overlay and turning off the on-board audio match HiFiBerry's own documentation. Apply it:

```
sudo /opt/jukebox/venv/bin/jukebox setup --apply
sudo reboot
```

Writing `/boot/firmware/config.txt` needs root. Without `sudo` you get a "permission denied" message that shows
the command to use. Under `sudo`, `~` still means your own home, so the default configuration file
is found. If you keep it somewhere else, add `-c /full/path/config.toml` (before `setup`). Before the first
change the tool puts `config.txt.jukebox.bak` next to the original. To roll back, copy the backup back.

After the reboot the DAC must show up as a sound card:

```
aplay -l
```

A card named `sndrpihifiberry` should appear. A quick test:

```
speaker-test -t sine -f 440 -l 1
```

No sound? See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## 5. Install go-librespot

1. On the [release page](https://github.com/devgianlu/go-librespot/releases/latest) download the Linux
   archive for your architecture. `uname -m` tells you which: `aarch64` is 64-bit ARM, `armv7l` is 32-bit
   ARM, `armv6l` is the Pi Zero. I cannot give the exact file names **(unverified)**.
2. Unpack it and put the program in `/usr/local/bin/` (`sudo install -m 755 ... /usr/local/bin/`). If the
   file is not called `go-librespot`, adjust `ExecStart` in `packaging/go-librespot.service`.
3. Create the configuration:
   ```
   mkdir -p ~/.config/go-librespot
   cp ~/spotify-jukebox/slim/packaging/go-librespot-config.yml ~/.config/go-librespot/config.yml
   ```
   The important parts are `credentials.type: device_auth` (login with a code, no browser needed on the
   box) and `server.enabled: true`. The REST API then listens on `localhost:3678`.
4. Set up the service:
   ```
   sudo cp ~/spotify-jukebox/slim/packaging/go-librespot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now go-librespot
   journalctl -u go-librespot -f
   ```
5. **One-time login:** The log shows a link and a code. Open <https://www.spotify.com/pair> on any device,
   enter the code and confirm. The daemon stores the credentials itself. Afterwards "Jukebox" shows up as a
   device in your Spotify app.

## 6. Check the Spotify connection

```
/opt/jukebox/venv/bin/jukebox spotify-check
```

Output without `FAILED` means the daemon answers. **Important:** The endpoints in `players/spotify.py` do not
come from go-librespot's specification, they are my assumption **(unverified)**. If `spotify-check` fails or
nothing happens when you put a card on the reader, compare the `ENDPOINTS` table with the file
`api-spec.yml` in the go-librespot repository and adjust it. It is a one-place change.

## 7. Set up the service

Hardware permissions:

```
sudo usermod -aG audio,gpio,i2c,spi,dialout,input pi
```

Install and start the service:

```
sudo cp ~/spotify-jukebox/slim/packaging/jukebox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jukebox
journalctl -u jukebox -f
```

To try things out you can start the box in the foreground first (Ctrl-C ends it):

```
/opt/jukebox/venv/bin/jukebox -v run
```

**Shutting down by card or button:** A service often may not run `systemctl poweroff` as is. Allow it
specifically for the user:

```
echo 'pi ALL=NOPASSWD: /usr/bin/systemctl poweroff' | sudo tee /etc/sudoers.d/jukebox
sudo chmod 440 /etc/sudoers.d/jukebox
```

and set in `config.toml`:

```toml
[system]
shutdown_command = ["sudo", "systemctl", "poweroff"]
```

## 8. Add cards

Put an unknown card on the reader. The log shows `unknown card <ID>`. Then:

```
/opt/jukebox/venv/bin/jukebox cards add 0123456789 --play spotify:playlist:PLAYLIST-ID --name "Good night"
/opt/jukebox/venv/bin/jukebox cards add 0123456790 --play folder:audiobooks/pumuckl
/opt/jukebox/venv/bin/jukebox cards add 0123456791 --action volume_up
/opt/jukebox/venv/bin/jukebox cards list
sudo systemctl restart jukebox
```

Cards are read at startup. Restart the service after every change to `cards.toml` that you make by hand.
(Changes made through the web interface, step 10, take effect at once.)

You already have cards in use with Phoniebox v2? Do not add them one by one: `jukebox import-v2` imports
them all at once, see [MIGRATION.md](MIGRATION.md).

You find the Spotify URI in the Spotify app under "Share" -> "Copy link". `https://open.spotify.com/playlist/ABC123?si=...`
becomes `spotify:playlist:ABC123`. Local folders live under the `root` from the configuration (default
`~/music`) and are written as `folder:<relative path>`.

## 9. Several boxes

Every box has its own `config.toml` (pinout, readers, sounds, `hooks.py`). The repository and the code are
the same everywhere. A new box is: steps 1 to 8, then copy `config.toml` and `cards.toml` from an existing box
and adjust the hardware sections.

## 10. Web interface (optional)

Switch it on in `config.toml`:

```toml
[web]
enabled = true
port = 8080
```

After a restart it is at `http://<name-of-the-box>.local:8080/` (or the IP address of the Pi). Put a card on
the reader and the ID appears on the page; paste a Spotify link or pick a folder and save. The card works
immediately, no restart. See [CONFIG.md](CONFIG.md#web) for details.

**There is no password.** Everybody in your network can change cards and control the box. Do not forward the
port to the internet.

## Updating

```
cd ~/spotify-jukebox && git pull
cd slim && sudo /opt/jukebox/venv/bin/pip install --upgrade .
sudo systemctl restart jukebox
```

You update go-librespot by replacing the binary with one from a newer release and restarting the service. If
Spotify suddenly stops playing after a protocol change, this is the first thing to try.

## Uninstalling

```
sudo systemctl disable --now jukebox go-librespot
sudo rm /etc/systemd/system/jukebox.service /etc/systemd/system/go-librespot.service
sudo rm -r /opt/jukebox
```

Remove the marked block from `config.txt` by hand or restore `config.txt.jukebox.bak`.
