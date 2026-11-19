"""Synchronisation with cloud storage (Dropbox, OneDrive, ... through rclone).

What is synchronised, with the default modes:
  cards.toml                      both ways, merged card by card (3-way), also after a change in the web UI
  config folder (config.toml,     cloud -> box, per box: <remote>/boxes/<box name>/
    hooks.py, sounds/, ...)
  music folder                    cloud -> box: <remote>/music/

rclone is an external program (apt package or download from rclone.org); the cloud login is set up once with
`rclone config`. Everything here runs rclone as a subprocess, so the module itself needs nothing else.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import events as ev
from .config import Card, ConfigError, load_cards, render_cards

log = logging.getLogger(__name__)

CARD_MODES = ("both", "pull", "push", "off")
PULL_MODES = ("pull", "off")
KEEP_LOCAL = ("cards.toml", "*.bak", "*.tmp", "*.jukebox.bak", "sync.json")   # never overwritten by a config pull
# Files that are only read when the jukebox starts: after a change a restart is needed (boot / idle picture, sounds).
RESTART_FILES = ("config.toml", "hooks.py",
                 *(f"idle.{e}" for e in ("jpg", "jpeg", "png", "webp")),
                 *(f"{stem}.{e}" for stem in ("startup", "shutdown") for e in ("mp3", "ogg", "wav", "flac", "m4a")))


class SyncError(Exception):
    pass


@dataclass(frozen=True)
class SyncSettings:
    remote: str = ""
    rclone: str = "rclone"
    rclone_config: str = ""
    interval_minutes: int = 30
    first_run_delay: int = 45
    bwlimit: str = ""
    delete: bool = False
    cards: str = "both"
    cards_per_box: bool = False
    config: str = "pull"
    music: str = "pull"

    @classmethod
    def from_section(cls, d: dict) -> "SyncSettings":
        s = cls(remote=str(d.get("remote", "")), rclone=str(d.get("rclone", "rclone")),
                rclone_config=str(d.get("rclone_config", "")),
                interval_minutes=int(d.get("interval_minutes", 30)),
                first_run_delay=int(d.get("first_run_delay", 45)), bwlimit=str(d.get("bwlimit", "")),
                delete=bool(d.get("delete", False)), cards=str(d.get("cards", "both")),
                cards_per_box=bool(d.get("cards_per_box", False)), config=str(d.get("config", "pull")),
                music=str(d.get("music", "pull")))
        if not s.remote or ":" not in s.remote:
            raise ConfigError('[sync] remote must look like "dropbox:Jukebox" (rclone remote, colon, folder)')
        if s.cards not in CARD_MODES:
            raise ConfigError(f"[sync] cards must be one of {CARD_MODES}")
        if s.config not in PULL_MODES or s.music not in PULL_MODES:
            raise ConfigError(f"[sync] config and music must be one of {PULL_MODES}")
        if s.interval_minutes < 1:
            raise ConfigError("[sync] interval_minutes must be at least 1")
        return s


def join_remote(base: str, *parts: str) -> str:
    out = base
    for part in parts:
        out = out + part if out.endswith(":") or out.endswith("/") else out + "/" + part
    return out


# -- rclone -------------------------------------------------------------------------
Runner = Callable[[list], "tuple[int, str, str]"]


def _run(argv: list, timeout: float = 6 * 3600) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SyncError(f"{argv[0]} not found: install rclone") from exc
    except subprocess.TimeoutExpired as exc:
        raise SyncError("rclone timed out") from exc
    return p.returncode, p.stdout, p.stderr


class Rclone:
    def __init__(self, s: SyncSettings, runner: Runner = _run, low_priority: bool = True) -> None:
        self.s, self._runner = s, runner
        self._prefix = ["nice", "-n", "19"] if low_priority and shutil.which("nice") else []

    def run(self, *args: str, bandwidth: bool = False) -> tuple[int, str, str]:
        if self._runner is _run and shutil.which(self.s.rclone) is None:
            raise SyncError(f"{self.s.rclone} not found: install rclone (sudo apt install rclone)")
        argv = [*self._prefix, self.s.rclone]
        if self.s.rclone_config:
            argv += ["--config", self.s.rclone_config]
        argv += ["--contimeout", "20s", "--timeout", "60s", "--low-level-retries", "3"]
        if bandwidth and self.s.bwlimit:
            argv += ["--bwlimit", self.s.bwlimit]
        return self._runner(argv + list(args))

    def stat(self, remote_path: str) -> dict | None:
        """lsjson --stat of one file: dict, or None when it does not exist. Other errors raise SyncError."""
        code, out, err = self.run("lsjson", "--stat", "--no-mimetype", remote_path)
        if code == 0:
            try:
                return json.loads(out)
            except ValueError as exc:
                raise SyncError(f"unreadable answer from rclone: {exc}") from exc
        if code in (3, 4) or "not found" in err.lower():
            return None
        raise SyncError(f"rclone lsjson failed ({code}): {err.strip()[:300]}")

    def check(self, *args: str, bandwidth: bool = False) -> str:
        code, out, err = self.run(*args, bandwidth=bandwidth)
        if code != 0:
            raise SyncError(f"rclone {args[0]} failed ({code}): {err.strip()[:300]}")
        return out


# -- cards: 3-way merge ---------------------------------------------------------------
def _sig(c: Card) -> tuple:
    return (c.name, c.play, c.action, tuple(sorted((c.args or {}).items())))


def _by_id(cards: dict[str, Card]) -> dict[str, Card]:
    return {k.lower(): v for k, v in cards.items()}


def merge_cards(base: dict[str, Card], local: dict[str, Card], remote: dict[str, Card]):
    """Merge per card. A change on one side wins over no change on the other; a card changed on both sides
    differently is a conflict and the cloud version wins. Returns (merged cards, ids of conflicts)."""
    b, l, r = _by_id(base), _by_id(local), _by_id(remote)
    merged: dict[str, Card] = {}
    conflicts: list[str] = []
    for key in {*b, *l, *r}:
        bs = _sig(b[key]) if key in b else None
        ls = _sig(l[key]) if key in l else None
        rs = _sig(r[key]) if key in r else None
        if ls == rs:
            pick = l.get(key)
        elif ls == bs:
            pick = r.get(key)
        elif rs == bs:
            pick = l.get(key)
        else:
            conflicts.append(key)
            pick = r.get(key)
        if pick is not None:
            merged[pick.id] = pick
    return merged, sorted(conflicts)


def same_cards(a: dict[str, Card], b: dict[str, Card]) -> bool:
    ia, ib = _by_id(a), _by_id(b)
    return ia.keys() == ib.keys() and all(_sig(ia[k]) == _sig(ib[k]) for k in ia)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@dataclass
class SyncResult:
    cards_changed: bool = False
    config_changed: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


SYNC_STATUS_FILE = "sync-status.json"


def sync_status_path(data_dir: Path) -> Path:
    return data_dir / SYNC_STATUS_FILE


def write_sync_status(path: Path, res: SyncResult, now: float | None = None) -> None:
    """Remember when the last sync ran, for the status API (Home Assistant). A failure here is only logged."""
    stamp = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    data = {"last_run": stamp.isoformat(timespec="seconds"), "ok": not res.errors,
            "cards_changed": res.cards_changed, "errors": res.errors}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, json.dumps(data, indent=2) + "\n")
    except OSError:
        log.warning("could not write sync status to %s", path, exc_info=True)


class Syncer:
    def __init__(self, s: SyncSettings, box_name: str, config_dir: Path, cards_path: Path, music_root: Path,
                 data_dir: Path, runner: Runner = _run) -> None:
        self.s, self.box, self.config_dir = s, box_name, config_dir
        self.cards_path, self.music_root, self.data_dir = cards_path, music_root, data_dir
        self.rclone = Rclone(s, runner)
        self._dir = data_dir / "sync"
        self._lock = threading.Lock()

    # remote locations
    def _box(self) -> str:
        return join_remote(self.s.remote, "boxes", self.box)

    def _cards_remote(self) -> str:
        return join_remote(self._box() if self.s.cards_per_box else self.s.remote, "cards.toml")

    # -- everything --------------------------------------------------------------------
    def run_once(self, parts=("cards", "config", "music"), dry_run: bool = False) -> SyncResult:
        res = SyncResult()
        with self._lock:
            steps = {"cards": (self.s.cards, self._cards), "config": (self.s.config, self._config),
                     "music": (self.s.music, self._music)}
            for name in parts:
                mode, fn = steps[name]
                if mode == "off":
                    continue
                try:
                    fn(res, dry_run)
                except SyncError as exc:
                    res.errors.append(f"{name}: {exc}")
                    log.warning("sync %s failed: %s", name, exc)
                except OSError as exc:
                    res.errors.append(f"{name}: {exc}")
                    log.warning("sync %s failed: %s", name, exc)
        if not dry_run and any(steps[n][0] != "off" for n in parts):
            write_sync_status(sync_status_path(self.data_dir), res)
        return res

    # -- cards ---------------------------------------------------------------------------
    def _cards(self, res: SyncResult, dry_run: bool) -> None:
        mode, remote_path = self.s.cards, self._cards_remote()
        info = self.rclone.stat(remote_path)
        local_exists = self.cards_path.exists()
        local = load_cards(self.cards_path) if local_exists else {}
        base_file = self._dir / "cards.base.toml"
        base = load_cards(base_file) if base_file.exists() else {}
        remote: dict[str, Card] = {}
        if info is not None:
            tmp = self._dir / "cards.remote.toml"
            self._dir.mkdir(parents=True, exist_ok=True)
            self.rclone.check("copyto", remote_path, str(tmp))
            remote = load_cards(tmp)
        if mode == "pull":
            merged, conflicts = (remote, []) if info is not None else (local, [])
        elif mode == "push":
            merged, conflicts = local, []
        else:
            merged, conflicts = merge_cards(base, local, remote)
        if conflicts:
            res.messages.append(f"cards changed on both sides (cloud version kept): {', '.join(conflicts)}")
        to_local = not same_cards(merged, local)
        to_remote = mode in ("both", "push") and (info is None or not same_cards(merged, remote)) and (merged or info)
        if dry_run:
            res.messages.append(f"cards: {len(merged)} in total, {'update the box' if to_local else 'box unchanged'}, "
                                f"{'update the cloud' if to_remote else 'cloud unchanged'}")
            return
        if to_local:
            if local_exists:
                shutil.copy2(self.cards_path, self.cards_path.with_name(self.cards_path.name + ".sync.bak"))
            _write_atomic(self.cards_path, "# managed by jukebox (comments are not kept)\n\n"
                          + render_cards(merged.values()))
            res.cards_changed = True
            res.messages.append("cards: box updated from the cloud")
        if to_remote:
            up = self._dir / "cards.upload.toml"
            _write_atomic(up, render_cards(merged.values()))
            self.rclone.check("copyto", str(up), remote_path)
            res.messages.append("cards: cloud updated from the box")
        _write_atomic(base_file, render_cards(merged.values()))

    # -- config folder ---------------------------------------------------------------------
    def _config(self, res: SyncResult, dry_run: bool) -> None:
        remote = self._box()
        watched = [self.config_dir / n for n in RESTART_FILES]
        before = [_sha(p) for p in watched]
        args = ["copy", remote, str(self.config_dir), "--update"]
        for pattern in KEEP_LOCAL:
            args += ["--exclude", pattern]
        if dry_run:
            args.append("--dry-run")
        self.rclone.check(*args)
        if not dry_run and before != [_sha(p) for p in watched]:
            res.config_changed = True
            res.messages.append("config: updated from the cloud; restart the jukebox to use it")

    # -- music -------------------------------------------------------------------------------
    def _music(self, res: SyncResult, dry_run: bool) -> None:
        remote = join_remote(self.s.remote, "music")
        if self.s.delete:
            if self.rclone.stat(remote) is None:        # a missing cloud folder must never empty the box
                raise SyncError(f"{remote} does not exist; nothing deleted")
            args = ["sync", remote, str(self.music_root), "--max-delete", "100"]
        else:
            args = ["copy", remote, str(self.music_root)]
        args += ["--transfers", "2", "--checkers", "4"]
        if dry_run:
            args.append("--dry-run")
        self.rclone.check(*args, bandwidth=True)
        res.messages.append("music: " + ("checked (dry run)" if dry_run else "up to date"))


class SyncThread(threading.Thread):
    """Runs the synchronisation in the background: shortly after start, then every interval, and soon after
    the cards were changed in the web interface."""

    def __init__(self, syncer: Syncer, bus, interval_s: float | None = None, first_delay: float | None = None,
                 settle: float = 10.0) -> None:
        super().__init__(name="sync", daemon=True)
        self.syncer, self.bus, self.settle = syncer, bus, settle
        self.interval = interval_s if interval_s is not None else syncer.s.interval_minutes * 60
        self.first = first_delay if first_delay is not None else syncer.s.first_run_delay
        self._wake, self._halt = threading.Event(), threading.Event()
        bus.subscribe(ev.CARDS_SAVED, lambda _e: self.trigger())

    def trigger(self) -> None:
        self._wake.set()

    def run(self) -> None:
        wait = self.first
        while not self._halt.is_set():
            woke = self._wake.wait(wait)
            if self._halt.is_set():
                return
            if woke:                                       # let several quick edits settle
                self._wake.clear()
                time.sleep(self.settle)
            parts = ("cards",) if woke else ("cards", "config", "music")
            res = self.syncer.run_once(parts)
            for m in res.messages:
                log.info("sync: %s", m)
            if res.cards_changed:
                self.bus.post(ev.CARDS_CHANGED)
            if res.errors:
                self.bus.post(ev.ERROR, message="sync: " + "; ".join(res.errors))
            wait = self.interval

    def stop(self) -> None:
        self._halt.set()
        self._wake.set()
