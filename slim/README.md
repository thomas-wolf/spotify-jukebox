# Spotify-Jukebox

Eine RFID-Jukebox für den Raspberry Pi: Karte auflegen, Musik spielt. Das ist die schlanke
Neufassung der Spotify-Edition von Phoniebox v2 (Ausgangspunkt: `RPi-Jukebox-RFID` 2.10).

Ein einziger Python-Prozess, Konfiguration in TOML. Kein PHP, kein MPD, kein Mopidy und keine
Shell-Skripte im Kern.

## Was sie kann

- **Spotify** über einen lokalen [go-librespot](https://github.com/devgianlu/go-librespot)-Daemon.
  Er meldet sich als Spotify-Connect-Gerät an und bietet eine REST-API auf `localhost`.
  Spotify Premium ist nötig.
- **Lokale Ordner** über mpv, mit Wiederaufnahme an der zuletzt gespielten Stelle.
- **Kartenleser:** USB-Reader (Tastatur-Emulation) und RDM6300 (UART). Die Karten-IDs sind mit
  Phoniebox v2 kompatibel, bestehende Karten funktionieren weiter.
- **GPIO:** Tasten (kurz, lang, Wiederholung), Drehencoder, LEDs über libgpiod.
- **Lautstärke-Poti** am ADS1115 (I2C).
- **Overlays:** `jukebox setup` pflegt einen markierten Block in der `config.txt`
  (Profil für den HiFiBerry MiniAmp, SPI, I2C), mit Diff und Backup.
- **Pro Box anpassbar** ohne Codeänderung: Pinbelegung und Reader in `config.toml`, Startsounds pro
  Ereignis, LED-Animationen in einer eigenen `hooks.py`.

Zur Laufzeit braucht der Kern nur Python ≥ 3.11 und die Programme `mpv` und `go-librespot`.
`python3-evdev` und `python3-libgpiod` kommen aus apt und werden nur für USB-Reader bzw. GPIO benötigt.

## Stand

| Teil | Zustand |
|---|---|
| Konfiguration, Karten, Aktionen, Ereignisse, Player-Auswahl, lokale Wiedergabe, `config.txt`-Pflege, Hooks | getestet (65 Tests ohne Hardware) |
| Tasten-, Encoder-, RDM6300-, Poti-Logik | getestet gegen Attrappen |
| REST-Endpunkte von go-librespot (`players/spotify.py`) | **ungeprüft.** Bestätigt ist nur, dass es eine REST-API gibt. Mit `jukebox spotify-check` und der `api-spec.yml` von go-librespot gegenprüfen. |
| libgpiod-Anbindung, mpv-Anbindung, ADS1115, evdev, UART | **noch nicht auf Hardware gelaufen** |
| ILI9341-Display-Treiber | nicht geschrieben (Schnittstelle vorhanden) |
| Cover und Titel aus Spotify | nicht angebunden (go-librespot liefert sie über WebSocket `/events`) |

Alles, was als „ungeprüft" markiert ist, ist auch in den Dokumenten so gekennzeichnet.

## Schnellstart

Die vollständige Anleitung steht in [docs/INSTALL.md](docs/INSTALL.md). Kurzfassung auf einem Pi mit
Raspberry Pi OS (Trixie):

```
sudo apt install -y python3-venv python3-libgpiod python3-evdev mpv alsa-utils git
git clone -b rewrite/slim-core https://github.com/thomas-wolf/spotify-jukebox
cd spotify-jukebox/slim
sudo python3 -m venv --system-site-packages /opt/jukebox/venv
sudo /opt/jukebox/venv/bin/pip install .
mkdir -p ~/.config/jukebox && cp examples/config.toml examples/cards.toml ~/.config/jukebox/
/opt/jukebox/venv/bin/jukebox setup        # zeigt die geplante Änderung der config.txt
```

Danach go-librespot einrichten, Karten anlegen und den Dienst aktivieren (siehe Installationsanleitung).

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | Schritt für Schritt vom leeren Pi zur laufenden Box |
| [docs/CONFIG.md](docs/CONFIG.md) | Alle Einstellungen in `config.toml` und `cards.toml`, alle Aktionen |
| [docs/HARDWARE.md](docs/HARDWARE.md) | MiniAmp, Overlays, Pinbelegung, RDM6300, ADS1115, Display |
| [docs/MIGRATION.md](docs/MIGRATION.md) | Umzug von Phoniebox v2: Karten, Ordner, Steuerkarten |
| [docs/HOOKS.md](docs/HOOKS.md) | Ereignisse, Startsounds, LED-Animationen pro Box |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Fehlersuche |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Aufbau, Tests, neue Reader und Player |

## Lizenz und Herkunft

Dieses Verzeichnis ist eine Neuentwicklung neben dem v2-Code des Repositorys. Das Projekt
Phoniebox/RPi-Jukebox-RFID steht unter der MIT-Lizenz; die Lizenzdatei des Repositorys gilt weiter.
Spotify ist eine Marke von Spotify AB. Die Anbindung nutzt das inoffizielle Protokoll der
librespot-Familie und ist kein von Spotify unterstütztes Produkt.
