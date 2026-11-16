#!/usr/bin/env bash
# Build the jukebox image with pi-gen (inside Docker by default).
#   ./build.sh                 build from the committed state of the current checkout
#   NATIVE=1 ./build.sh        no Docker: run pi-gen's build.sh with sudo (Debian host)
#   PREPARE_ONLY=1 ./build.sh  prepare the pi-gen tree and stop (for inspection)
# The image contains exactly the committed state of slim/ (git archive), nothing else.
set -euo pipefail

PI_GEN_URL=https://github.com/RPi-Distro/pi-gen
PI_GEN_COMMIT=c0d2c9f2cffc08bc56850b0a3eb23178f4226e8a   # pi-gen branch arm64 (Trixie, 64-bit), pinned
# 32-bit instead (Pi Zero/1): pi-gen master, e.g. 6e3ff62bfd9c690a6a3d1d7de259d5e0af40cb78, and see versions.env

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
SLIM=${HERE#"$REPO"/}; SLIM=${SLIM%/image}
COMMIT=$(git -C "$REPO" rev-parse HEAD)

if [ -n "$(git -C "$REPO" status --porcelain -- "$SLIM")" ] && [ "${ALLOW_DIRTY:-0}" != 1 ]; then
    echo "error: uncommitted changes in $SLIM. The image only contains committed files." >&2
    echo "       Commit them, or set ALLOW_DIRTY=1 to build the last commit anyway." >&2
    exit 1
fi

WORK="$HERE/.build"; PIGEN="$WORK/pi-gen"
mkdir -p "$PIGEN"
if [ ! -d "$PIGEN/.git" ]; then
    git -C "$PIGEN" init -q
    git -C "$PIGEN" remote add origin "$PI_GEN_URL"
fi
if [ "$(git -C "$PIGEN" rev-parse -q --verify HEAD || true)" != "$PI_GEN_COMMIT" ]; then
    git -C "$PIGEN" fetch -q --depth 1 origin "$PI_GEN_COMMIT"
    git -C "$PIGEN" checkout -q --force FETCH_HEAD
fi

# Our stage: committed files plus the two generated ones (code snapshot, version).
rm -rf "$PIGEN/stage-jukebox"
cp -r "$HERE/stage-jukebox" "$PIGEN/stage-jukebox"
F="$PIGEN/stage-jukebox/00-jukebox/files"
git -C "$REPO" archive --format=tar --prefix=repo/ "HEAD:$SLIM" > "$F/jukebox.tar"
echo "$COMMIT" > "$F/VERSION"
touch "$PIGEN/stage2/SKIP_IMAGES"   # only our stage exports an image, not the plain Lite one
# Workaround: newer util-linux prints "/dev/loop0 (lost)" for `losetup -f` when the device node is missing in
# the container; pi-gen then cannot parse it ("mknod: invalid minor device number") and the export fails.
sed -i.bak 's#loopdev="$(losetup -f)"#loopdev="$(losetup -f | awk '"'"'{print $1}'"'"')"#' "$PIGEN/scripts/common"
rm -f "$PIGEN/scripts/common.bak"
grep -q "awk '{print \$1}'" "$PIGEN/scripts/common" || { echo "error: loop device patch did not apply" >&2; exit 1; }

cp "$HERE/config" "$PIGEN/config"
[ -f "$HERE/config.local" ] && cat "$HERE/config.local" >> "$PIGEN/config"

echo "jukebox commit: $COMMIT   pi-gen: $PI_GEN_COMMIT"
[ "${PREPARE_ONLY:-0}" = 1 ] && { echo "prepared in $PIGEN"; exit 0; }

cd "$PIGEN"
if [ "${NATIVE:-0}" = 1 ]; then sudo ./build.sh -c config; else PRESERVE_CONTAINER="${PRESERVE_CONTAINER:-1}" ./build-docker.sh -c config; fi
echo "image: $PIGEN/deploy/"
