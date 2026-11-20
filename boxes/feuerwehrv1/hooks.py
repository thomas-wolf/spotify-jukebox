"""hooks.py of the fire engine (v1): siren with flashing lights, and a switch to mute the siren.

Ported from the old Phoniebox script (gpio.py, `def_alarm` and `def_mute_alarm`).

- Action `sirene` (red button): pauses the music (it goes on at the same spot afterwards), plays the siren sound, runs the light show (blue left/right
  alternate, the yellow lights flash in the first half of every round), then resumes the music if it was playing (a live stream is dropped by the player and reloaded).
  The yellow front lights are on while idle (`[siren] front_lights`, default true, plus `on = true` on the LED).
- Action `alarm_mute` (encoder push button, held 2 s): toggles "siren muted". While muted the red button does nothing.

The sound file is private and not in the repository: put `martinshorn.mp3` into `~/.config/jukebox/` (or set
`[siren] sound` in config.toml). With cloud sync it can live in `<remote>/boxes/feuerwehrv1/martinshorn.mp3`.
The yellow front lights are on while idle (`[siren] front_lights`, default true; the config also has `on = true` on
that LED) and come back on after the siren. The LED class can only switch on and off, so the blue lights are dark when idle (the old script held them at half
brightness with PWM).
"""
import logging
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


def setup(app):
    cfg = app.cfg.section("siren")
    sound = Path(str(cfg.get("sound", "~/.config/jukebox/martinshorn.mp3"))).expanduser()
    command = cfg.get("command", ["mpv", "--no-video", "--really-quiet"])
    rounds = int(cfg.get("rounds", 7))        # old script: 7 rounds of one second
    step = float(cfg.get("step", 0.25))       # seconds per light phase, 4 phases per round
    front_on = bool(cfg.get("front_lights", True))   # yellow lights stay on when idle
    state = {"muted": False, "busy": False}
    lock = threading.Lock()

    blue_l, blue_r, yellow = (app.leds.get(n) for n in ("blue_left", "blue_right", "yellow"))
    if yellow is not None and front_on:
        yellow.set(True)      # also when the LED has no `on = true` in the config

    def set_leds(bl, br, y):
        for led, on in ((blue_l, bl), (blue_r, br), (yellow, y)):
            if led is not None:
                led.set(bool(on))

    def run_siren(was_playing):
        proc = None
        try:
            if sound.is_file():
                proc = subprocess.Popen([*command, str(sound)])
            else:
                log.warning("sirene: sound file %s not found, lights only", sound)
            for _ in range(rounds):
                set_leds(1, 0, 1); time.sleep(step)
                set_leds(0, 1, 1); time.sleep(step)
                set_leds(1, 0, 0); time.sleep(step)
                set_leds(0, 1, 0); time.sleep(step)
            if proc is not None:
                try:
                    proc.wait(timeout=60)     # let the siren finish before the music comes back
                except subprocess.TimeoutExpired:
                    proc.terminate()
        except Exception:
            log.exception("sirene failed")
        finally:
            set_leds(0, 0, front_on)
            if was_playing:
                app.do_action("resume")
            with lock:
                state["busy"] = False

    def sirene():
        if state["muted"]:
            log.info("sirene: muted, ignored")
            return
        with lock:
            if state["busy"]:
                return
            state["busy"] = True
        was_playing = bool(app.players.is_playing())
        if was_playing:
            app.do_action("pause")     # not "stop": that unloads the local playlist and resume would find nothing
        threading.Thread(target=run_siren, args=(was_playing,), daemon=True).start()

    def alarm_mute():
        state["muted"] = not state["muted"]
        log.info("sirene: %s", "muted" if state["muted"] else "active again")

    app.actions["sirene"] = sirene
    app.actions["alarm_mute"] = alarm_mute
