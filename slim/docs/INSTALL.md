# Installation

Diese Anleitung bringt einen leeren Raspberry Pi bis zur laufenden Box. Schritte, die ich nicht auf
echter Hardware ausprobiert habe, sind mit **(ungeprüft)** markiert.

## Voraussetzungen

- Raspberry Pi mit 40-Pin-Leiste und WLAN oder Ethernet.
- **Raspberry Pi OS auf Basis von Debian 13 „Trixie"** (Lite reicht). Grund: Der GPIO-Code nutzt die
  Python-Bindings von libgpiod 2. Trixie liefert `python3-libgpiod` in Version 2.2.1 aus, Bookworm
  nur 1.6.3 mit anderer API. Auf Bookworm gibt es 2.1.3 in `bookworm-backports`.
- Ein **Spotify-Premium-Konto**. Mit einem kostenlosen Konto funktioniert die Wiedergabe nicht.
- HiFiBerry MiniAmp (oder ein anderes DAC-Profil, siehe [HARDWARE.md](HARDWARE.md)).
- Ein Rechner mit SSH, um die Box einzurichten.

**Pi Zero (ARMv6):** Der MiniAmp ist für den Pi Zero gebaut. Ob go-librespot dafür fertige Binaries
anbietet, habe ich nicht geprüft **(ungeprüft)**. Sieh dazu auf der
[Release-Seite](https://github.com/devgianlu/go-librespot/releases/latest) nach. Bei `uname -m` =
`armv6l` musst du das Programm sonst selbst bauen.

## 1. System vorbereiten

Mit dem Raspberry Pi Imager Raspberry Pi OS Lite (Trixie) auf die SD-Karte schreiben. In den
Imager-Einstellungen Hostname, Benutzer, WLAN und SSH setzen. Die Anleitung geht vom Benutzer `pi`
aus. Heißt dein Benutzer anders, ersetze `pi` in den Befehlen und in den Dateien unter `packaging/`.

```
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv python3-libgpiod python3-evdev mpv alsa-utils git
```

`python3-evdev` brauchst du nur für USB-Reader. Den Paketnamen habe ich nicht geprüft **(ungeprüft)**;
findet apt ihn nicht, such mit `apt search evdev`.

## 2. Jukebox installieren

```
git clone -b rewrite/slim-core https://github.com/thomas-wolf/spotify-jukebox ~/spotify-jukebox
cd ~/spotify-jukebox/slim
sudo python3 -m venv --system-site-packages /opt/jukebox/venv
sudo /opt/jukebox/venv/bin/pip install .
```

`--system-site-packages` sorgt dafür, dass die per apt installierten Module `gpiod` und `evdev` im
venv sichtbar sind. Prüfen:

```
/opt/jukebox/venv/bin/jukebox --help
```

## 3. Konfiguration anlegen

```
mkdir -p ~/.config/jukebox ~/music
cp examples/config.toml examples/cards.toml ~/.config/jukebox/
nano ~/.config/jukebox/config.toml
```

Passe mindestens diese Bereiche an: den Reader (`[readers.usb]` oder `[readers.rdm6300]`, nicht
benutzte auf `enabled = false`), die `[[gpio.*]]`-Einträge (nicht vorhandene Hardware entfernen)
und `[boot]`. Alle Schlüssel erklärt [CONFIG.md](CONFIG.md).

Die Beispiel-Karten in `cards.toml` sind Platzhalter. Lösche sie oder ersetze sie später.

## 4. Overlays setzen und neu starten

`jukebox setup` zeigt zuerst nur, was es ändern würde:

```
/opt/jukebox/venv/bin/jukebox setup
```

Für den MiniAmp (`audio = "hifiberry-miniamp"`) sieht der Diff so aus: `dtparam=audio=on` wird
auskommentiert, und ein markierter Block mit `dtoverlay=hifiberry-dac` (plus `dtparam=spi=on`, wenn
`spi = true`) kommt hinzu. Das Overlay und das Abschalten des Onboard-Audios entsprechen der
Dokumentation von HiFiBerry. Übernehmen:

```
sudo /opt/jukebox/venv/bin/jukebox -c "$HOME/.config/jukebox/config.toml" setup --apply
sudo reboot
```

Das `-c` mit absolutem Pfad ist nötig, weil `~` unter `sudo` auf das Home von root zeigt. Vor der
ersten Änderung legt das Tool `config.txt.jukebox.bak` neben die Originaldatei. Zurücksetzen:
Backup zurückkopieren.

Nach dem Neustart muss der DAC als Soundkarte erscheinen:

```
aplay -l
```

Dort sollte eine Karte mit dem Namen `sndrpihifiberry` auftauchen. Ein kurzer Test:

```
speaker-test -t sine -f 440 -l 1
```

Kein Ton? Siehe [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## 5. go-librespot installieren

1. Auf der [Release-Seite](https://github.com/devgianlu/go-librespot/releases/latest) das
   Linux-Archiv für deine Architektur laden. `uname -m` sagt dir, welche: `aarch64` ist 64-bit ARM,
   `armv7l` 32-bit ARM, `armv6l` der Pi Zero. Die genauen Dateinamen kann ich nicht nennen
   **(ungeprüft)**.
2. Entpacken und das Programm nach `/usr/local/bin/` legen (`sudo install -m 755 ... /usr/local/bin/`).
   Heißt die Datei anders als `go-librespot`, passe `ExecStart` in
   `packaging/go-librespot.service` an.
3. Konfiguration anlegen:
   ```
   mkdir -p ~/.config/go-librespot
   cp ~/spotify-jukebox/slim/packaging/go-librespot-config.yml ~/.config/go-librespot/config.yml
   ```
   Wichtig sind `credentials.type: device_auth` (Anmeldung per Code, braucht keinen Browser auf der
   Box) und `server.enabled: true`. Die REST-API lauscht dann auf `localhost:3678`.
4. Dienst einrichten:
   ```
   sudo cp ~/spotify-jukebox/slim/packaging/go-librespot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now go-librespot
   journalctl -u go-librespot -f
   ```
5. **Einmalige Anmeldung:** Im Log erscheint ein Link und ein Code. Öffne
   <https://www.spotify.com/pair> auf einem beliebigen Gerät, gib den Code ein und bestätige. Die
   Zugangsdaten speichert der Daemon selbst. Danach taucht „Jukebox" als Gerät in deiner Spotify-App auf.

## 6. Spotify-Anbindung prüfen

```
/opt/jukebox/venv/bin/jukebox spotify-check
```

Ausgabe ohne `FAILED` heißt: Der Daemon antwortet. **Wichtig:** Die in `players/spotify.py`
hinterlegten Endpunkte stammen nicht aus der Spezifikation von go-librespot, sondern sind meine
Annahme **(ungeprüft)**. Funktioniert `spotify-check` nicht oder passiert beim Auflegen einer Karte
nichts, vergleiche die Tabelle `ENDPOINTS` mit der Datei `api-spec.yml` im go-librespot-Repository und
passe sie an. Das ist eine Änderung an einer Stelle.

## 7. Dienst einrichten

Rechte für die Hardware:

```
sudo usermod -aG audio,gpio,i2c,spi,dialout,input pi
```

Dienst installieren und starten:

```
sudo cp ~/spotify-jukebox/slim/packaging/jukebox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jukebox
journalctl -u jukebox -f
```

Zum Ausprobieren kannst du die Box vorher im Vordergrund starten (Strg-C beendet sie):

```
/opt/jukebox/venv/bin/jukebox -v run
```

**Herunterfahren per Karte oder Taste:** Ein Dienst darf `systemctl poweroff` oft nicht ohne
Weiteres ausführen. Erlaube es dem Benutzer gezielt:

```
echo 'pi ALL=NOPASSWD: /usr/bin/systemctl poweroff' | sudo tee /etc/sudoers.d/jukebox
sudo chmod 440 /etc/sudoers.d/jukebox
```

und trage in der `config.toml` ein:

```toml
[system]
shutdown_command = ["sudo", "systemctl", "poweroff"]
```

## 8. Karten anlegen

Lege eine unbekannte Karte auf. Im Log steht `unknown card <ID>`. Dann:

```
/opt/jukebox/venv/bin/jukebox cards add 0123456789 --play spotify:playlist:PLAYLIST-ID --name "Gute Nacht"
/opt/jukebox/venv/bin/jukebox cards add 0123456790 --play folder:hoerbuecher/pumuckl
/opt/jukebox/venv/bin/jukebox cards add 0123456791 --action volume_up
/opt/jukebox/venv/bin/jukebox cards list
sudo systemctl restart jukebox
```

Die Karten werden beim Start gelesen. Nach jeder Änderung an `cards.toml` den Dienst neu starten.

Die Spotify-URI findest du in der Spotify-App unter „Teilen" → „Link kopieren". Aus
`https://open.spotify.com/playlist/ABC123?si=...` wird `spotify:playlist:ABC123`. Lokale Ordner
liegen unter dem `root` aus der Konfiguration (Standard `~/music`) und werden als `folder:<relativer Pfad>` angegeben.

## 9. Mehrere Boxen

Jede Box hat ihre eigene `config.toml` (Pinbelegung, Reader, Sounds, `hooks.py`). Das Repository und der
Code sind überall gleich. Eine neue Box ist: Schritte 1 bis 8, dann `config.toml` und `cards.toml` von
einer bestehenden Box kopieren und die Hardware-Abschnitte anpassen.

## Aktualisieren

```
cd ~/spotify-jukebox && git pull
cd slim && sudo /opt/jukebox/venv/bin/pip install --upgrade .
sudo systemctl restart jukebox
```

go-librespot aktualisierst du, indem du das Binary aus einem neueren Release ersetzt und den Dienst neu
startest. Wenn Spotify nach einem Protokollwechsel plötzlich nicht mehr spielt, ist das der erste Schritt.

## Deinstallieren

```
sudo systemctl disable --now jukebox go-librespot
sudo rm /etc/systemd/system/jukebox.service /etc/systemd/system/go-librespot.service
sudo rm -r /opt/jukebox
```

Den markierten Block in der `config.txt` entfernst du von Hand oder stellst `config.txt.jukebox.bak` wieder her.
