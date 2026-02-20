"""Tests for hecras_runner.version_check."""

from __future__ import annotations

from unittest.mock import patch

from hecras_runner.version_check import VersionInfo, _parse_version, check_for_update, is_outdated


class TestParseVersion:
    def test_simple(self):
        assert _parse_version("0.1.0") == (0, 1, 0)

    def test_higher(self):
        assert _parse_version("1.10.3") == (1, 10, 3)

    def test_non_numeric_segment_stops(self):
        assert _parse_version("1.2.beta") == (1, 2)

    def test_single_segment(self):
        assert _parse_version("5") == (5,)


class TestIsOutdated:
    def test_outdated(self):
        assert is_outdated("0.1.0", "0.2.0") is True

    def test_current(self):
        assert is_outdated("0.2.0", "0.2.0") is False

    def test_ahead(self):
        assert is_outdated("0.3.0", "0.2.0") is False

    def test_major_bump(self):
        assert is_outdated("0.9.9", "1.0.0") is True


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
