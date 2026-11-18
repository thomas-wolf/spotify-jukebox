"""Status values for Home Assistant, served as JSON by the web API (GET /api/metrics).

Everything here is read-only. Values the box cannot know yet are null, not guessed:
battery_soc (no fuel gauge installed) and the Soloist build age (waits for the log format).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .sync import sync_status_path

# Spotify Soloist builds stop working this many days after they were made (see packaging/jukebox-soloist-update).
SOLOIST_BUILD_LIFETIME_DAYS = 90


def read_sync_status(data_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(sync_status_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def soloist_lifetime(built: date | None, today: date | None = None) -> dict[str, int | None]:
    """Age and remaining days of a Soloist build. Both are None while the build date is unknown."""
    if built is None:
        return {"soloist_build_age_days": None, "soloist_expires_in_days": None}
    today = today or datetime.now(timezone.utc).date()
    age = (today - built).days
    return {"soloist_build_age_days": age, "soloist_expires_in_days": SOLOIST_BUILD_LIFETIME_DAYS - age}


def build_metrics(app, soloist_built: date | None = None, today: date | None = None) -> dict[str, Any]:
    """``app`` needs ``cfg`` (Config) and ``cards`` (dict), like jukebox.app.App."""
    spotify = app.cfg.section("spotify")
    sync = read_sync_status(app.cfg.data_dir) or {}
    metrics: dict[str, Any] = {
        "version": __version__,
        "box": app.cfg.section("box")["name"],
        "backend": spotify["backend"],
        "cards": len(app.cards),
        "last_sync": sync.get("last_run"),
        "last_sync_ok": sync.get("ok"),
        "battery_soc": None,
    }
    metrics.update(soloist_lifetime(soloist_built, today))
    return metrics
