"""Application settings management — persisted to %APPDATA%/hecras_runner/settings.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class DbSettings:
    """PostgreSQL connection settings."""

    host: str = "hydro-arx-dev-01.cuwlgbeagerx.us-west-2.rds.amazonaws.com"
    port: int = 5432
    dbname: str = "hydro_arx_dev"
    user: str = "hecras_runner"
    password: str = ""


@dataclass
class NetworkSettings:
    """Distributed execution settings."""

    enabled: bool = False
    share_path: str = (
        r"X:\Technical\01_Projects\213_UAE"
        r"\78.1014.00000 - Al Ain Flood Protection\hecras_share_test"
    )
    worker_mode: bool = False  # accept jobs from queue
    max_concurrent: int = 1
    terrain_cache_max_gb: float = 10.0


@dataclass
class AppSettings:
    """Top-level application settings."""

    db: DbSettings = field(default_factory=DbSettings)
    network: NetworkSettings = field(default_factory=NetworkSettings)
    update_url: str = "https://updates.arx.engineering/hecras-runner/version.json"


def _settings_dir() -> str:
    """Return the settings directory path (%APPDATA%/hecras_runner/)."""
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        appdata = os.path.expanduser("~")
    return os.path.join(appdata, "hecras_runner")


def _settings_path() -> str:
    """Return the full path to settings.json."""
    return os.path.join(_settings_dir(), "settings.json")


def load_settings() -> AppSettings:
    """Load settings from disk. Returns defaults if file missing or corrupt."""
    path = _settings_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return AppSettings()

    if not isinstance(data, dict):
        return AppSettings()

    db_data = data.get("db", {})
    net_data = data.get("network", {})

    db = DbSettings(
        host=str(db_data.get("host", "")),
        port=int(db_data.get("port", 5432)),
        dbname=str(db_data.get("dbname", "hydro_arx_dev")),
        user=str(db_data.get("user", "hecras_runner")),
        password=str(db_data.get("password", "")),
    )
    network = NetworkSettings(
        enabled=bool(net_data.get("enabled", False)),
        share_path=str(net_data.get("share_path", "")),
        worker_mode=bool(net_data.get("worker_mode", False)),
        max_concurrent=int(net_data.get("max_concurrent", 1)),
        terrain_cache_max_gb=float(net_data.get("terrain_cache_max_gb", 10.0)),
    )
    update_url = str(data.get("update_url", AppSettings.update_url))
    return AppSettings(db=db, network=network, update_url=update_url)


def save_settings(settings: AppSettings) -> None:
    """Save settings to disk. Creates the directory if needed."""
    directory = _settings_dir()
    os.makedirs(directory, exist_ok=True)

    path = _settings_path()
    data = asdict(settings)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
