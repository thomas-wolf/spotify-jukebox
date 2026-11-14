# Development

## Structure

```
 Reader (thread)  ─┐
 GPIO (thread)    ─┼─►  EventBus (queue)  ─►  App.handle  ─►  PlayerRouter ─┬─► SpotifyPlayer ─► go-librespot (HTTP localhost)
 Potentiometer    ─┘          │                                             └─► LocalPlayer   ─► mpv (JSON IPC socket)
                              └─► observers: sounds, hooks.py, display
```

- Inputs run in threads of their own and do exactly one thing: `bus.post("card", id=...)` or `bus.post("action", ...)`.
- The main loop (`EventBus.run`) takes events one at a time, lets the core (`App.handle`) work first and then
  passes the event on to the observers. So the player logic runs in a single thread and needs no locks.
- Errors in an observer or in the core are logged and end nothing.

```
src/jukebox/
  cli.py          commands (run, setup, cards, spotify-check, adc-check) and wiring
  app.py          cards and actions, volume logic
  config.py       config.toml and cards.toml (reading and writing)
  importer.py     import of Phoniebox v2 cards
  web.py, _page.py  web interface (standard library, one HTML page)
  events.py       EventBus
  hooks.py        event sounds and hooks.py
  boot.py         config.txt maintenance (overlays)
  players/        base (interface), router, spotify, local
  inputs/         usb_reader, rdm6300, gpio, adc
  display/        interface, no driver yet
tests/            pytest, no hardware needed
packaging/        systemd units, go-librespot template
examples/         config.toml, cards.toml, hooks.py
```

## Tests

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The tests need no hardware, no mpv and no go-librespot. `tests/fakes.py` contains stand-ins for players,
mpv and the clock. Covered: configuration, card logic, volume, choosing and switching players, resolving local
paths (including protection against `..`), resume, button and encoder logic, parsing RDM6300 frames,
`config.txt` maintenance, hooks, the v2 importer and the web interface (against a real local HTTP server).

**Not** tested, because hardware or programs are needed: `GpiodBackend`, `MpvClient`, `Ads1115`, the evdev
reader, opening the serial port and the real HTTP against go-librespot. These are the thin layers that have to
be tried on a real box first.

## Adding a new reader (e.g. RC522, PN532)

1. A new file in `src/jukebox/inputs/`. A `threading.Thread` subclass with `stop()` and `run()`.
   Do not use `_stop` as an attribute name; it belongs to `Thread` itself.
2. When a card is read, `self.bus.post("card", id=<ID as text>)`. The ID should be stable and comparable
   case-insensitively.
3. Put the pure evaluation (splitting frames, checksum) in a function of its own and test it without
   hardware, like `parse_frame` for the RDM6300.
4. In `cli.start_inputs`, evaluate a section `[readers.<name>]`.

## Adding a new player

1. Implement the class `Player` from `players/base.py` (`play`, `pause`, `resume`, `stop`, `next`,
   `prev`, `seek`, `set_volume`, `is_playing`). Report errors as `PlayerError`.
2. Register it in `cli.build` under a scheme (`backends["radio"] = ...`). Targets like `radio:...` then go
   to the player automatically. The router keeps only one player running at a time.
3. Test it with `FakePlayer` from `tests/fakes.py` as a model.

## Open work

| Topic | Status |
|---|---|
| Check the go-librespot endpoints against `api-spec.yml`, measure latency card -> sound | most important next step, needs a real box |
| Cover and title from go-librespot (WebSocket `/events`) into the `track` event | open, otherwise the display stays empty |
| ILI9341 driver over SPI (`spidev`, Pillow) | open, needs resolution, rotation, DC/RESET pins |
| Import of v2 cards (`shared/shortcuts`, `spotify.txt`, `rfid_trigger_play.conf`) | possible, see [MIGRATION.md](MIGRATION.md) |
| Reload `cards.toml` without a restart | open |
| RC522 and PN532 readers | open |
| Idle shutdown (power off on inactivity) | open, a hook candidate |
| Hardware test of `GpiodBackend`, `MpvClient`, `Ads1115`, evdev, UART | open |

## Style

- Standard library only in the core. New dependencies only for hardware and as optional imports, so that
  a box starts without them.
- Write parsers, state machines and configuration logic as pure functions so they can be tested without hardware.
- Errors in a hardware or network layer become `PlayerError` or log messages, never a crash of the box.
