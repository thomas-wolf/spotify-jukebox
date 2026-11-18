# Home Assistant integration

Status: in progress on branch `feature/home-assistant-integration`. Open points are at the end.

## Goals

1. **Metrics:** let Home Assistant (HA) show the health of each box. HA only reads; it does not control playback.
2. **Battery state of charge:** planned, needs hardware (see below).

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
| `soloist_build_age_days` | Age of the Soloist build in days | build date from `soloist -V`, `null` if no binary |
| `soloist_expires_in_days` | `90 - age`, remaining days | same |
| `battery_soc` | Battery state of charge in percent | **no hardware yet**, always `null` |

Values the box cannot know are `null`, never guessed.

### Soloist build expiry

Spotify builds of Soloist stop working 90 days after they were made. Exit code 10 means the build has
expired (`packaging/soloist.service`). `SOLOIST_BUILD_LIFETIME_DAYS` in `metrics.py` holds the 90.

The build date is read from the first line of `soloist -V`, e.g. `soloist 1.3.10.79 build 1794938472 (20261117) ...`
(binary from `SOLOIST_BIN`, default `/opt/soloist/soloist`). Not from the time of the last update: the update
timer runs weekly even when nothing changes. The result is cached per file and modification time.

Checked against Soloist's own log: a build from 2026-11-17 logged `client expires in 89 days` on 2026-11-18,
which is 90 days after the build date.

### Last sync

`Syncer.run_once()` writes `sync-status.json` to the data dir after every run that had at least one enabled
part (cards, config, music). Dry runs do not write it. A write failure is logged and does not stop the sync.

## Control

Out of scope. HA does not start, pause or change playback. The existing action endpoints in the web API
are unchanged and not used by HA.

## Open points

- **Transport for HA.** HA polls `/api/metrics` with a REST sensor. This needs no new dependency, since the
  core only uses the standard library. The alternative is MQTT with HA discovery, which needs a client library
  such as `paho-mqtt`. For read-only metrics, polling is enough. Decide whether MQTT is still wanted.
- **Web API exposure.** Not part of HA work, but worth knowing: `/api/*` has no authentication (see
  `docs/CONFIG.md`). With `[web]` enabled, anyone who can reach the port can change cards and control playback.
  HA does not change that. Decide whether this needs a fix later.
- **Battery.** Needs a fuel gauge on the I²C bus (e.g. MAX17048) or a UPS HAT that reports SoC.
  Nothing is installed yet.
- **Boxes.** All boxes should get the same integration, differing only in config and name.
