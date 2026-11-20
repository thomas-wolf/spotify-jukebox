#!/bin/bash -e
# Runs on the build host; ROOTFS_DIR is the image's file system. Working directory: this folder.
. ./versions.env

# Code: the committed tree, unpacked to /opt/jukebox/repo
install -d "${ROOTFS_DIR}/opt/jukebox"
rm -rf "${ROOTFS_DIR}/opt/jukebox/repo"
tar -xf files/jukebox.tar -C "${ROOTFS_DIR}/opt/jukebox"
install -m 644 files/VERSION "${ROOTFS_DIR}/opt/jukebox/VERSION"

# go-librespot: pinned version, checksum verified
tmp=$(mktemp -d)
curl -fsSL -o "${tmp}/gl.tar.gz" "https://github.com/devgianlu/go-librespot/releases/download/${GL_VERSION}/${GL_ASSET}"
echo "${GL_SHA256}  ${tmp}/gl.tar.gz" | sha256sum -c -
tar -xzf "${tmp}/gl.tar.gz" -C "${tmp}" go-librespot
install -D -m 755 "${tmp}/go-librespot" "${ROOTFS_DIR}/usr/local/bin/go-librespot"
rm -rf "${tmp}"

# Services: the units from packaging/ with the service user and its home swapped in (single source of truth)
units="${ROOTFS_DIR}/etc/systemd/system"
install -d "${units}"
for u in jukebox go-librespot soloist; do
	sed 's|/home/pi|/var/lib/jukebox|g; s|^User=pi$|User=jukebox|' "${ROOTFS_DIR}/opt/jukebox/repo/packaging/${u}.service" > "${units}/${u}.service"
	grep -q '^User=jukebox$' "${units}/${u}.service"
	if grep -q '/home/pi' "${units}/${u}.service"; then echo "${u}.service still names /home/pi" >&2; exit 1; fi
	install -D -m 644 "files/${u}.service.d.conf" "${units}/${u}.service.d/image.conf"
done
# Soloist: the binary is not part of the image (Spotify forbids passing it on); jukebox-soloist-update downloads it
install -D -m 755 "${ROOTFS_DIR}/opt/jukebox/repo/packaging/jukebox-soloist" "${ROOTFS_DIR}/usr/local/bin/jukebox-soloist"
install -D -m 755 "${ROOTFS_DIR}/opt/jukebox/repo/packaging/jukebox-soloist-update" "${ROOTFS_DIR}/usr/local/sbin/jukebox-soloist-update"
install -m 644 "${ROOTFS_DIR}/opt/jukebox/repo/packaging/soloist-update.service" "${units}/soloist-update.service"
install -m 644 "${ROOTFS_DIR}/opt/jukebox/repo/packaging/soloist-update.timer" "${units}/soloist-update.timer"
install -m 644 files/jukebox-firstboot.service "${units}/jukebox-firstboot.service"
install -D -m 755 files/jukebox-firstboot "${ROOTFS_DIR}/usr/local/sbin/jukebox-firstboot"
install -D -m 440 files/sudoers "${ROOTFS_DIR}/etc/sudoers.d/jukebox"

# PipeWire output of a new box starts at 100 % instead of WirePlumber's default of 0.40 (everything was too quiet)
install -D -m 644 files/51-jukebox-volume.conf "${ROOTFS_DIR}/etc/wireplumber/wireplumber.conf.d/51-jukebox-volume.conf"

# Template for the file the user puts on the boot partition
install -D -m 644 files/jukebox.toml.example "${ROOTFS_DIR}/boot/firmware/jukebox.toml.example"
