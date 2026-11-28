"""Which build is installed, and did it change since the last start?

`jukebox-deploy` writes the build (short commit hash, or the given ref) to /opt/jukebox/VERSION. The service
remembers the build it ran last in `<data_dir>/build.txt`; a different build at the next start is an update.
"""

from __future__ import annotations

import os
from pathlib import Path

VERSION_FILE = "/opt/jukebox/VERSION"


def installed_build(path: str | os.PathLike | None = None) -> str:
    """Content of the VERSION file ("" if there is none, e.g. a development checkout)."""
    try:
        return Path(path or os.environ.get("JUKEBOX_VERSION_FILE", VERSION_FILE)).read_text().strip().splitlines()[0]
    except (OSError, IndexError):
        return ""


def check_update(data_dir: Path, build: str | None = None) -> tuple[str, str] | None:
    """(old, new) if the installed build differs from the one that ran last, else None. Remembers the build.
    The very first start (nothing remembered) and a box without VERSION file give None."""
    build = installed_build() if build is None else build
    if not build:
        return None
    state = Path(data_dir) / "build.txt"
    try:
        old = state.read_text().strip()
    except OSError:
        old = ""
    if old != build:
        try:
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(build + "\n")
        except OSError:
            return None
    return (old, build) if old and old != build else None
