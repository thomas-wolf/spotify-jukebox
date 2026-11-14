# Umzug von Phoniebox v2

Diese Seite beschreibt, wie du bestehende Karten und Einstellungen aus der v2-Spotify-Edition übernimmst.
Ein Import-Werkzeug gibt es noch nicht. Die Umstellung ist Handarbeit, aber überschaubar.

## Alte Dienste abschalten

Läuft auf der Box noch v2, kollidieren die alten Dienste mit der neuen Jukebox (Audio-Gerät, serielle
Schnittstelle, GPIO-Pins, Port 6680/6600). Schalte sie vorher ab:

```
sudo systemctl disable --now mopidy mpd lighttpd phoniebox-rfid-reader \
  phoniebox-gpio-control phoniebox-startup-scripts phoniebox-idle-watchdog 2>&1 | cat
```

Nicht vorhandene Dienste meldet systemd als Fehler. Das ist unkritisch. Welche Dienste bei dir wirklich laufen,
zeigt `systemctl list-units 'phoniebox*' mopidy* mpd*`. Am saubersten ist eine frische SD-Karte.

## Karten-IDs

Damit deine Karten ohne Neuanlernen weiterfunktionieren, liefert die neue Jukebox dieselben IDs wie v2:

| Reader | v2 | Neu |
|---|---|---|
| RDM6300 | Standard: roh, 12 Zeichen mit Prüfsumme (`070067315809`) | `id_format = "raw"` (Standard) |
| RDM6300 | `numberformat = card_id_dec` | `id_format = "dec"` |
| RDM6300 | `numberformat = card_id_float` | `id_format = "float"` |
| USB | Ziffern und Buchstaben, Buchstaben klein | gleich (Buchstaben klein) |

Zwei Randfälle:

- Der alte USB-Code übersetzte Tasten über eine Tabelle für deutsche Tastaturen, bei der **y und z vertauscht**
  sind. Karten-IDs mit y oder z (bei Hex-IDs unüblich) heißen jetzt anders.
- Die Jukebox vergleicht IDs ohne Beachtung der Groß-/Kleinschreibung.

## Karten und Ordner

v2 speichert eine Karte in zwei Teilen (Pfade relativ zur v2-Installation, die Wurzel steht in
`settings/Audio_Folders_Path`):

1. `shared/shortcuts/<Karten-ID>` ist eine Datei, deren Inhalt der Ordnername ist.
2. `shared/audiofolders/<Ordnername>/` enthält entweder Audiodateien oder eine Textdatei mit der Quelle:
   `spotify.txt`, `podcast.txt`, `livestream.txt` oder `url.txt`.

Daraus wird in `cards.toml`:

| v2 | Neu |
|---|---|
| Ordner enthält `spotify.txt` mit `spotify:playlist:ID` | `play = "spotify:playlist:ID"` (derselbe Inhalt der Datei, v2 nutzte das Mopidy-Format) |
| Ordner mit Audiodateien | `play = "folder:<Ordnername>"`, die Dateien nach `[local] root` kopieren |
| `podcast.txt`, `livestream.txt`, `url.txt` | **nicht unterstützt** |

Beispiel: Die Datei `shared/shortcuts/0123456789` enthält `Gute-Nacht`, und
`shared/audiofolders/Gute-Nacht/spotify.txt` enthält `spotify:playlist:37i9dQZF1DX0UrRvztWcAU`. Dann:

```toml
[cards."0123456789"]
name = "Gute-Nacht"
play = "spotify:playlist:37i9dQZF1DX0UrRvztWcAU"
```

Die Datei-Inhalte liest du mit `cat` oder einer kleinen Schleife aus, etwa:

```
cd ~/RPi-Jukebox-RFID/shared/shortcuts
for id in *; do printf '%s -> %s\n' "$id" "$(cat "$id")"; done
cat ../audiofolders/Gute-Nacht/spotify.txt
```

Der Pfad `~/RPi-Jukebox-RFID` ist der Standard von v2 und kann bei dir abweichen.

Die Wiederaufnahme-Position lokaler Ordner wird nicht übernommen, sie beginnt neu.

## Steuerkarten

v2 legt Steuerkarten in `settings/rfid_trigger_play.conf` ab, als Zeilen wie `CMDVOLUP="0123456789"`.
Diese Zuordnung gilt in der neuen Jukebox:

| v2-Variable | Neue Aktion |
|---|---|
| `CMDVOLUP`, `CMDVOLDOWN` | `volume_up`, `volume_down` |
| `CMDVOL30` … `CMDVOL100` | `volume_set` mit `args = { value = 30 }` usw. |
| `CMDMUTE` | `mute` |
| `CMDNEXT`, `CMDPREV` | `next`, `prev` |
| `CMDPAUSE` | `play_pause` (in v2 schaltete diese Karte um, sie pausierte nicht nur) |
| `CMDPLAY` | `resume` |
| `CMDSTOP` | `stop` |
| `CMDSEEKFORW`, `CMDSEEKBACK` | `seek_forward`, `seek_back` (v2: 15 Sekunden, hier ebenfalls 15) |
| `CMDSHUTDOWN` | `shutdown` |

Beispiel für eine „Lautstärke 50 %"-Karte:

```toml
[cards."0123456790"]
action = "volume_set"
args = { value = 50 }
```

**Noch nicht vorhanden** (die Karten werden als unbekannt gemeldet): Zufallswiedergabe (`CMDSHUFFLE`,
`CMDRANDCARD`, `CMDRANDFOLD`, `CMDRANDTRACK`), Neustart der Playlist (`CMDREWIND`), Höchstlautstärke-Karten
(`CMDMAXVOL…`), Stop-/Shutdown-Timer (`STOPAFTER…`, `SHUTDOWNAFTER…`), Reboot, WLAN-, Bluetooth- und
Audio-Interface-Umschaltung, Aufnahme, Synchronisation.

## GPIO-Einstellungen

`settings/gpio_settings.ini` wird nicht gelesen. Die Entsprechung steht in der `config.toml`:

| v2 | Neu |
|---|---|
| `Type: Button`, `functionCall: functionCallPlayerNext` | `[[gpio.button]]`, `action = "next"` |
| `functionCallVolU` / `functionCallVolD` | `volume_up` / `volume_down` |
| `functionCallPlayerPause` | `play_pause` (in v2 schaltet das um) |
| `functionCallPlayerPauseForce` | `pause` |
| `functionCallPlayerPrev` / `functionCallPlayerNext` | `prev` / `next` |
| `functionCallVol0` | `mute` |
| `functionCallPlayerStop` | `stop` |
| `functionCallPlayerSeekFwd` / `SeekBack` | `seek_forward` / `seek_back`. v2 sprang hier 10 Sekunden (`SeekFarFwd`/`FarBack`: 60), setze `args = { seconds = 10 }`, sonst gilt 15. |
| `functionCallShutdown` | `shutdown` |
| `hold_mode: Repeat` | `repeat = true` |
| `hold_mode: SecondFunc` mit `functionCall2` | `hold_action` (und `hold_time`) |
| `Type: RotaryEncoder` | `[[gpio.rotary]]` mit `cw`/`ccw` |
| `Type: ShutdownButton` | `[[gpio.button]]` mit `hold_action = "shutdown"` |
| `Type: TwoButtonControl` | zwei einzelne Taster (der Doppeldruck-Effekt entfällt) |
| `Type: StatusLED` | eine `[[gpio.led]]` plus Hook, siehe [HOOKS.md](HOOKS.md) |

Vergleiche die Pins mit der Tabelle in [HARDWARE.md](HARDWARE.md). Mit I2C (Poti) ist GPIO 3 als Taster
nicht mehr nutzbar.

## Was bewusst nicht dabei ist

Die neue Jukebox ist eine Spotify- und Lokal-Box, kein Ersatz für das ganze v2-Paket. Nicht enthalten sind:
Weboberfläche, Podcasts, Livestreams und YouTube-Downloads, Samba-Freigabe, WLAN-Hotspot, Bluetooth-Sink-Umschaltung,
automatisches Ausschalten bei Inaktivität (Idle-Watchdog), Aufnahme, Synchronisation, RFID-Reader RC522 und PN532 sowie
die Anzeigen HD44780 und MAX7219. Einiges davon ließe sich als eigener Baustein ergänzen, siehe
[DEVELOPMENT.md](DEVELOPMENT.md).
