"""Cover art for local files.

Order: a picture in the folder (cover.jpg, folder.png, ...), then a copy saved earlier, then, if enabled, a
search on Spotify by album and artist (the album picture is saved as cover.jpg in the folder, or in the data
folder when the folder is not writable). Nothing found means no cover. Standard library only.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

NAMES = ("cover", "folder", "front", "albumart", "album", "artwork")      # by convention, in this order
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
SEARCH_URL = "https://api.spotify.com/v1/search"
NEGATIVE_DAYS = 30                                # how long "Spotify does not know this album" is remembered
MATCH_ALBUM = 0.8
MATCH_ARTIST = 0.7


class SearchError(Exception):
    """The search could not be done (offline, no session, HTTP error). Not remembered, retried later."""


def find_cover_file(folder: Path) -> Path | None:
    try:
        entries = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        return None
    for stem in NAMES:
        for ext in EXTENSIONS:
            hit = entries.get(stem + ext)
            if hit:
                return hit
    return None


def _norm(text: str) -> str:
    text = re.sub(r"[\(\[].*?[\)\]]", " ", text.casefold())
    text = re.sub(r"\b(deluxe|remaster(ed)?|edition|expanded|bonus)\b", " ", text)
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def best_album(items: list[dict], album: str, artist: str) -> str | None:
    """Image URL of the best matching album in a Spotify search result, or None when nothing matches well."""
    best_score, best_url = 0.0, None
    for item in items:
        images = item.get("images") or []
        if not images:
            continue
        score = _similar(item.get("name", ""), album)
        if score < MATCH_ALBUM:
            continue
        if artist:
            names = [a.get("name", "") for a in item.get("artists", [])]
            if not any(_similar(n, artist) >= MATCH_ARTIST or _norm(artist) in _norm(n) for n in names):
                continue
        if score > best_score:
            best_score, best_url = score, images[0].get("url")      # Spotify lists the largest first
    return best_url


def http_get(url: str, headers: dict | None = None, timeout: float = 6.0, limit: int = 8_000_000) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:       # noqa: S310 (https URLs only, see callers)
            data = resp.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SearchError(str(exc)) from exc
    if len(data) > limit:
        raise SearchError("response too large")
    return data


class SpotifySearch:
    """Looks up an album on Spotify with the token of the go-librespot session (POST /token), so no
    developer account of your own is needed. Not run against the real service yet."""

    def __init__(self, token_call: Callable[[], str | None], get: Callable = http_get) -> None:
        self._token, self._get = token_call, get

    def find(self, album: str, artist: str = "") -> str | None:
        try:
            token = self._token()
        except Exception as exc:                      # go-librespot not reachable
            raise SearchError(f"no token: {exc}") from exc
        if not token:
            raise SearchError("no Spotify session (go-librespot is not logged in)")
        q = f"album:{album}" + (f" artist:{artist}" if artist else "")
        url = SEARCH_URL + "?" + urllib.parse.urlencode({"q": q, "type": "album", "limit": 10})
        try:
            data = json.loads(self._get(url, {"Authorization": f"Bearer {token}"}))
        except ValueError as exc:
            raise SearchError(f"unreadable answer: {exc}") from exc
        return best_album((data.get("albums") or {}).get("items") or [], album, artist)


class CoverResolver:
    def __init__(self, data_dir: Path, search=None, download: Callable = http_get,
                 write_to_folder: bool = True, now: Callable[[], float] = time.time) -> None:
        self._dir = data_dir / "covers"
        self._state = data_dir / "covers.json"
        self._search, self._download, self._write_folder, self._now = search, download, write_to_folder, now

    # -- what is already there (cheap, no network) ---------------------------------
    def lookup(self, folder: Path) -> str | None:
        hit = find_cover_file(folder)
        if hit:
            return str(hit)
        cached = self._cache_path(folder)
        return str(cached) if cached.exists() else None

    def _cache_path(self, folder: Path) -> Path:
        return self._dir / (hashlib.sha1(str(folder).encode()).hexdigest()[:16] + ".jpg")

    def _known_missing(self, folder: Path) -> bool:
        try:
            stamp = json.loads(self._state.read_text()).get(str(folder))
        except (OSError, ValueError):
            return False
        return bool(stamp) and self._now() - stamp < NEGATIVE_DAYS * 86400

    def _remember_missing(self, folder: Path) -> None:
        try:
            state = json.loads(self._state.read_text())
        except (OSError, ValueError):
            state = {}
        state[str(folder)] = self._now()
        try:
            self._state.parent.mkdir(parents=True, exist_ok=True)
            self._state.write_text(json.dumps(state))
        except OSError:
            log.warning("could not write %s", self._state)

    # -- Spotify (network) -----------------------------------------------------------
    def fetch(self, folder: Path, album: str, artist: str = "") -> str | None:
        if self._search is None or not album or self._known_missing(folder):
            return None
        try:
            url = self._search.find(album, artist)
            if url is None:
                self._remember_missing(folder)
                return None
            if not url.startswith("https://"):
                raise SearchError("unexpected cover URL")
            data = self._download(url)
        except SearchError as exc:
            log.info("no cover for %s: %s", folder, exc)
            return None
        if not (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
            log.info("cover for %s is not a picture", folder)
            return None
        return self._save(folder, data)

    def _save(self, folder: Path, data: bytes) -> str | None:
        suffix = ".png" if data.startswith(b"\x89PNG") else ".jpg"
        if self._write_folder and os.access(folder, os.W_OK):
            target = folder / ("cover" + suffix)
            try:
                target.write_bytes(data)
                return str(target)
            except OSError:
                pass
        target = self._cache_path(folder)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            log.warning("could not save cover: %s", exc)
            return None
        return str(target)
