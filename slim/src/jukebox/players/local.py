"""Local audio folders, played by mpv over its JSON IPC socket (stdlib only)."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from .base import Player, PlayerError

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b",
                    ".aac", ".wav", ".wma", ".aiff", ".ac3"}


class Mpv(Protocol):
    def command(self, *args: Any) -> Any: ...
    def close(self) -> None: ...


class MpvClient:
    """Starts mpv in idle mode and talks JSON IPC to it."""

    def __init__(self, binary: str = "mpv", volume: int = 30) -> None:
        self._dir = tempfile.mkdtemp(prefix="jukebox-mpv-")
        self._sock_path = os.path.join(self._dir, "ipc.sock")
        try:
            self._proc = subprocess.Popen(
                [binary, "--idle=yes", "--no-video", "--no-terminal", "--really-quiet",
                 f"--volume={volume}", f"--input-ipc-server={self._sock_path}"],
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise PlayerError(f"{binary!r} not found; install mpv") from None
        self._lock = threading.Lock()
        self._req = 0
        self._sock = self._connect()
        self._buf = b""

    def _connect(self) -> socket.socket:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise PlayerError("mpv exited during start-up")
            try:
                s = socket.socket(socket.AF_UNIX)
                s.settimeout(5)
                s.connect(self._sock_path)
                return s
            except OSError:
                time.sleep(0.05)
        raise PlayerError("mpv IPC socket did not appear")

    def command(self, *args: Any) -> Any:
        with self._lock:
            self._req += 1
            rid = self._req
            self._sock.sendall(json.dumps({"command": list(args), "request_id": rid}).encode() + b"\n")
            while True:
                while b"\n" not in self._buf:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        raise PlayerError("mpv closed the IPC socket")
                    self._buf += chunk
                line, self._buf = self._buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("request_id") == rid:
                    if msg.get("error") != "success":
                        raise PlayerError(f"mpv {args[0]}: {msg.get('error')}")
                    return msg.get("data")

    def close(self) -> None:
        try:
            self._sock.close()
        finally:
            self._proc.terminate()


def natural_key(path: Path) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(path))]


class LocalPlayer(Player):
    name = "local"

    def __init__(self, mpv: Mpv, root: Path, state_file: Path) -> None:
        self._mpv = mpv
        self._root = root.resolve()
        self._state_file = state_file
        self._current: str | None = None
        self._playing = False

    # -- resume state ------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self._state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save_position(self) -> None:
        if not self._current:
            return
        try:
            index = self._mpv.command("get_property", "playlist-pos")
            seconds = self._mpv.command("get_property", "time-pos")
        except PlayerError:
            return
        if index is None or index < 0:
            return
        state = self._load_state()
        state[self._current] = {"index": index, "time": seconds or 0}
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(state))

    # -- Player API --------------------------------------------------------
    def resolve(self, target: str) -> list[Path]:
        kind, _, rel = target.partition(":")
        if kind not in ("folder", "file") or not rel:
            raise PlayerError(f"not a local target: {target!r}")
        path = (self._root / rel).resolve()
        if not path.is_relative_to(self._root):
            raise PlayerError(f"{target!r} points outside {self._root}")
        if kind == "file":
            if not path.is_file():
                raise PlayerError(f"no such file: {path}")
            return [path]
        if not path.is_dir():
            raise PlayerError(f"no such folder: {path}")
        files = sorted((p for p in path.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS),
                       key=natural_key)
        if not files:
            raise PlayerError(f"no audio files in {path}")
        return files

    def play(self, target: str) -> None:
        files = self.resolve(target)
        self._save_position()
        self._mpv.command("loadfile", str(files[0]), "replace")
        for f in files[1:]:
            self._mpv.command("loadfile", str(f), "append")
        saved = self._load_state().get(target)
        if saved and saved["index"] < len(files):
            self._mpv.command("set_property", "playlist-pos", saved["index"])
            self._mpv.command("seek", saved["time"], "absolute")
        self._mpv.command("set_property", "pause", False)
        self._current = target
        self._playing = True

    def pause(self) -> None:
        self._mpv.command("set_property", "pause", True)
        self._save_position()
        self._playing = False

    def resume(self) -> None:
        self._mpv.command("set_property", "pause", False)
        self._playing = True

    def stop(self) -> None:
        self._save_position()
        self._mpv.command("stop")
        self._playing = False

    def next(self) -> None:
        self._mpv.command("playlist-next", "weak")

    def prev(self) -> None:
        self._mpv.command("playlist-prev", "weak")

    def seek(self, seconds: float) -> None:
        self._mpv.command("seek", seconds, "relative")

    def set_volume(self, volume: int) -> None:
        self._mpv.command("set_property", "volume", max(0, min(100, volume)))

    def is_playing(self) -> bool:
        return self._playing

    def close(self) -> None:
        self._save_position()
        self._mpv.close()
