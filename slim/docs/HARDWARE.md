# Hardware und Overlays

## HiFiBerry MiniAmp

- Overlay: `dtoverlay=hifiberry-dac`. Dazu muss die Onboard-Audioausgabe aus
  (`dtparam=audio=on` entfernen oder auskommentieren). Beides macht `jukebox setup` für das Profil
  `hifiberry-miniamp`.
- Der MiniAmp hat **keinen Hardware-Mixer**. Die Lautstärke regeln deshalb go-librespot und mpv in der
  Software. Das passt zur Lautstärkelogik der Jukebox, es gibt keine ALSA-Softvol-Konfiguration zu pflegen.
- Der DAC belegt die I2S-Pins GPIO 18 bis 21. Diese Pins darf keine Taste und keine LED nutzen.
- Nach dem Neustart zeigt `aplay -l` eine Karte `sndrpihifiberry`.

Ob go-librespot ohne weitere Einstellung (`audio_device: default`) auf dem DAC ausgibt, hängt davon ab, dass
der DAC die einzige Karte ist. Mit abgeschaltetem Onboard-Audio sollte das der Fall sein
**(auf der Box prüfen)**. Sonst trage in `go-librespot/config.yml` den ALSA-Namen aus `aplay -L` ein.

### Overlays und Pi-Versionen

Overlays hängen vom Pi-Modell und Kernel ab. Deshalb liegt die Auswahl in der `config.toml` jeder Box
(`[boot]`) und nicht im Code:

```toml
[boot]
audio = "hifiberry-miniamp"
spi = true
i2c = true
extra = [
  "dtoverlay=irgendwas",
  { model = "pi5", line = "dtparam=pciex1" },   # gilt nur auf dem Pi 5
]
```

`jukebox setup` schreibt alles in einen markierten Block der `config.txt`:

```
# >>> jukebox managed block (do not edit) >>>
dtoverlay=hifiberry-dac
dtparam=spi=on
# <<< jukebox managed block <<<
```

- Der Befehl ist **idempotent**: Mehrfaches Ausführen ergibt dasselbe, Änderungen in der `config.toml` ersetzen den Block.
- Zeilen außerhalb des Blocks bleiben unberührt, abgesehen vom Auskommentieren von `dtparam=audio=on`.
- Vor der ersten Änderung entsteht **einmalig** `config.txt.jukebox.bak`.
- Den Pfad findet das Tool selbst: `/boot/firmware/config.txt` (aktuelles Raspberry Pi OS), sonst `/boot/config.txt`.
- Mit `i2c = true` schreibt es außerdem `/etc/modules-load.d/jukebox.conf` mit `i2c-dev`, damit `/dev/i2c-1` entsteht.
- Ohne `--apply` zeigt es nur den Diff.

Andere Audio-Hardware: ein weiteres Profil ist eine Zeile in `AUDIO_PRESETS` in `src/jukebox/boot.py`,
oder du setzt `audio` weg und trägst das Overlay unter `extra` ein.

## Pinbelegung (BCM)

Diese Pins sind durch Hardware oder Overlays vergeben. Die Beispielkonfiguration meidet sie.

| Pins | Belegt durch | Hinweis |
|---|---|---|
| 18, 19, 20, 21 | I2S des MiniAmp | nicht verwenden |
| 14 (TX), 15 (RX) | UART (RDM6300) | nur, wenn der RDM6300 benutzt wird |
| 2 (SDA), 3 (SCL) | I2C (ADS1115) | nur mit Poti. **GPIO 3 war in v2 oft der Shutdown-Taster. Mit I2C geht das nicht.** |
| 7, 8, 9, 10, 11 | SPI0 (Display) | nur mit Display |
| 17, 25 | Display DC und RESET | Vorschlag für den ILI9341 (Treiber noch nicht geschrieben) |

Frei und im Beispiel verwendet: 5, 22, 23, 24, 26, 27.

## Tasten, Encoder, LEDs

- Taster gegen Masse schalten und `pull = "up"` lassen (Standard). Der interne Pull-up reicht.
- Drehencoder: gemeinsamer Pin an Masse, A und B an zwei GPIOs. Dreht er falsch herum, tausche
  `cw` und `ccw` in der Konfiguration.
- LED: GPIO → Vorwiderstand (z. B. 330 Ω) → LED → Masse. Gesteuert wird sie nur über Hooks, siehe [HOOKS.md](HOOKS.md).
- Der Dienst läuft als Benutzer in der Gruppe `gpio`. Pins, die ein anderer Prozess hält (etwa ein noch
  laufender alter Phoniebox-Dienst), lassen sich nicht öffnen.

## RDM6300 (125-kHz-Reader)

Verkabelung:

| RDM6300 | Raspberry Pi |
|---|---|
| 5V | 5 V (Pin 2 oder 4) |
| GND | GND |
| TX | RXD, GPIO 15 (Pin 10) |

**Pegel:** Der Reader wird mit 5 V versorgt. Ob sein TX-Ausgang bei deinem Modul 3,3 V liefert, hängt vom Modul ab.
Miss nach oder setze einen Pegelwandler bzw. Spannungsteiler ein, bevor du ihn an den Pi anschließt. Die
GPIO-Eingänge des Pi vertragen 3,3 V.

Serielle Schnittstelle freischalten: `sudo raspi-config` → Interface Options → Serial Port. Auf die Frage
nach der Login-Shell „Nein", auf die Frage nach der seriellen Hardware „Ja" **(Menütext ungeprüft)**. Danach
neu starten. Der Port heißt dann `/dev/serial0`.

Schnelltest: `sudo cat /dev/serial0` zeigt beim Auflegen einer Karte Zeichen an (Binärzeichen mit dem
Text der Karten-ID dazwischen). Auf Modellen mit Bluetooth kann `/dev/serial0` auf die Mini-UART zeigen. Bei
9600 Baud sollte das reichen **(ungeprüft)**.

Das Format der Karten-ID stellt `id_format` ein, siehe [CONFIG.md](CONFIG.md). Für bestehende v2-Karten
bleibt es bei `raw`.

## USB-Reader

Funktioniert, wenn der Reader sich wie eine Tastatur meldet und die Karten-ID mit Enter abschließt. Den
Gerätenamen für `device_name` zeigt:

```
python3 -c "import evdev; [print(evdev.InputDevice(p).name) for p in evdev.list_devices()]"
```

Nicht unterstützt sind bisher RC522 und PN532 (SPI/I2C), die v2 kannte.

## Lautstärke-Poti mit ADS1115

| ADS1115 | Anschluss |
|---|---|
| VDD | 3,3 V |
| GND | GND |
| SDA | GPIO 2 (Pin 3) |
| SCL | GPIO 3 (Pin 5) |
| ADDR | GND → Adresse `0x48` |
| A0 | Schleifer des Potis |

Die beiden äußeren Anschlüsse des Potis gehen an 3,3 V und GND. In der `config.toml`: `[adc] enabled = true`
und `[boot] i2c = true`, dann `jukebox setup --apply` und neu starten. Ob der Chip antwortet, zeigt
`sudo apt install -y i2c-tools && i2cdetect -y 1` (erwartet `48`). Die Kalibrierung macht
`jukebox adc-check`, siehe [CONFIG.md](CONFIG.md).

## Display (ILI9341 über SPI)

**Noch nicht umgesetzt.** Vorhanden ist nur die Schnittstelle (`src/jukebox/display/`): Ein Treiber bekommt
Titel und Cover-URL über das Ereignis `track`. Offen sind der Treiber selbst und die Anbindung der
Cover-Daten von go-librespot (WebSocket `/events` liefert `album_cover_url`). Für den Treiber brauche ich
Auflösung, Drehung und die Pins für DC und RESET.
