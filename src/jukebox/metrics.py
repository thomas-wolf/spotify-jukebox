"""Status values for Home Assistant, served as JSON by the web API (GET /api/metrics).

Everything here is read-only. Values the box cannot know are null, not guessed: battery_soc (no fuel gauge
installed), and the Soloist values when the binary is missing or its version line has no build date.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .sync import sync_status_path

# Spotify Soloist builds stop working this many days after they were made (see packaging/jukebox-soloist-update).
# Confirmed by Soloist itself: a build from 2026-11-17 logged "client expires in 89 days" on 2026-11-18.
SOLOIST_BUILD_LIFETIME_DAYS = 90
SOLOIST_BIN_DEFAULT = "/opt/soloist/soloist"

# First line of `soloist -V`: "soloist 1.3.10.79 build 1794938472 (20261117) (g19412df6ea) (macos/aarch64)"
_BUILD_DATE = re.compile(r"\((\d{4})(\d{2})(\d{2})\)")
_build_cache: dict[tuple[str, int], date | None] = {}


def parse_soloist_build_date(version_output: str) -> date | None:
    first = version_output.strip().splitlines()[0] if version_output.strip() else ""
    m = _BUILD_DATE.search(first)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def soloist_binary() -> Path:
    return Path(os.environ.get("SOLOIST_BIN", SOLOIST_BIN_DEFAULT))


def soloist_build_date(binary: Path | None = None) -> date | None:
    """Build date from `soloist -V`. Cached per file and modification time, so an update is seen."""
    binary = binary or soloist_binary()
    try:
        key = (str(binary), binary.stat().st_mtime_ns)
    except OSError:
        return None
    if key not in _build_cache:
        try:
            out = subprocess.run([str(binary), "-V"], capture_output=True, text=True, timeout=5, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _build_cache.clear()
        _build_cache[key] = parse_soloist_build_date(out)
    return _build_cache[key]


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
        "playtime_today_min": None,
        "battery_soc": None,
    }
    playtime = getattr(app, "playtime", None)  # set by the run command, None in tests and CLI commands
    if playtime is not None:
        metrics["playtime_today_min"] = playtime.minutes(today)
    metrics.update(soloist_lifetime(soloist_built, today))
    return metrics
