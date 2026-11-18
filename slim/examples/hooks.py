"""Example per-box hooks: a status LED that breathes while music plays.

Enable with  [hooks] file = "hooks.py"  in config.toml.
"""

import threading
import time


def setup(app):
    led = app.leds.get("status")
    if led is None:
        return
    stop = threading.Event()

    def breathe():
        while not stop.is_set():
            led.on(); time.sleep(0.5)
            led.off(); time.sleep(0.5)

    state = {"thread": None}

    def on_playing(_event):
        if state["thread"] is None or not state["thread"].is_alive():
            stop.clear()
            state["thread"] = threading.Thread(target=breathe, daemon=True)
            state["thread"].start()

    def on_idle(_event):
        stop.set()
        led.off()

    app.bus.subscribe("playing", on_playing)
    app.bus.subscribe("paused", on_idle)
    app.bus.subscribe("stopped", on_idle)
