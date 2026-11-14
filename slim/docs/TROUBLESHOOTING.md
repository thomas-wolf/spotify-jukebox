# Fehlersuche

Zuerst die Logs ansehen:

```
journalctl -u jukebox -f          # die Jukebox
journalctl -u go-librespot -f     # Spotify-Daemon
/opt/jukebox/venv/bin/jukebox -v run     # im Vordergrund mit Debug-Meldungen (Dienst vorher stoppen)
```

## Kein Ton

1. Gibt es die Soundkarte? `aplay -l` muss `sndrpihifiberry` zeigen. Wenn nicht, steht das Overlay nicht in der
   `config.txt` oder es wurde nicht neu gestartet: `grep -n hifiberry /boot/firmware/config.txt`
   (bei älterem System `/boot/config.txt`).
2. Läuft das Onboard-Audio noch? `dtparam=audio=on` muss ausgeschaltet sein. `jukebox setup` kommentiert die
   Zeile aus.
3. Funktioniert die Karte generell? `speaker-test -t sine -f 440 -l 1`.
4. Ist die Lautstärke 0 oder stumm? Das Log zeigt `volume`-Ereignisse. `start_volume` in der `config.toml`.
5. Lokale Dateien gehen nicht? `mpv --no-video /pfad/datei.mp3` direkt ausprobieren.
6. Spotify spielt in der App, aber nicht auf der Box? Prüfe `audio_device` in der go-librespot-Konfiguration
   (`aplay -L` listet die Namen).

## Karte wird nicht erkannt

- Im Log steht `unknown card <ID>`: Die Karte ist nicht angelegt. ID kopieren und
  `jukebox cards add <ID> --play ...`. Danach den Dienst neu starten, denn `cards.toml` wird beim Start gelesen.
- Die ID sieht anders aus als in v2: bei RDM6300 `id_format` prüfen (Standard `raw`).
- Gar keine Meldung beim Auflegen: siehe „Reader findet nichts".

## Reader findet nichts

**USB:** Der Dienstbenutzer muss in der Gruppe `input` sein (`groups`). `device_name` muss in
einem Gerätenamen vorkommen (Befehl in [HARDWARE.md](HARDWARE.md)). Im Log steht alle fünf Sekunden
`USB reader ... not found`, solange er fehlt. Andere Programme, die den Reader ebenfalls greifen (der alte
Phoniebox-Dienst), blockieren ihn.

**RDM6300:** Ist die serielle Schnittstelle freigeschaltet (Login-Shell aus, Hardware an)? `ls -l /dev/serial0`.
Der Benutzer braucht die Gruppe `dialout`. `sudo cat /dev/serial0` muss beim Auflegen einer Karte Zeichen
zeigen. Passiert nichts, prüfe Verkabelung (TX des Readers an RX des Pi) und Spannung.

## Spotify

**`jukebox spotify-check` meldet `FAILED: go-librespot not reachable`:**
`systemctl status go-librespot` prüfen, in der go-librespot-Konfiguration muss `server.enabled: true` stehen.
`server.port` und `[spotify] api_url` müssen übereinstimmen.

**Der Daemon läuft, aber die Karte startet nichts:** Im Log der Jukebox steht dann etwas wie
`go-librespot POST /player/play: HTTP 404`. Die Endpunkte in `src/jukebox/players/spotify.py` (`ENDPOINTS`)
sind meine Annahme und nicht aus der Spezifikation von go-librespot geprüft. Vergleiche sie mit der Datei
`api-spec.yml` im go-librespot-Repository und passe die Tabelle an. Auch die Feldnamen der Anfragen (`uri`,
`volume`, `position`) stammen aus derselben Annahme.

**Anmeldefehler (`INVALID_CREDENTIALS`, `login5`):** Ein Bericht vom August 2026 beschreibt, dass go-librespot
0.7.1 unter Volumio mit dieser Meldung abbrach, wenn die Anmeldung per Token erfolgte, im reinen Zeroconf-Modus
aber lief. Im Mopidy-Forum meldeten Nutzer denselben Fehler mit dem Spotify-Plugin. Dieser Fehler gehört also
zur Familie der Anmeldeprobleme der librespot-Projekte, nicht zu dieser Jukebox. Was hilft:

1. go-librespot auf die neueste Version aktualisieren.
2. Neu anmelden: den Dienst stoppen, die gespeicherten Zugangsdaten im go-librespot-Konfigurationsordner
   entfernen (welche Datei, steht im README von go-librespot **(nicht geprüft)**), starten und den Code-Login
   auf spotify.com/pair wiederholen.
3. Nur zur Diagnose `credentials.type: zeroconf` ausprobieren und die Box aus der Spotify-App heraus wählen.

**Spielt nicht, obwohl die Anmeldung stimmt:** Spotify Premium wird vorausgesetzt.

## GPIO und Tasten

- `ModuleNotFoundError: gpiod` oder `AttributeError: ... request_lines`: Es ist `python3-libgpiod` 1.x installiert
  oder das venv sieht die apt-Pakete nicht. Prüfe `python3 -c "import gpiod; print(gpiod.request_lines)"`. Auf
  Bookworm gibt es 2.x nur über `bookworm-backports`. Das venv braucht `--system-site-packages`.
- `Permission denied`: Benutzer in die Gruppe `gpio`, danach neu anmelden bzw. den Dienst neu starten.
- `Device or resource busy`: Der Pin wird schon benutzt, etwa von einem noch laufenden alten Phoniebox-Dienst oder
  einem Overlay. `gpioinfo` zeigt die Besitzer der Leitungen.
- Taste löst mehrfach aus oder gar nicht: `pull` prüfen. Taster gegen Masse brauchen `pull = "up"`.
- Encoder zählt rückwärts: `cw` und `ccw` tauschen.
- Das Log meldet `unknown action`: Tippfehler im Namen. Die Namen stehen in [CONFIG.md](CONFIG.md).

## Poti

- `/dev/i2c-1` fehlt: I2C ist nicht aktiv. `[boot] i2c = true`, `jukebox setup --apply`, neu starten. Das Modul
  `i2c-dev` kommt aus `/etc/modules-load.d/jukebox.conf`.
- `i2cdetect -y 1` zeigt `48` nicht: Verkabelung und ADDR-Pin prüfen.
- Lautstärke erreicht 100 % nicht oder zu früh: `jukebox adc-check` und `full_scale` anpassen.
- Die Lautstärke springt nach dem Start nicht auf die Potistellung. Das ist Absicht, erst eine Bewegung
  zählt.

## Herunterfahren geht nicht

Der Dienst darf `systemctl poweroff` oft nicht ausführen. Lege die sudo-Regel an und stelle
`shutdown_command` um (siehe [INSTALL.md](INSTALL.md) Schritt 7).

## Die `config.txt` zurücksetzen

Beim ersten `jukebox setup --apply` entsteht `config.txt.jukebox.bak` neben der `config.txt`. Zurück:

```
sudo cp /boot/firmware/config.txt.jukebox.bak /boot/firmware/config.txt
```

(bei älterem System unter `/boot/`). Die Datei `/etc/modules-load.d/jukebox.conf` kannst du einfach löschen.

## Fehler melden

Gib bei einem Problem diese Angaben mit: Raspberry-Pi-Modell, `cat /etc/os-release`, `uname -m`, Auszüge aus
`journalctl -u jukebox` und `journalctl -u go-librespot`, deine `config.toml` ohne persönliche Daten.
