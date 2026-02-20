"""Background version check — zero external dependencies."""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class VersionInfo:
    """Information about an available update."""

    latest_version: str
    download_url: str
    release_notes: str


def parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '0.2.0' into a tuple of ints."""
    parts: list[int] = []
    for segment in v.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


def is_outdated(current: str, latest: str) -> bool:
    """Return True if *current* is older than *latest*."""
    return parse_version(current) < parse_version(latest)


def check_for_update(
    current_version: str,
    url: str,
    callback: Callable[[VersionInfo | None], None],
    timeout: float = 5.0,
) -> None:
    """Fetch version info in a background thread.

    Calls *callback* with a ``VersionInfo`` if the running version is outdated,
    or ``None`` if up-to-date or on any error (offline, bad URL, etc.).
    The callback is invoked from the background thread.
    """

    def _fetch() -> None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hecras-runner"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            latest = data.get("latest_version", "")
            if latest and is_outdated(current_version, latest):
                info = VersionInfo(
                    latest_version=latest,
                    download_url=data.get("download_url", ""),
                    release_notes=data.get("release_notes", ""),
                )
                callback(info)
            else:
                callback(None)
        except Exception:
            callback(None)

    thread = threading.Thread(target=_fetch, daemon=True)
    thread.start()
