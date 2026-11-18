"""hooks.py of Marie's horse trailer: the back button plays a random horse sound.

Copy next to config.toml as hooks.py. Put mp3/ogg/wav files in the folder from [pferdesound].
"""
import logging
import random
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)
EXT = {".mp3", ".ogg", ".wav", ".flac", ".m4a"}


def setup(app):
    cfg = app.cfg.section("pferdesound")
    folder = Path(str(cfg.get("folder", "~/sounds/pferd"))).expanduser()
    command = cfg.get("command", ["mpv", "--no-video", "--really-quiet"])
    stop_playback = cfg.get("stop_playback", True)   # v2 stopped the music before the sound
    state = {"proc": None}

    def pferdesound():
        files = [f for f in folder.glob("*") if f.suffix.lower() in EXT] if folder.is_dir() else []
        if not files:
            log.warning("pferdesound: no sound files in %s", folder)
            return
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            return  # still neighing
        if stop_playback:
            app.do_action("stop")
        state["proc"] = subprocess.Popen([*command, str(random.choice(files))])

    app.actions["pferdesound"] = pferdesound
