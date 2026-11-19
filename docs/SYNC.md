# Cloud synchronisation (Dropbox, OneDrive, ...)

Cards, configuration and music can be kept in a cloud folder. The jukebox uses
[rclone](https://rclone.org) for the transfer; rclone knows Dropbox, OneDrive and many other services.
The jukebox itself needs nothing else.

## What goes where

One cloud folder holds everything (here called `Jukebox`):

```
Jukebox/
  cards.toml                shared by all boxes   <->  ~/.config/jukebox/cards.toml     (both ways)
  music/                    shared by all boxes   ->   [local] root                      (cloud to box)
  boxes/
    kitchen/                one folder per box    ->   ~/.config/jukebox/               (cloud to box)
      config.toml
      hooks.py
      idle.jpg              boot / idle picture
      startup.mp3           boot sound (shutdown.mp3: shutdown sound)
    bedroom/
      config.toml
```

The folder name under `boxes/` is `[box] name` from the box's `config.toml`.

| Part | Default | What happens |
|---|---|---|
| Cards | `both` | Merged card by card. A card added or changed on one side arrives on the other. A card changed on both sides differently: the cloud version is kept and the conflict is logged. Cards deleted on one side are deleted on the other. |
| Config | `pull` | Files from `boxes/<name>/` are copied to the config folder, except `cards.toml` and backup files. A local file that is newer than the cloud file is not overwritten. Nothing is deleted. A change of `config.toml`, `hooks.py`, the idle picture (`idle.*`) or the startup / shutdown sound is used after the next restart (the log says so). |
| Music | `pull` | New and changed files are copied from `music/` to the music folder. Nothing is deleted unless `delete = true`. |

`cards = "pull"` makes the cloud the master (local changes in cards are discarded), `"push"` the other way,
`"off"` leaves the part alone. `config` and `music` are `pull` or `off`.

If you want every box to have its own cards: `cards_per_box = true` uses `boxes/<name>/cards.toml`.

When you change cards in the web interface, the sync starts about ten seconds later, so a card you
add in the morning is on your other boxes within minutes. Otherwise it runs after start (45 seconds) and every
`interval_minutes` (30). A cloud change of `cards.toml` is loaded into the running box without a restart.

## Setting it up

1. **Install rclone** on the box: `sudo apt install rclone`. Your distribution's version may be older than the
   current one on rclone.org; which one you need for Dropbox and OneDrive is not something I checked.
2. **Create the remote** (this logs rclone in to your cloud account), as the user that runs the jukebox:
   `rclone config`, then `n` for a new remote, a name (for example `dropbox`), the type (`dropbox` or
   `onedrive`), and answer the questions. The login needs a web browser. A box without a screen has none, so
   rclone offers a way around it: answer `N` to the question about the web browser (older versions word it
   "Use auto config?"), and rclone asks for a `config_token`. Then run `rclone authorize "dropbox"` (or
   `"onedrive"`) on a computer with a browser and rclone, log in there, and paste the token it prints into the
   box. rclone's page on remote setup describes it, also with an SSH tunnel as an alternative.
3. **Check it:** `rclone lsd dropbox:` lists the top-level folders of the account.
4. **Put the files in the cloud** in the layout above. For the first run you may only have `Jukebox/music/`
   and `Jukebox/boxes/<name>/config.toml`; cards can be created on the box or in the cloud.
5. **Configure the jukebox** in `config.toml`:
   ```toml
   [sync]
   enabled = true
   remote = "dropbox:Jukebox"
   ```
6. **Test:** `jukebox sync --check` (is rclone found and the remote reachable?), then `jukebox sync --dry-run`
   (shows what would happen and changes nothing), then `jukebox sync`.
7. Restart the service. From then on the sync runs in the background, at low priority (`nice`).

`jukebox sync --only cards` (or `config`, `music`, comma separated) runs only part of it.

## Settings (`[sync]`)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Run the sync in the background while the box runs |
| `remote` | | rclone remote and folder, `dropbox:Jukebox`. Required. |
| `interval_minutes` | `30` | How often everything is checked |
| `first_run_delay` | `45` | Seconds after start before the first run (time for the network to come up) |
| `cards` | `both` | `both`, `pull`, `push`, `off` |
| `cards_per_box` | `false` | One `cards.toml` per box instead of a shared one |
| `config` | `pull` | `pull` or `off` |
| `music` | `pull` | `pull` or `off` |
| `delete` | `false` | Music: also remove files from the box that are gone from the cloud (`rclone sync`, at most 100 files per run). Refuses to run when the cloud folder does not exist. Cover pictures the jukebox saved itself would be removed too; set `[covers] write_to_folder = false` to avoid that. |
| `bwlimit` | none | Speed limit for the music download, e.g. `"2M"` |
| `rclone` | `rclone` | Program name or path |
| `rclone_config` | rclone's default | Path of an rclone configuration file if it is not in the default place |

## Things to know

- **Cards and comments:** When the sync writes `cards.toml` the comments in it are lost (the same happens
  when you save in the web interface). Before the sync replaces your local file it keeps a copy as
  `cards.toml.sync.bak`.
- **Two boxes, one card file:** Works, with the merge above. If two people change the same card at the same time,
  one of the versions loses (the cloud's).
- **Do not point it at the Dropbox folder of an installed Dropbox client.** The box does not run one; rclone
  talks to Dropbox directly.
- **Rate limits and large libraries:** The first download of a big music folder takes a long time and some
  services limit the request rate. `bwlimit` and the low priority keep the box usable; I have not tried it with a
  large library.
- **Login expires:** If the cloud login is withdrawn or expires, the sync fails with an error message from rclone
  in the log (`journalctl -u jukebox`) and a message in the web interface; playing is not affected.
- **Not synchronised:** Resume positions, the cover cache and `config.txt`.
