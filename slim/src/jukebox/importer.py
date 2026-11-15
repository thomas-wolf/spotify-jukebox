"""Import card assignments from a Phoniebox v2 installation (or a copy of its `shared/` and `settings/`)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import render_cards
from pathlib import Path

CONTROL_ACTIONS: dict[str, tuple[str, dict]] = {
    "CMDVOLUP": ("volume_up", {}), "CMDVOLDOWN": ("volume_down", {}),
    "CMDMUTE": ("mute", {}), "CMDNEXT": ("next", {}), "CMDPREV": ("prev", {}),
    "CMDPAUSE": ("play_pause", {}), "CMDPLAY": ("resume", {}), "CMDSTOP": ("stop", {}),
    "CMDSEEKFORW": ("seek_forward", {}), "CMDSEEKBACK": ("seek_back", {}),
    "CMDSHUTDOWN": ("shutdown", {}),
}
for _v in (30, 50, 75, 80, 85, 90, 95, 100):
    CONTROL_ACTIONS[f"CMDVOL{_v}"] = ("volume_set", {"value": _v})

SOURCE_FILES = {"podcast.txt": "podcast", "url.txt": "url", "youtube.txt": "youtube"}
_SPOTIFY_URL = re.compile(r"https?://open\.spotify\.com/(?:intl-[a-z]+/)?(playlist|album|track|artist|show|episode)/([A-Za-z0-9]+)")
_SPOTIFY_USER = re.compile(r"^spotify:user:[^:]+:playlist:([A-Za-z0-9]+)$")
_CONF_LINE = re.compile(r'^\s*([A-Z0-9_]+)\s*=\s*"?([^"#]*?)"?\s*(?:#.*)?$')


@dataclass
class Entry:
    id: str
    name: str = ""
    play: str | None = None
    action: str | None = None
    args: dict = field(default_factory=dict)


@dataclass
class ImportResult:
    entries: list[Entry] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)    # (card id, reason)
    unused: list[str] = field(default_factory=list)                 # ids that were never assigned


def normalize_spotify(text: str) -> str | None:
    """Return a `spotify:<type>:<id>` URI from whatever v2 stored, or None."""
    t = text.strip().splitlines()[0].strip() if text.strip() else ""
    m = _SPOTIFY_URL.search(t)
    if m:
        return f"spotify:{m.group(1)}:{m.group(2)}"
    m = _SPOTIFY_USER.match(t)
    if m:
        return f"spotify:playlist:{m.group(1)}"
    if re.match(r"^spotify:[a-z]+:[A-Za-z0-9]+$", t):
        return t
    return None


def find_roots(src: Path) -> tuple[Path | None, Path | None, Path | None]:
    """Locate (shortcuts, audiofolders, rfid_trigger_play.conf) below `src`, which may be the v2 root,
    its `shared/` folder, or a folder holding copies."""
    def first(*cands: Path) -> Path | None:
        return next((c for c in cands if c.exists()), None)
    shortcuts = first(src / "shared" / "shortcuts", src / "shortcuts")
    folders = first(src / "shared" / "audiofolders", src / "audiofolders")
    conf = first(src / "settings" / "rfid_trigger_play.conf", src / "rfid_trigger_play.conf")
    return shortcuts, folders, conf


def read_control_cards(conf: Path) -> tuple[list[Entry], list[tuple[str, str]]]:
    entries: list[Entry] = []
    skipped: list[tuple[str, str]] = []
    for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CONF_LINE.match(line)
        if not m or line.lstrip().startswith("#"):
            continue
        key, card_id = m.group(1), m.group(2).strip()
        if not card_id or card_id.startswith("%"):
            continue                                           # unset / template placeholder
        if key in CONTROL_ACTIONS:
            action, args = CONTROL_ACTIONS[key]
            entries.append(Entry(card_id, name=key, action=action, args=dict(args)))
        else:
            skipped.append((card_id, f"control card {key} has no equivalent"))
    return entries, skipped


def convert(src: Path) -> ImportResult:
    shortcuts, folders, conf = find_roots(src)
    res = ImportResult()
    if conf:
        ents, skip = read_control_cards(conf)
        res.entries += ents
        res.skipped += skip
    if shortcuts is None:
        raise FileNotFoundError(f"no shortcuts folder below {src}")
    control_ids = {e.id.lower() for e in res.entries}
    for f in sorted(shortcuts.iterdir()):
        if not f.is_file() or f.name.startswith(".") or f.name == "placeholder":
            continue
        card_id = f.name
        if card_id.lower() in control_ids:
            continue
        folder = (f.read_text(encoding="utf-8", errors="replace").strip().splitlines() or [""])[0].strip()
        if folder in ("", card_id):
            res.unused.append(card_id)                         # v2 writes these on first use, never assigned
            continue
        if ".." in Path(folder).parts or folder.startswith("/"):
            res.skipped.append((card_id, f"unsafe folder name {folder!r}"))
            continue
        res.entries.append(_resolve(card_id, folder, folders, res))
    res.entries = [e for e in res.entries if e is not None]
    return res


def _resolve(card_id: str, folder: str, folders: Path | None, res: ImportResult) -> Entry | None:
    if folders is None or not (folders / folder).is_dir():
        res.skipped.append((card_id, f"folder {folder!r} not found (not copied, or wrong name)"))
        return None
    d = folders / folder
    sp = d / "spotify.txt"
    if sp.exists():
        uri = normalize_spotify(sp.read_text(encoding="utf-8", errors="replace"))
        if uri is None:
            res.skipped.append((card_id, f"spotify.txt in {folder!r} is not a recognisable Spotify link"))
            return None
        return Entry(card_id, name=folder, play=uri)
    live = d / "livestream.txt"
    if live.exists():
        url = (live.read_text(encoding="utf-8", errors="replace").strip().splitlines() or [""])[0].strip()
        if url.startswith(("http://", "https://")) and " " not in url:
            return Entry(card_id, name=folder, play=f"stream:{url}")
        res.skipped.append((card_id, f"livestream.txt in {folder!r} does not contain a http(s) address"))
        return None
    for fname, kind in SOURCE_FILES.items():
        if (d / fname).exists():
            res.skipped.append((card_id, f"{kind} folder {folder!r} is not supported"))
            return None
    return Entry(card_id, name=folder, play=f"folder:{folder}")


def render(entries: list[Entry]) -> str:
    return render_cards(entries)
