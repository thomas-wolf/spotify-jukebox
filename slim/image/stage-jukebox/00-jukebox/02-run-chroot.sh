#!/bin/bash -e
# Runs inside the image's chroot (as root).

for g in audio gpio i2c spi dialout input; do
	getent group "${g}" >/dev/null || groupadd --system "${g}"
done
if ! id jukebox >/dev/null 2>&1; then
	useradd --system --create-home --home-dir /var/lib/jukebox --shell /usr/sbin/nologin jukebox
fi
usermod -aG audio,gpio,i2c,spi,dialout,input jukebox

install -d -o jukebox -g jukebox /var/lib/jukebox/music \
	/var/lib/jukebox/.config /var/lib/jukebox/.config/jukebox /var/lib/jukebox/.config/go-librespot
install -o jukebox -g jukebox -m 644 /opt/jukebox/repo/packaging/go-librespot-config.yml \
	/var/lib/jukebox/.config/go-librespot/config.yml

# venv with the apt-installed gpiod/evdev visible; builds from the local checkout, no network needed
python3 -m venv --system-site-packages /opt/jukebox/venv
/opt/jukebox/venv/bin/pip install --no-build-isolation --no-deps --no-cache-dir /opt/jukebox/repo
rm -rf /opt/jukebox/repo/build /opt/jukebox/repo/src/*.egg-info

# Raspberry Pi OS ships this file world-readable; netplan then refuses it and logs "Permissions ... are too open"
# several times per boot. This only silences that warning (it was measured NOT to speed up the boot).
# Harmless if the file does not exist.
if [ -f /lib/netplan/00-network-manager-all.yaml ]; then
	chmod 600 /lib/netplan/00-network-manager-all.yaml
fi

# Fail the build early if something is wrong
/opt/jukebox/venv/bin/jukebox --help >/dev/null
/opt/jukebox/venv/bin/python -c "import gpiod; assert hasattr(gpiod, 'request_lines'), 'libgpiod API v1 found, v2 needed'"
visudo -cf /etc/sudoers.d/jukebox
python3 -m py_compile /usr/local/sbin/jukebox-firstboot

# Keep the journal across reboots (first-boot problems are otherwise gone after the reboot)
install -d -m 2755 -g systemd-journal /var/log/journal

systemctl enable jukebox-firstboot.service go-librespot.service jukebox.service
