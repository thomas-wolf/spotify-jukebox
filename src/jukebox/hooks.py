"""Per-box customisation: event sounds and a user hook file.

A box can ship a ``hooks.py`` next to its config.toml. It must define
``setup(app)`` and may use ``app.bus.subscribe(event_name, handler)`` to run
its own code, e.g. LED animations:

    def setup(app):
        def on_play(event):
            ...  # start your animation thread here
        app.bus.subscribe("playing", on_play)

A hook that raises is logged and skipped; it can never stop playback.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .app import App
from .config import expand
from .events import Event

log = logging.getLogger(__name__)


# By convention a box plays these files from its configuration folder (~/.config/jukebox), which is never in git:
# startup.mp3 at boot, shutdown.mp3 when shutting down. An entry in [sounds.events] takes precedence.
SOUND_CONVENTION = {"boot": "startup", "shutdown": "shutdown"}
SOUND_EXTENSIONS = ("mp3", "ogg", "wav", "flac", "m4a")


def conventional_sounds(local_dir: Path | None, configured: dict) -> dict[str, str]:
    found: dict[str, str] = {}
    if local_dir is None:
        return found
    for event_name, stem in SOUND_CONVENTION.items():
        if event_name in configured:
            continue
        for ext in SOUND_EXTENSIONS:
            candidate = local_dir / f"{stem}.{ext}"
            if candidate.is_file():
                found[event_name] = str(candidate)
                break
    return found


def pipewire_socket() -> Path | None:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / "pipewire-0" if runtime else None


def install_sounds(app: App, popen: Callable[..., Any] = subprocess.Popen) -> None:
    """Play a file for an event: [sounds.events] boot = "/path/start.mp3".

    The sound processes are kept in ``app.sound_procs`` so that a shutdown can wait for its own sound. A sound
    that is due before PipeWire is up (the box has just booted) waits for its socket, at most ``audio_wait`` s,
    in a helper thread so the main loop is not held up."""
    sounds = app.cfg.section("sounds")
    command = list(sounds["command"])
    audio_wait = float(sounds.get("audio_wait", 20.0))
    cfg_path = getattr(app.cfg, "path", None)
    base = cfg_path.resolve().parent if cfg_path else Path.cwd()  # next to the real file, also when linked
    events = dict(sounds.get("events", {}))
    events.update(conventional_sounds(cfg_path.parent if cfg_path else None, events))

    def launch(cmd: list[str]) -> None:
        app.sound_procs[:] = [p for p in app.sound_procs if getattr(p, "poll", lambda: 0)() is None]
        proc = popen(cmd, stdin=subprocess.DEVNULL)
        if proc is not None:
            app.sound_procs.append(proc)

    def play_when_audio_is_up(cmd: list[str], sock: Path) -> None:
        deadline = time.monotonic() + audio_wait
        while not sock.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        if not sock.exists():
            log.warning("sound: PipeWire socket %s did not appear within %.0f s, playing anyway", sock, audio_wait)
        launch(cmd)

    for event_name, file in events.items():
        path = expand(file)
        if not path.is_absolute():
            path = base / path  # relative paths: next to config.toml

        def play(_event: Event, path: Path = path) -> None:
            if not path.is_file():
                log.warning("sound file missing: %s", path)
                return
            cmd = command + [str(path)]
            sock = pipewire_socket()
            if sock is None or sock.exists() or audio_wait <= 0:
                launch(cmd)
            else:
                threading.Thread(target=play_when_audio_is_up, args=(cmd, sock), daemon=True,
                                 name="sound-wait").start()

        app.bus.subscribe(event_name, play)


def load_user_hooks(app: App, file: str | Path) -> None:
    path = expand(file)
    if not path.is_file():
        log.warning("hooks file not found: %s", path)
        return
    spec = importlib.util.spec_from_file_location("jukebox_user_hooks", path)
    if spec is None or spec.loader is None:
        log.error("cannot load hooks from %s", path)
        return
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.setup(app)
    except Exception:
        log.exception("hooks file %s failed to load", path)
