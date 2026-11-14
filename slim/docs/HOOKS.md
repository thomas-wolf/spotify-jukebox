# Ereignisse, Sounds und Hooks

Alles, was sich von Box zu Box unterscheidet (Startsound, LED-Animationen, eigene Reaktionen), gehört
in die `config.toml` und in eine optionale `hooks.py`, nicht in den Code.

## Ereignisse

Die Jukebox meldet ihr Geschehen als Ereignisse. Hooks und Sounds hören darauf.

| Ereignis | Wann | Daten |
|---|---|---|
| `boot` | Die Box ist gestartet | |
| `card` | Eine Karte wurde aufgelegt | `id` |
| `card_unknown` | Die Karte steht nicht in `cards.toml` | `id` |
| `action` | Eine Aktion wurde ausgelöst (Taste, Encoder, Poti) | `name`, `args` |
| `playing` | Wiedergabe läuft | `target` und `name` beim Start per Karte, sonst oft leer |
| `paused` | Wiedergabe pausiert | `target`, kann fehlen |
| `stopped` | Wiedergabe gestoppt | |
| `volume` | Lautstärke geändert | `value` (0 bis `max_volume`) |
| `track` | Titelinfos (für das Display) | `title`, `artist`, `cover_url`. **Wird noch nicht gesendet**, siehe unten |
| `shutdown` | Die Box fährt herunter | |
| `error` | Ein Player meldet einen Fehler | `message` |

`*` abonniert alle Ereignisse. Zugriff auf fehlende Daten immer mit `event.data.get("name")`.

Die Wiedergabe-Ereignisse beschreiben, was die Jukebox **angefordert** hat. Beendet go-librespot einen Titel
von selbst oder spielt jemand über die Spotify-App, melden sie das nicht. Dafür müssten die WebSocket-Ereignisse
von go-librespot angebunden werden (`/events`: `playing`, `paused`, `metadata`, `volume`, …). Das ist
noch nicht umgesetzt.

## Startsounds und Ereignis-Sounds

Ohne Code, direkt in der `config.toml`:

```toml
[sounds]
command = ["mpv", "--no-video", "--really-quiet"]     # optional, ist der Standard

[sounds.events]
boot = "~/sounds/startup.mp3"
card = "~/sounds/blip.mp3"
card_unknown = "~/sounds/error.mp3"
shutdown = "~/sounds/shutdown.mp3"
```

Jede Box hat ihre eigenen Dateien. Fehlt eine Datei, steht eine Warnung im Log.
Der Sound wird im Hintergrund gestartet und blockiert nichts.

## hooks.py

Eine Python-Datei neben der `config.toml`:

```toml
[hooks]
file = "hooks.py"
```

Sie muss eine Funktion `setup(app)` haben. Darin abonnierst du Ereignisse:

```python
def setup(app):
    def on_unknown(event):
        print("Neue Karte:", event.data["id"])

    app.bus.subscribe("card_unknown", on_unknown)
```

Was du über `app` erreichst:

| Zugriff | Bedeutung |
|---|---|
| `app.bus.subscribe(name, fn)` | Auf ein Ereignis reagieren (`"*"` für alle) |
| `app.bus.post(name, **daten)` | Ein eigenes Ereignis auslösen, auch für andere Hooks |
| `app.leds["status"]` | Eine LED aus `[[gpio.led]]` mit `.on()`, `.off()`, `.set(bool)` |
| `app.do_action(name, **args)` | Eine Aktion auslösen, z. B. `app.do_action("next")` |
| `app.players.volume`, `.is_playing()`, `.current_target` | Zustand lesen |
| `app.cfg.section("box")` | Konfiguration lesen, auch eigene Abschnitte |

**Wichtig:** Handler laufen im Hauptablauf der Box. Ein Handler, der wartet (`time.sleep`, lange
Schleifen), hält Karten und Tasten an. Animationen gehören in einen eigenen Thread, wie im Beispiel unten.
Ein Hook, der einen Fehler wirft, wird protokolliert und übersprungen. Er kann die Wiedergabe nicht anhalten.
`app.leds` ist leer, wenn kein GPIO konfiguriert ist. Prüfe das im Hook (`app.leds.get("status")`).

### Beispiel: LED blinkt, solange Musik läuft

Siehe `examples/hooks.py`:

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

Für aufwendigere Animationen (Pulsieren per PWM, mehrere LEDs) ist `hooks.py` der richtige Ort. Die LED-Klasse
kann bisher nur an und aus. Weiche Übergänge musst du per schnellem Umschalten selbst bauen.

### Eigene Aktionen

Braucht eine Taste oder Karte eine Aktion, die es nicht gibt, lege sie in `hooks.py` an:

```python
def setup(app):
    app.actions["nachtmodus"] = lambda: app.set_volume(10)
```

und in der `config.toml` `action = "nachtmodus"`. `app.actions` ist die Tabelle, aus der Tasten, Encoder
und Karten ihre Aktion auswählen.
