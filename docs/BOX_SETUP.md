# Set up a new box from the image

Checklist for one box, from the SD card to a playing jukebox. Written for the image of `image/` (see
[image/README.md](../image/README.md) for building it). `<box>` is the box name from `boxes/<box>/` (for example
`feuerwehrv1`), `<user>` is your own login on the box. Commands run on the box over SSH unless it says otherwise.

Everything here was done by hand on real boxes, but the whole path from a fresh card has not been run end to end yet.

## 1. Before the first start: boot partition of the SD card

Mount the boot partition on your computer and put two files there.

**`jukebox.toml`** (copy `jukebox.toml.example`):

```toml
box = "feuerwehrv1"
wifi_ssid = "HomeOffice"
wifi_password = "YOUR-WIFI-PASSWORD"   # 8 to 63 characters; leave out for an open network
wifi_country = "DE"                    # two capital letters
```

Type the Wi-Fi password carefully: a wrong character (one capital letter too few cost an hour once) shows up only
as a failed Wi-Fi connection, see "Troubleshooting".

**`user-data`** (cloud-init, creates your login). This is a starting point, not a verified file; use the one that
worked on an earlier box if you have it:

```yaml
#cloud-config
users:
  - name: YOUR-USER
    groups: [sudo, audio]
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: "YOUR-PASSWORD"
    sudo: ALL=(ALL) ALL
ssh_pwauth: true
```

No `network-config`: the Wi-Fi comes from `jukebox.toml`. Do not set it in both places.

## 2. Files in the cloud

Put the private files of the box into `Jukebox2.0/boxes/<box>/` in Dropbox. The sync copies them to
`~/.config/jukebox/` ([SYNC.md](SYNC.md)). They are read at start, so restart after the sync.

| File | Content |
|---|---|
| `startup.mp3`, `shutdown.mp3` | start and shutdown sound (optional) |
| `idle.jpg` | boot picture, only for boxes with a display (optional) |
| `martinshorn.mp3` | siren, only `feuerwehrv1` (`hooks.py`) |

## 3. First start and checks

Power on (with a network cable if you can). The box configures itself and reboots once. Then:

```bash
hostname                                   # <box>, reachable as <box>.local
sudo journalctl -u jukebox-firstboot --no-pager | tail -20
nmcli device status                        # wlan0 connected
cat /opt/jukebox/VERSION                   # the commit the image was built from
```

## 4. rclone remote `dropbox`

The sync needs a remote called `dropbox` for the service user:

```bash
sudo -u jukebox env HOME=/var/lib/jukebox rclone config
```

`n` (new remote), name `dropbox`, type `dropbox`, leave client id and secret empty. Answer `n` when it asks to use a
web browser, then run `rclone authorize "dropbox"` on a computer with a browser and paste the token on the box.
Check:

```bash
sudo -u jukebox env HOME=/var/lib/jukebox rclone lsd dropbox:Jukebox2.0
```

## 5. Soloist (once per box)

Needs the API key from Spotify for Developers of the account the box plays with. The Spotify app of that account
must be open in the same network for the pairing.

```bash
sudo jukebox-soloist-update
read -rsp 'API key: ' KEY; echo
printf 'SOLOIST_API_KEY=%s\nSOLOIST_NAME=feuerwehrv1\n' "$KEY" | \
  sudo -u jukebox sh -c 'umask 077; cat > /var/lib/jukebox/.config/jukebox/soloist.env'

sudo systemctl stop soloist
sudo -u jukebox env HOME=/var/lib/jukebox XDG_RUNTIME_DIR=/run/user/$(id -u jukebox) \
  /opt/soloist/soloist --device-name feuerwehrv1 --api-key "$KEY" --ws 127.0.0.1:9090 --pair
unset KEY
sudo systemctl restart soloist jukebox
```

Use the same device name in both places. The key is a command line argument while the pairing runs and while the
service runs, so it shows up in `ps` (open point in `claude/image-soloist-handoff.md`).

## 6. Get the config files from the cloud

```bash
sudo -u jukebox env HOME=/var/lib/jukebox /opt/jukebox/venv/bin/jukebox \
  -c /var/lib/jukebox/.config/jukebox/config.toml sync --only config --dry-run
```

If the list is right, run it again without `--dry-run`, then `sudo systemctl restart jukebox`.

## 7. Check

```bash
systemctl status soloist jukebox --no-pager | head -20
journalctl -u jukebox -b --no-pager | tail -30
sudo -u jukebox env HOME=/var/lib/jukebox /opt/jukebox/venv/bin/jukebox \
  -c /var/lib/jukebox/.config/jukebox/config.toml spotify-check
```

The log shows whether the card reader was found. If its name differs from `device_name` in the box config, set
`device_name` to a part of the real name in `config.local.toml`. The PipeWire output of the service user should be at full volume (an older image left it at 0.40 and everything was
quiet):

```bash
sudo -u jukebox env XDG_RUNTIME_DIR=/run/user/$(id -u jukebox) wpctl get-volume @DEFAULT_AUDIO_SINK@
# if it says 0.40: sudo -u jukebox env XDG_RUNTIME_DIR=/run/user/$(id -u jukebox) wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0
```

Then press every button once, turn the encoder and
present a card.

## Troubleshooting

**Wi-Fi does not connect, `journalctl -u NetworkManager -b` shows `4way_handshake -> disconnected`, then
`no secrets`.** That is almost always a wrong password. Compare what is in `jukebox.toml` and in the profile with the
real one, without showing it (letters become `a`/`A`, digits `0`, special characters stay visible):

```bash
muster() { sed 's/[a-z]/a/g; s/[A-Z]/A/g; s/[0-9]/0/g'; }
read -rsp 'Real Wi-Fi password: ' PW; echo
echo "real   :"; printf %s "$PW" | muster; echo
echo "toml   :"; sed -n 's/^wifi_password *= *"\(.*\)"[[:space:]]*$/\1/p' /boot/firmware/jukebox.toml | muster
echo "profile:"; sudo sed -n 's/^psk=//p' /etc/NetworkManager/system-connections/jukebox-wifi.nmconnection | muster
unset PW
```

Correct `jukebox.toml` (`sudo nano /boot/firmware/jukebox.toml`) and either run the first boot again
([image/README.md](../image/README.md#run-the-first-boot-again)) or connect by hand over a cable:
`sudo nmcli --ask device wifi connect "<ssid>"`. A profile made by hand survives reboots. A wrong password does not
stop the first boot, the box just stays offline.
