# Konfiguration

Die Box liest zwei Dateien aus demselben Ordner (Standard `~/.config/jukebox/`):

- `config.toml`: Hardware und Verhalten, **pro Box verschieden**
- `cards.toml`: Karte → Aktion, wird beim Start gelesen (nach Änderungen Dienst neu starten)

Andere Pfade: `jukebox -c /pfad/zu/config.toml ...`. `cards.toml` liegt immer neben der `config.toml`.
Fehlt ein Schlüssel, gilt der Standardwert aus den Tabellen unten. Ungültige Werte (etwa eine
Lautstärke über 100) lehnt der Start mit einer Fehlermeldung ab.

Eine kommentierte Vorlage liegt in `examples/config.toml`.

## config.toml

### `[box]`

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `name` | `jukebox` | Name der Box, nur für Logmeldungen |
| `data_dir` | `~/.local/share/jukebox` | Ablage für den Wiederaufnahme-Stand lokaler Ordner (`resume.json`) |

### `[audio]`

Alle Werte sind ganze Zahlen von 0 bis 100. Die Lautstärke wird in der Software geregelt (der MiniAmp hat
keinen Hardware-Mixer).

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `start_volume` | `30` | Lautstärke beim Start der Box |
| `max_volume` | `80` | Harte Obergrenze. Gilt für Tasten, Encoder, Karten und das Poti. |
| `volume_step` | `5` | Schrittweite für `volume_up` und `volume_down` |

### `[cards]`

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `same_card` | `toggle` | Was passiert, wenn die laufende Karte erneut aufgelegt wird: `toggle` (Pause/Weiter), `ignore`, `restart` (von vorn), `next` (nächster Titel) |
| `same_card_delay` | `3.0` | Sekunden, in denen dieselbe Karte als Dopplung des Readers gilt und ignoriert wird |

### `[spotify]`

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `enabled` | `true` | Spotify-Wiedergabe ein oder aus |
| `api_url` | `http://127.0.0.1:3678` | Adresse der REST-API von go-librespot (`server.port` dort) |

### `[local]`

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `enabled` | `true` | Lokale Ordner ein oder aus. Findet sich `mpv` nicht, wird dieser Teil abgeschaltet und die Box läuft mit Spotify weiter. |
| `root` | `~/music` | Wurzelordner. Ziele wie `folder:hoerbuecher/x` beziehen sich darauf. |
| `mpv` | `mpv` | Programmname oder Pfad von mpv |

Ordner werden rekursiv gelesen und natürlich sortiert (`2.mp3` vor `10.mp3`). Erkannte Endungen:
mp3, flac, ogg, oga, opus, m4a, m4b, aac, wav, wma, aiff, ac3. Pfade außerhalb von `root` werden abgelehnt.

### `[readers.usb]`

Tastatur-Emulation, wie bei den meisten USB-Readern. Braucht `python3-evdev`.

| Schlüssel | Bedeutung |
|---|---|
| `enabled` | `true` zum Aktivieren |
| `device_name` | Teil des Gerätenamens (ohne Groß-/Kleinschreibung). Namen listet `python3 -c "import evdev; [print(evdev.InputDevice(p).name) for p in evdev.list_devices()]"`. |

Der Reader wird exklusiv gegriffen, die Ziffern landen also nicht in einer Konsole. Buchstaben in
Karten-IDs werden kleingeschrieben (wie in v2).

### `[readers.rdm6300]`

125-kHz-Reader an der seriellen Schnittstelle (9600 Baud).

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `enabled` | `false` | `true` zum Aktivieren |
| `port` | `/dev/serial0` | Serielle Schnittstelle |
| `id_format` | `raw` | Aussehen der Karten-ID, siehe unten |

Formate (für denselben Chip):

| `id_format` | Beispiel | Hinweis |
|---|---|---|
| `raw` | `070067315809` | 12 Zeichen mit Prüfsumme, **wie Phoniebox v2 standardmäßig** |
| `dec` | `0006762840` | 10 Ziffern, wie v2 `card_id_dec` |
| `float` | `103,12632` | wie v2 `card_id_float`, entspricht der aufgedruckten Nummer |
| `hex` | `0700673158` | die 10 Zeichen des Chips ohne Prüfsumme (neu) |

Eine Karte wird einmal pro Auflegen gemeldet. Nimmst du sie ab (eine Sekunde ohne Signal) und legst sie
wieder auf, zählt das als neues Auflegen.

### `[gpio]`

GPIO-Nummern sind BCM-Nummern (nicht die Pin-Nummern auf der Leiste). Braucht `python3-libgpiod` 2.x.

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `enabled` | `true` | Auf `false` setzen, um GPIO ganz abzuschalten, ohne die Einträge zu löschen |
| `chip` | `/dev/gpiochip0` | GPIO-Chip. Ältere Kernel auf dem Pi 5 verwenden einen anderen (ungeprüft), `gpiodetect` zeigt sie. |

**Taster: `[[gpio.button]]`** (beliebig oft)

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `pin` | | BCM-Nummer |
| `pull` | `up` | `up`: Taster gegen Masse, Pull-up intern. `down`: Taster gegen 3,3 V |
| `action` | | Aktion bei kurzem Druck (Liste unten) |
| `args` | `{}` | Argumente der Aktion, z. B. `args = { seconds = 30 }` |
| `hold_action` | | Aktion bei langem Halten. Dann löst `action` erst beim Loslassen aus, wenn nicht gehalten wurde. |
| `hold_time` | `1.0` | Sekunden bis `hold_action` auslöst |
| `repeat` | `false` | Aktion wiederholt sich, solange gehalten wird (sinnvoll für Lautstärke) |

**Drehencoder: `[[gpio.rotary]]`**

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `pin_a`, `pin_b` | | BCM-Nummern der beiden Kanäle |
| `pull` | `up` | Pull für beide Pins |
| `cw`, `ccw` | | Aktion pro Raste im Uhrzeigersinn bzw. dagegen |
| `cw_args`, `ccw_args` | `{}` | Argumente |

Eine Raste entspricht vier gültigen Übergängen. Prellen auf nur einem Kanal löst nichts aus. Dreht der
Encoder bei dir falsch herum, tausche `cw` und `ccw`.

**LED: `[[gpio.led]]`**

| Schlüssel | Bedeutung |
|---|---|
| `name` | Name, unter dem die LED in einer `hooks.py` als `app.leds["name"]` erreichbar ist |
| `pin` | BCM-Nummer. LEDs werden vom Kern nicht selbst gesteuert, nur über Hooks. |

### `[adc]`: Lautstärke-Poti am ADS1115

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `enabled` | `false` | `true` zum Aktivieren (setzt `[boot] i2c = true` voraus) |
| `bus` | `1` | I2C-Bus (`/dev/i2c-1`) |
| `address` | `0x48` | I2C-Adresse des ADS1115 |
| `channel` | `0` | Eingang A0 bis A3 |
| `full_scale` | `26400` | Rohwert am oberen Anschlag des Potis |

Der Startwert des Potis ändert die Lautstärke beim Start nicht, erst eine Bewegung um mindestens zwei
Prozent. `full_scale` stimmst du mit `jukebox adc-check` ab: Poti an beide Enden drehen und den Rohwert am
oberen Ende eintragen. Der Standardwert gilt für ein an 3,3 V angeschlossenes Poti im Bereich ±4,096 V.

### `[sounds]`

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `command` | `["mpv", "--no-video", "--really-quiet"]` | Programm zum Abspielen von Ereignis-Sounds. Der Dateiname wird angehängt. |

**`[sounds.events]`** ordnet Ereignissen Dateien zu:

```toml
[sounds.events]
boot = "~/sounds/startup.mp3"
shutdown = "~/sounds/shutdown.mp3"
card_unknown = "~/sounds/error.mp3"
```

Gültige Ereignisnamen stehen in [HOOKS.md](HOOKS.md). Fehlt die Datei, steht eine Warnung im Log,
sonst passiert nichts.

### `[system]`

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `shutdown_command` | `["systemctl", "poweroff"]` | Befehl der Aktion `shutdown`. Siehe [INSTALL.md](INSTALL.md) für die sudo-Variante. |

### `[hooks]`

| Schlüssel | Bedeutung |
|---|---|
| `file` | Python-Datei mit eigenem Code für diese Box, relativ zur `config.toml`. Siehe [HOOKS.md](HOOKS.md). |

### `[boot]`: Overlays

Wird nur von `jukebox setup` gelesen, nicht im Betrieb.

| Schlüssel | Bedeutung |
|---|---|
| `audio` | Audio-Profil: `hifiberry-miniamp`, `hifiberry-dac` (beide `dtoverlay=hifiberry-dac`) oder `pirate-audio` (zusätzlich `gpio=25=op,dh`, wie im v2-Skript). Alle schalten `dtparam=audio=on` aus. |
| `spi` | `true` schreibt `dtparam=spi=on` (für das Display) |
| `i2c` | `true` schreibt `dtparam=i2c_arm=on` (für den ADS1115) |
| `extra` | Weitere Zeilen. Entweder Text oder `{ model = "pi5", line = "..." }` für Zeilen, die nur bei einem Pi-Modell gelten (config.txt-Filter `[pi5]`) |

Details und Hintergrund in [HARDWARE.md](HARDWARE.md).

## cards.toml

```toml
[cards."0123456789"]
name = "Gute Nacht"                      # optional, nur zur Übersicht
play = "spotify:playlist:37i9dQZF1DX0UrRvztWcAU"

[cards."0123456790"]
play = "folder:hoerbuecher/pumuckl"

[cards."0123456791"]
action = "seek_forward"
args = { seconds = 30 }
```

Je Karte genau eines von `play` oder `action`. Die ID wird ohne Beachtung der Groß-/Kleinschreibung verglichen.
Anlegen auch per Befehl: `jukebox cards add ID --play ... | --action ... [--name ...]`.

**Ziele (`play`)**

| Form | Bedeutung |
|---|---|
| `spotify:playlist:ID`, `spotify:album:ID`, `spotify:track:ID`, ... | Spotify-URI |
| `folder:relativer/pfad` | Ordner unter `[local] root`, rekursiv, wird mit Wiederaufnahme gespielt |
| `file:relativer/pfad.mp3` | Einzelne Datei unter `root` |

Beim Wechsel zwischen Spotify und lokal wird der jeweils andere Player angehalten. Die Lautstärke gilt für beide.

**Aktionen (`action`, auch bei Tasten, Encodern und Hooks)**

| Aktion | Argumente | Bedeutung |
|---|---|---|
| `play_pause` | | Pause/Weiter umschalten |
| `pause`, `resume`, `stop` | | Entsprechend. Bei Spotify hält `stop` nur an. |
| `next`, `prev` | | Nächster/vorheriger Titel |
| `seek_forward`, `seek_back` | `seconds` (15) | Vor- oder zurückspulen |
| `volume_up`, `volume_down` | | Um `volume_step` ändern |
| `volume_set` | `value` | Lautstärke setzen (wird auf `max_volume` begrenzt) |
| `mute` | | Stumm schalten und zurück zur vorigen Lautstärke |
| `shutdown` | | Box herunterfahren (`[system] shutdown_command`) |

Unbekannte Aktionen und falsche Argumente werden im Log gemeldet und stören den Betrieb nicht.
Fehler des Players (z. B. go-librespot nicht erreichbar) werden ebenfalls geloggt und lösen das Ereignis `error` aus.
