# Home Assistant integration

Status: in progress on branch `feature/home-assistant-integration`. Open points are at the end.

## Goals

1. **Metrics:** let Home Assistant (HA) show the health of each box.
2. **Control:** let HA start playback (including a Spotify link), pause, skip, and set the volume.
3. **Battery state of charge:** planned, needs hardware (see below).

## Metrics: `GET /api/metrics`

Served by the existing web API (`[web]` section, off by default). Read-only JSON:

| Field | Meaning | Source |
|---|---|---|
| `version` | Jukebox version | `jukebox.__version__` |
| `box` | Box name | `[box] name` |
| `backend` | `go-librespot` or `soloist` | `[spotify] backend` |
| `cards` | Number of cards in `cards.toml` | loaded cards |
| `last_sync` | UTC time of the last Dropbox sync run (ISO 8601) | `sync-status.json` in the data dir |
| `last_sync_ok` | `false` if the last run had errors | `sync-status.json` |
| `soloist_build_age_days` | Age of the Soloist build in days | build date, **not yet available** |
| `soloist_expires_in_days` | `90 - age`, remaining days | same, **not yet available** |
| `battery_soc` | Battery state of charge in percent | **no hardware yet**, always `null` |

Values the box cannot know are `null`, never guessed.

### Soloist build expiry

Spotify builds of Soloist stop working 90 days after they were made. Exit code 10 means the build has
expired (`packaging/soloist.service`). `SOLOIST_BUILD_LIFETIME_DAYS` in `metrics.py` holds the 90.

The metric must come from Soloist's own output (log line or CLI), not from the time of the last update:
the update timer runs weekly even when nothing changes. The parser for that output is still to be written;
it needs a sample of the log line.

### Last sync

`Syncer.run_once()` writes `sync-status.json` to the data dir after every run that had at least one enabled
part (cards, config, music). Dry runs do not write it. A write failure is logged and does not stop the sync.

## Control

HA calls the existing action endpoint `POST /api/action` with `{"name": ..., "args": {...}}`.
Available actions today (from `app.py`):

`play_pause`, `pause`, `resume`, `stop`, `next`, `prev`, `seek_forward`, `seek_back`, `volume_up`,
`volume_down`, `volume_set`, `mute`, `shutdown`.

Missing: starting an arbitrary Spotify link. The only play route today is a stored card
(`POST /api/cards/<id>/play`). A `play` action with a `target` argument is needed. It must reuse the
target check in `web.validate_card` so that only valid targets get through.

All playback goes through `PlayerRouter`, which picks the backend by the URI scheme (`spotify:`).
The same commands therefore work with both go-librespot and Soloist.

## Open points

- **Transport for HA.** Option A (current plan): HA polls `/api/metrics` and calls `/api/action`
  with REST sensors and `rest_command`. Needs no new dependency, since the core only uses the standard library.
  Option B: MQTT with HA discovery, which needs a client library such as `paho-mqtt`. Decide before building.
- **Authentication.** `/api/*` has no authentication (see `docs/CONFIG.md`). Anyone who can reach the port
  can control playback. Before HA controls the box, either bind to the LAN only with a token, or limit it
  by firewall.
- **Soloist log format.** Needed for the expiry metric.
- **Battery.** Needs a fuel gauge on the I²C bus (e.g. MAX17048) or a UPS HAT that reports SoC.
  Nothing is installed yet.
- **Boxes.** All boxes should get the same integration, differing only in config and name.
