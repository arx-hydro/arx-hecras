"""Tests for hecras_runner.settings."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from hecras_runner.settings import (
    AppSettings,
    DbSettings,
    NetworkSettings,
    load_settings,
    save_settings,
)


class TestAppSettings:
    def test_defaults(self):
        s = AppSettings()
        assert s.db.host == "hydro-arx-dev-01.cuwlgbeagerx.us-west-2.rds.amazonaws.com"
        assert s.db.port == 5432
        assert s.db.dbname == "hydro_arx_dev"
        assert s.network.enabled is False
        assert s.network.max_concurrent == 1
        assert s.update_url == "https://updates.arx.engineering/hecras-runner/version.json"

    def test_custom_values(self):
        s = AppSettings(
            db=DbSettings(host="myhost", port=5433),
            network=NetworkSettings(enabled=True, share_path=r"\\SRV\share"),
        )
        assert s.db.host == "myhost"
        assert s.db.port == 5433
        assert s.network.share_path == r"\\SRV\share"


class TestLoadSettings:
    def test_returns_defaults_when_file_missing(self, tmp_path: Path):
        fake_path = str(tmp_path / "nonexistent" / "settings.json")
        with patch("hecras_runner.settings._settings_path", return_value=fake_path):
            s = load_settings()
        assert s.db.host == "hydro-arx-dev-01.cuwlgbeagerx.us-west-2.rds.amazonaws.com"
        assert s.network.enabled is False

    def test_loads_from_file(self, tmp_path: Path):
        data = {
            "db": {"host": "db.example.com", "port": 5433, "password": "secret"},
            "network": {"enabled": True, "share_path": r"\\SRV\q", "max_concurrent": 3},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(data))

        with patch("hecras_runner.settings._settings_path", return_value=str(settings_file)):
            s = load_settings()

        assert s.db.host == "db.example.com"
        assert s.db.port == 5433
        assert s.db.password == "secret"
        assert s.network.enabled is True
        assert s.network.share_path == r"\\SRV\q"
        assert s.network.max_concurrent == 3

    def test_corrupt_json_returns_defaults(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{bad json")

        with patch("hecras_runner.settings._settings_path", return_value=str(settings_file)):
            s = load_settings()

        assert s.db.host == "hydro-arx-dev-01.cuwlgbeagerx.us-west-2.rds.amazonaws.com"

    def test_non_dict_json_returns_defaults(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('"just a string"')

        with patch("hecras_runner.settings._settings_path", return_value=str(settings_file)):
            s = load_settings()

        assert s.db.host == "hydro-arx-dev-01.cuwlgbeagerx.us-west-2.rds.amazonaws.com"

    def test_partial_data_fills_defaults(self, tmp_path: Path):
        data = {"db": {"host": "myhost"}}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(data))

        with patch("hecras_runner.settings._settings_path", return_value=str(settings_file)):
            s = load_settings()

        assert s.db.host == "myhost"
        assert s.db.port == 5432  # default
        assert s.network.enabled is False  # default


class TestSaveSettings:
    def test_round_trip(self, tmp_path: Path):
        settings_file = tmp_path / "hecras_runner" / "settings.json"

        dir_rv = str(tmp_path / "hecras_runner")
        file_rv = str(settings_file)
        with (
            patch("hecras_runner.settings._settings_dir", return_value=dir_rv),
            patch("hecras_runner.settings._settings_path", return_value=file_rv),
        ):
            original = AppSettings(
                db=DbSettings(host="rds.example.com", password="pw123"),
                network=NetworkSettings(enabled=True, share_path=r"\\X\Y"),
            )
            save_settings(original)

            loaded = load_settings()

        assert loaded.db.host == "rds.example.com"
        assert loaded.db.password == "pw123"
        assert loaded.network.enabled is True
        assert loaded.network.share_path == r"\\X\Y"

    def test_creates_directory(self, tmp_path: Path):
        new_dir = tmp_path / "new_subdir"
        settings_file = new_dir / "settings.json"

        with (
            patch("hecras_runner.settings._settings_dir", return_value=str(new_dir)),
            patch("hecras_runner.settings._settings_path", return_value=str(settings_file)),
        ):
            save_settings(AppSettings())

        assert settings_file.exists()
