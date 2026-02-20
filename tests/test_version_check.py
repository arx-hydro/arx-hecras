"""Tests for hecras_runner.version_check."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hecras_runner.version_check import VersionInfo, check_for_update, is_outdated, parse_version


class TestParseVersion:
    @pytest.mark.parametrize(
        ("version_str", "expected"),
        [
            ("0.1.0", (0, 1, 0)),
            ("1.10.3", (1, 10, 3)),
            ("1.2.beta", (1, 2)),
            ("5", (5,)),
        ],
        ids=["simple", "higher", "non-numeric-stops", "single"],
    )
    def test_parse(self, version_str, expected):
        assert parse_version(version_str) == expected


class TestIsOutdated:
    @pytest.mark.parametrize(
        ("current", "latest", "expected"),
        [
            ("0.1.0", "0.2.0", True),
            ("0.2.0", "0.2.0", False),
            ("0.3.0", "0.2.0", False),
            ("0.9.9", "1.0.0", True),
        ],
        ids=["outdated", "current", "ahead", "major-bump"],
    )
    def test_is_outdated(self, current, latest, expected):
        assert is_outdated(current, latest) is expected


class TestCheckForUpdate:
    def test_callback_receives_none_on_error(self):
        """When the URL is unreachable, callback gets None (no crash)."""
        results: list[VersionInfo | None] = []

        # Use an obviously invalid URL
        check_for_update("0.1.0", "http://127.0.0.1:1/invalid", results.append, timeout=0.5)

        # Wait for the thread to complete
        import threading

        for t in threading.enumerate():
            if t.daemon and t.is_alive():
                t.join(timeout=2)

        assert len(results) == 1
        assert results[0] is None

    def test_callback_receives_version_info_when_outdated(self):
        """When server reports a newer version, callback gets VersionInfo."""
        import io
        import json

        payload = json.dumps(
            {
                "latest_version": "1.0.0",
                "download_url": "https://example.com/download",
                "release_notes": "Bug fixes",
            }
        ).encode()

        results: list[VersionInfo | None] = []

        mock_response = io.BytesIO(payload)
        mock_response.status = 200  # type: ignore[attr-defined]

        with patch("urllib.request.urlopen", return_value=mock_response):
            check_for_update("0.1.0", "https://example.com/version.json", results.append)

        import threading

        for t in threading.enumerate():
            if t.daemon and t.is_alive():
                t.join(timeout=2)

        assert len(results) == 1
        info = results[0]
        assert isinstance(info, VersionInfo)
        assert info.latest_version == "1.0.0"
        assert info.download_url == "https://example.com/download"

    def test_callback_receives_none_when_up_to_date(self):
        """When already on latest, callback gets None."""
        import io
        import json

        payload = json.dumps({"latest_version": "0.1.0"}).encode()
        mock_response = io.BytesIO(payload)

        results: list[VersionInfo | None] = []

        with patch("urllib.request.urlopen", return_value=mock_response):
            check_for_update("0.1.0", "https://example.com/version.json", results.append)

        import threading

        for t in threading.enumerate():
            if t.daemon and t.is_alive():
                t.join(timeout=2)

        assert len(results) == 1
        assert results[0] is None
