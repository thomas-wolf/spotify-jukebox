"""Loading of config.toml (hardware, per box) and cards.toml (card -> action)."""

from __future__ import annotations

import os
import pwd
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "box": {"name": "jukebox", "data_dir": "~/.local/share/jukebox"},
    "audio": {"start_volume": 30, "max_volume": 80, "volume_step": 5},
    "cards": {
        # What happens when the same card is presented again:
        # toggle (pause/resume), ignore, restart, next
        "same_card": "restart",
        "same_card_delay": 3.0,
    },
    "spotify": {
        "enabled": True,
        "backend": "go-librespot",               # or "soloist" (Spotify's own client, see docs/CONFIG.md)
        "api_url": "http://127.0.0.1:3678",      # go-librespot
        "soloist_ws": "127.0.0.1:9090",          # Soloist's WebSocket API
    },
    "local": {"enabled": True, "root": "~/music", "mpv": "mpv"},
    "sounds": {"command": ["mpv", "--no-video", "--really-quiet"]},
    "display": {"enabled": False},
    # Cover art for local files (needs [display] enabled): picture in the folder, else search on Spotify
    "covers": {"spotify_search": True, "write_to_folder": True},
    "sync": {"enabled": False},
    "web": {"enabled": False, "host": "0.0.0.0", "port": 8080},
    # Status to Home Assistant over MQTT (needs the "mqtt" extra: paho-mqtt)
    "mqtt": {"enabled": False, "host": "127.0.0.1", "port": 1883, "username": "", "password": "",
             "discovery_prefix": "homeassistant", "topic_prefix": "jukebox", "interval": 60.0},
    "system": {"shutdown_command": ["systemctl", "poweroff"]},
}


class ConfigError(ValueError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def expand(path: str | Path) -> Path:
    """Like expanduser, but under ``sudo`` a leading ``~`` means the invoking user's home, not root's."""
    text = str(path)
    if text == "~" or text.startswith("~/"):
        user = os.environ.get("SUDO_USER")
        if user and os.geteuid() == 0:
            try:
                return Path(pwd.getpwnam(user).pw_dir + text[1:])
            except KeyError:
                pass
    return Path(path).expanduser()


@dataclass
class Config:
    raw: dict[str, Any]
    path: Path | None = None

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        if not isinstance(value, dict):
            raise ConfigError(f"[{name}] must be a table")
        return value

    @property
    def data_dir(self) -> Path:
        return expand(self.section("box")["data_dir"])

    def hardware_list(self, *keys: str) -> list[dict[str, Any]]:
        node: Any = self.raw
        for key in keys:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        return node if isinstance(node, list) else []


def load_config(path: str | Path | None = None) -> Config:
    raw: dict[str, Any] = {}
    p = expand(path) if path else None
    if p is not None:
        try:
            with open(p, "rb") as fh:
                raw = tomllib.load(fh)
        except FileNotFoundError:
            raise ConfigError(f"config file not found: {p}") from None
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{p}: {exc}") from exc
    if p is not None:
        local = p.with_name("config.local.toml")  # per-device overrides, not in git, next to the (linked) config
        if local.is_file():
            try:
                with open(local, "rb") as fh:
                    raw = _merge(raw, tomllib.load(fh))
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{local}: {exc}") from exc
    cfg = Config(_merge(DEFAULTS, raw), p)
    audio = cfg.section("audio")
    for key in ("start_volume", "max_volume", "volume_step"):
        if not isinstance(audio[key], int) or not 0 <= audio[key] <= 100:
            raise ConfigError(f"[audio] {key} must be an integer 0..100")
    if cfg.section("spotify")["backend"] not in ("go-librespot", "soloist"):
        raise ConfigError("[spotify] backend must be go-librespot or soloist")
    if cfg.section("cards")["same_card"] not in ("toggle", "ignore", "restart", "next"):
        raise ConfigError("[cards] same_card must be toggle, ignore, restart or next")
    return cfg


@dataclass
class Card:
    id: str
    name: str = ""
    play: str | None = None      # spotify:... | folder:relative/path | file:path
    action: str | None = None    # volume_up, next, shutdown, ...
    args: dict[str, Any] = field(default_factory=dict)


def load_cards(path: str | Path) -> dict[str, Card]:
    p = expand(path)
    if not p.exists():
        return {}
    try:
        with open(p, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{p}: {exc}") from exc
    cards: dict[str, Card] = {}
    for card_id, entry in raw.get("cards", {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"{p}: card {card_id!r} must be a table")
        play, action = entry.get("play"), entry.get("action")
        if bool(play) == bool(action):
            raise ConfigError(f"{p}: card {card_id!r} needs exactly one of play/action")
        cards[str(card_id)] = Card(
            id=str(card_id),
            name=entry.get("name", ""),
            play=play,
            action=action,
            args=entry.get("args", {}),
        )
    return cards


def add_card(path: str | Path, card_id: str, *, name: str = "",
             play: str | None = None, action: str | None = None) -> None:
    """Append a card entry to cards.toml (no TOML writer needed for this shape)."""
    if bool(play) == bool(action):
        raise ConfigError("give exactly one of play/action")
    p = expand(path)
    if card_id in load_cards(p):
        raise ConfigError(f"card {card_id} already exists")
    p.parent.mkdir(parents=True, exist_ok=True)
    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    lines = [f"\n[cards.{q(card_id)}]"]
    if name:
        lines.append(f"name = {q(name)}")
    lines.append(f"play = {q(play)}" if play else f"action = {q(action or '')}")
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return _q(str(v))


def render_cards(cards) -> str:
    """cards.toml text for objects with id, name, play, action, args."""
    out: list[str] = []
    for c in cards:
        out.append(f"[cards.{_q(c.id)}]")
        if c.name:
            out.append(f"name = {_q(c.name)}")
        out.append(f"play = {_q(c.play)}" if c.play else f"action = {_q(c.action or '')}")
        if c.args:
            out.append("args = { " + ", ".join(f"{k} = {_val(v)}" for k, v in c.args.items()) + " }")
        out.append("")
    return "\n".join(out)


def save_cards(path: str | Path, cards) -> None:
    """Rewrite cards.toml atomically. Comments are lost; the first rewrite keeps a .jukebox.bak copy."""
    p = expand(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.with_name(p.name + ".jukebox.bak")
        if not bak.exists():
            bak.write_bytes(p.read_bytes())
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("# managed by jukebox (comments are not kept)\n\n" + render_cards(cards), encoding="utf-8")
    tmp.replace(p)
