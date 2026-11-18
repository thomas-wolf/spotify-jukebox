# Events, sounds and hooks

Everything that differs from box to box (startup sound, LED animations, custom reactions) belongs in
`config.toml` and an optional `hooks.py`, not in the code.

## Events

The jukebox reports what happens as events. Hooks and sounds listen to them.

| Event | When | Data |
|---|---|---|
| `boot` | The box has started | |
| `card` | A card was presented | `id` |
| `card_unknown` | The card is not in `cards.toml` | `id` |
| `action` | An action was triggered (button, encoder, potentiometer) | `name`, `args` |
| `playing` | Playback is running | `target` and `name` when started by a card, otherwise often empty |
| `paused` | Playback paused | `target`, may be missing |
| `stopped` | Playback stopped | |
| `volume` | Volume changed | `value` (0 to `max_volume`) |
| `track` | Track info (for the display) | `title`, `artist`, `cover_url`. **Not sent yet**, see below |
| `shutdown` | The box is shutting down | |
| `error` | A player reports an error | `message` |

`*` subscribes to all events. Always read data that may be missing with `event.data.get("name")`.

The playback events describe what the jukebox **requested**. If go-librespot finishes a track on its own or
someone plays through the Spotify app, they do not report it. That would require hooking up go-librespot's
WebSocket events (`/events`: `playing`, `paused`, `metadata`, `volume`, ...). That is not implemented yet.

## Startup sounds and event sounds

No code needed, directly in `config.toml`:

```toml
[sounds]
command = ["mpv", "--no-video", "--really-quiet"]     # optional, this is the default

[sounds.events]
boot = "~/sounds/startup.mp3"
card = "~/sounds/blip.mp3"
card_unknown = "~/sounds/error.mp3"
shutdown = "~/sounds/shutdown.mp3"
```

Relative paths are taken relative to the real `config.toml` (a link is followed), so a box folder in the repository can carry its own `sounds/`. **Convention:** without an entry, `startup.mp3` (boot) and `shutdown.mp3` (shutdown) in the configuration folder `~/.config/jukebox/` are played (also `.ogg`, `.wav`, `.flac`, `.m4a`). That folder is never part of the repository. An entry in `[sounds.events]` takes precedence. Each box has its own files. If a file is missing there is a warning in the log.
The sound is started in the background and blocks nothing.

## hooks.py

A Python file next to `config.toml`:

```toml
[hooks]
file = "hooks.py"
```

It must have a function `setup(app)`. In it you subscribe to events:

```python
def setup(app):
    def on_unknown(event):
        print("New card:", event.data["id"])

    app.bus.subscribe("card_unknown", on_unknown)
```

What you can reach through `app`:

| Access | Meaning |
|---|---|
| `app.bus.subscribe(name, fn)` | React to an event (`"*"` for all) |
| `app.bus.post(name, **data)` | Raise your own event, also for other hooks |
| `app.leds["status"]` | An LED from `[[gpio.led]]` with `.on()`, `.off()`, `.set(bool)` |
| `app.do_action(name, **args)` | Trigger an action, e.g. `app.do_action("next")` |
| `app.players.volume`, `.is_playing()`, `.current_target` | Read state |
| `app.cfg.section("box")` | Read configuration, including your own sections |

**Important:** handlers run in the box's main loop. A handler that waits (`time.sleep`, long loops) holds up
cards and buttons. Animations belong in a thread of their own, as in the example below.
A hook that raises an error is logged and skipped. It cannot stop playback.
`app.leds` is empty when no GPIO is configured. Check for that in the hook (`app.leds.get("status")`).

### Example: LED blinks while music is playing

See `examples/hooks.py`:

```python
import threading, time

def setup(app):
    led = app.leds.get("status")
    if led is None:
        return
    stop = threading.Event()
    state = {"thread": None}

    def blink():
        while not stop.is_set():
            led.on();  time.sleep(0.5)
            led.off(); time.sleep(0.5)

    def on_playing(_event):
        if state["thread"] is None or not state["thread"].is_alive():
            stop.clear()
            state["thread"] = threading.Thread(target=blink, daemon=True)
            state["thread"].start()

    def on_idle(_event):
        stop.set()
        led.off()

    app.bus.subscribe("playing", on_playing)
    app.bus.subscribe("paused", on_idle)
    app.bus.subscribe("stopped", on_idle)
```

`hooks.py` is the right place for more elaborate animations (pulsing by PWM, several LEDs). The LED class can
only do on and off so far. You have to build soft transitions yourself by switching quickly.

### Custom actions

If a button or card needs an action that does not exist, define it in `hooks.py`:

```python
def setup(app):
    app.actions["night_mode"] = lambda: app.set_volume(10)
```

and put `action = "night_mode"` in `config.toml`. `app.actions` is the table from which buttons, encoders
and cards pick their action.
