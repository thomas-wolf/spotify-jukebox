# Entwicklung

## Aufbau

```
 Reader (Thread)  ─┐
 GPIO (Thread)    ─┼─►  EventBus (Warteschlange)  ─►  App.handle  ─►  PlayerRouter ─┬─► SpotifyPlayer ─► go-librespot (HTTP localhost)
 Poti (Thread)    ─┘            │                                                   └─► LocalPlayer   ─► mpv (JSON-IPC-Socket)
                                └─► Beobachter: Sounds, hooks.py, Display
```

- Eingaben laufen in eigenen Threads und tun genau eines: `bus.post("card", id=...)` bzw. `bus.post("action", ...)`.
- Der Hauptablauf (`EventBus.run`) holt Ereignisse nacheinander ab, lässt zuerst den Kern (`App.handle`) arbeiten und gibt
  das Ereignis danach an die Beobachter weiter. Die Player-Logik läuft also nur in einem Thread und braucht keine Sperren.
- Fehler in einem Beobachter oder im Kern werden protokolliert und beenden nichts.

```
src/jukebox/
  cli.py          Befehle (run, setup, cards, spotify-check, adc-check) und Verdrahtung
  app.py          Karten und Aktionen, Lautstärkelogik
  config.py       config.toml und cards.toml
  events.py       EventBus
  hooks.py        Ereignis-Sounds und hooks.py
  boot.py         config.txt-Pflege (Overlays)
  players/        base (Schnittstelle), router, spotify, local
  inputs/         usb_reader, rdm6300, gpio, adc
  display/        Schnittstelle, noch kein Treiber
tests/            pytest, ohne Hardware
packaging/        systemd-Units, go-librespot-Vorlage
examples/         config.toml, cards.toml, hooks.py
```

## Tests

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Die Tests brauchen keine Hardware, kein mpv und kein go-librespot. `tests/fakes.py` enthält Attrappen für Player,
mpv und Uhr. Getestet sind Konfiguration, Kartenlogik, Lautstärke, die Auswahl und das Wechseln der Player, die
Auflösung lokaler Pfade (auch Schutz gegen `..`), Wiederaufnahme, Taster- und Encoder-Logik, das Zerlegen von
RDM6300-Rahmen, die `config.txt`-Pflege und Hooks.

**Nicht** getestet, weil Hardware oder Programme nötig sind: `GpiodBackend`, `MpvClient`, `Ads1115`, der
evdev-Reader, das Öffnen der seriellen Schnittstelle und das echte HTTP gegen go-librespot. Das sind die
dünnen Schichten, die zuerst auf einer echten Box ausprobiert werden müssen.

## Einen neuen Reader ergänzen (z. B. RC522, PN532)

1. Neue Datei in `src/jukebox/inputs/`. Eine `threading.Thread`-Unterklasse mit `stop()` und `run()`.
   Nicht `_stop` als Attributnamen verwenden, das gehört `Thread` selbst.
2. Beim Lesen einer Karte `self.bus.post("card", id=<ID als Text>)`. Die ID sollte stabil und mit
   Groß-/Kleinschreibung unempfindlich vergleichbar sein.
3. Die reine Auswertung (Rahmen zerlegen, Prüfsumme) in eine eigene Funktion legen und ohne Hardware testen,
   wie `parse_frame` bei RDM6300.
4. In `cli.start_inputs` einen Abschnitt `[readers.<name>]` auswerten.

## Einen neuen Player ergänzen

1. Die Klasse `Player` aus `players/base.py` implementieren (`play`, `pause`, `resume`, `stop`, `next`,
   `prev`, `seek`, `set_volume`, `is_playing`). Fehler als `PlayerError` melden.
2. In `cli.build` unter einem Schema registrieren (`backends["radio"] = ...`). Ziele wie `radio:...` gehen dann
   automatisch an den Player. Der Router hält jeweils nur einen Player am Laufen.
3. Mit `FakePlayer` aus `tests/fakes.py` als Vorbild testen.

## Offene Arbeit

| Thema | Stand |
|---|---|
| go-librespot-Endpunkte gegen `api-spec.yml` prüfen, Latenz Karte → Ton messen | wichtigster nächster Schritt, braucht eine echte Box |
| Cover und Titel aus go-librespot (WebSocket `/events`) in das Ereignis `track` | offen, sonst bleibt das Display leer |
| ILI9341-Treiber über SPI (`spidev`, Pillow) | offen, braucht Auflösung, Drehung, DC-/RESET-Pins |
| Import der v2-Karten (`shared/shortcuts`, `spotify.txt`, `rfid_trigger_play.conf`) | möglich, siehe [MIGRATION.md](MIGRATION.md) |
| `cards.toml` ohne Neustart nachladen | offen |
| Reader RC522 und PN532 | offen |
| Idle-Shutdown (Ausschalten bei Inaktivität) | offen, ein Hook-Kandidat |
| Hardware-Test von `GpiodBackend`, `MpvClient`, `Ads1115`, evdev, UART | offen |

## Stil

- Nur die Standardbibliothek im Kern. Neue Abhängigkeiten nur für Hardware und als optionale Importe, damit
  eine Box ohne sie startet.
- Parser, Zustandsautomaten und Konfigurationslogik als reine Funktionen schreiben, damit sie ohne Hardware testbar sind.
- Fehler einer Hardware- oder Netzwerkschicht werden zu `PlayerError` oder Logmeldungen, nie zu einem Absturz der Box.
