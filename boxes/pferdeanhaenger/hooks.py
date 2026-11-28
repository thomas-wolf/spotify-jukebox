"""hooks.py of Marie's horse trailer: the white back button (GPIO 16) plays a random horse sound, the red LED
button (pin 3, GPIO 2) plays the engine sound motor.mp3. In both cases the music pauses and goes on afterwards,
if it was playing.

The chord blue + yellow + green (next, pause, previous) held together for 2 s runs `sudo jukebox-deploy` (action
`deploy`, see [deploy] in config.toml and the sudoers line in the comment there).

Copy next to config.toml as hooks.py. Put mp3/ogg/wav files in the folder from [pferdesound]. motor.mp3 comes
from the configuration folder (~/.config/jukebox/, synced from Dropbox boxes/pferdeanhaenger/) or from [motor] file.
"""
import logging
import random
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)
EXT = {".mp3", ".ogg", ".wav", ".flac", ".m4a"}


def setup(app):
    cfg = app.cfg.section("pferdesound")
    folder = Path(str(cfg.get("folder", "~/sounds/pferd"))).expanduser()
    command = cfg.get("command", ["mpv", "--no-video", "--really-quiet"])
    pause_playback = cfg.get("pause_playback", True)   # pause before, resume after (only if it was playing)
    state = {"proc": None}

    def pferdesound():
        files = [f for f in folder.glob("*") if f.suffix.lower() in EXT] if folder.is_dir() else []
        if not files:
            log.warning("pferdesound: no sound files in %s", folder)
            return
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            return  # still neighing
        was_playing = bool(pause_playback and app.players.is_playing())
        if was_playing:
            app.do_action("pause")   # not "stop": that unloads a local playlist and resume would find nothing
        proc = subprocess.Popen([*command, str(random.choice(files))], stdin=subprocess.DEVNULL)
        state["proc"] = proc
        if was_playing:
            threading.Thread(target=lambda: (proc.wait(), app.do_action("resume")), daemon=True,
                             name="pferd-resume").start()

    app.actions["pferdesound"] = pferdesound

    # --- red LED button: engine sound --------------------------------------------------------------------------
    motor_cfg = app.cfg.section("motor")
    motor_pause = motor_cfg.get("pause_playback", True)  # pause before, resume after (only if it was playing)
    motor_command = motor_cfg.get("command", command)
    motor_state = {"proc": None}

    def motor_file():
        named = motor_cfg.get("file")
        if named:
            return Path(str(named)).expanduser()
        cfg_path = getattr(app.cfg, "path", None)
        base = Path(cfg_path).parent if cfg_path else Path.home() / ".config" / "jukebox"
        for ext in ("mp3", "ogg", "wav", "flac", "m4a"):
            if (base / f"motor.{ext}").is_file():
                return base / f"motor.{ext}"
        return base / "motor.mp3"

    def motor():
        path = motor_file()
        if not path.is_file():
            log.warning("motor: sound file %s not found", path)
            return
        proc = motor_state["proc"]
        if proc is not None and proc.poll() is None:
            return  # engine still running
        was_playing = bool(motor_pause and app.players.is_playing())
        if was_playing:
            app.do_action("pause")   # not "stop": that unloads a local playlist and resume would find nothing
        proc = subprocess.Popen([*motor_command, str(path)], stdin=subprocess.DEVNULL)
        motor_state["proc"] = proc

        def after():
            proc.wait()
            if was_playing:
                app.do_action("resume")

        threading.Thread(target=after, daemon=True, name="motor-resume").start()

    app.actions["motor"] = motor

    # --- three top buttons held together: install the newest build from GitHub -------------------------------------
    deploy_cfg = app.cfg.section("deploy")
    deploy_state = {"proc": None}

    def deploy():
        proc = deploy_state["proc"]
        if proc is not None and proc.poll() is None:
            return  # already running
        command = deploy_cfg.get("command", ["sudo", "-n", "/usr/local/sbin/jukebox-deploy"])
        ref = deploy_cfg.get("ref", "develop")
        log_path = Path.home() / "deploy.log"
        log.warning("deploy: started %s %s (output in %s); the service restarts at the end", command, ref, log_path)
        display = getattr(app, "display", None)
        if display is not None:       # the new build is shown after the restart (jukebox.version)
            from jukebox.version import installed_build
            display.show_track(f"Update {installed_build() or '?'} \u2192 {ref}", "", None)
        try:
            out = open(log_path, "ab")
            # own session: the script finishes with `systemctl restart jukebox`, which ends this process
            deploy_state["proc"] = subprocess.Popen([*command, ref], stdin=subprocess.DEVNULL, stdout=out,
                                                    stderr=subprocess.STDOUT, start_new_session=True)
        except OSError:
            log.exception("deploy: could not start %s", command)

    app.actions["deploy"] = deploy
