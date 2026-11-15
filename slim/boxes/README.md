# Boxes

One folder per physical box. The folder is the source of truth for that box: pinout, readers, display,
sounds and hooks. The code is the same everywhere.

```
boxes/<name>/
  config.toml    # the box's configuration ([box] name = "<name>")
  hooks.py       # optional, only if the box has its own behaviour
  README.md      # pin table, wiring, quirks
```

## Add a box

1. Copy `examples/config.toml` to `boxes/<name>/config.toml`, set `[box] name`, fill in the pinout.
2. `jukebox -c boxes/<name>/config.toml pins` must report no errors (the tests check this for every box).
3. Write the pin table into `boxes/<name>/README.md` (physical pin, BCM, part).

## Install on a box

```bash
git pull
mkdir -p ~/.config/jukebox
ln -sf "$PWD/boxes/<name>/config.toml" ~/.config/jukebox/config.toml
ln -sf "$PWD/boxes/<name>/hooks.py"    ~/.config/jukebox/hooks.py     # only if the box has one
sudo ~/jukebox/venv/bin/python -m jukebox -c ~/.config/jukebox/config.toml setup --apply
```

Symlinks keep the box in step with the repository. Use `cp` instead if the box has no clone of the repository.
`cards.toml` and the music are not part of a box folder; they are shared and live in the cloud (see docs/SYNC.md).

## Private files: by convention in `~/.config/jukebox/`

Everything that must not be in the repository goes into the configuration folder on the box, never into
`boxes/`. Currently the boot / idle picture: `~/.config/jukebox/idle.jpg` (or `.png`, `.jpeg`, `.webp`), found
automatically. With cloud sync (`config = "pull"`) the file may also live in the cloud under
`<remote>/boxes/<name>/idle.jpg` and is copied there.
