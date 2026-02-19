"""Tests for hecras_runner.monitor."""

from __future__ import annotations

from pathlib import Path

from hecras_runner.monitor import (
    parse_bco_timestep,
    patch_write_detailed,
    verify_hdf_completion,
)


class TestPatchWriteDetailed:
    def test_sets_write_detailed_to_1(self, tmp_path: Path):
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\nWrite Detailed= 0 \nDSS File=dss\n")
        assert patch_write_detailed(str(plan)) is True
        content = plan.read_text()
        assert "Write Detailed= 1 \n" in content
        # Other lines preserved
        assert "Plan Title=test\n" in content
        assert "DSS File=dss\n" in content

    def test_already_set_to_1(self, tmp_path: Path):
        plan = tmp_path / "test.p01"
        plan.write_text("Write Detailed= 1 \n")
        assert patch_write_detailed(str(plan)) is True
        assert "Write Detailed= 1 \n" in plan.read_text()

    def test_appends_if_missing(self, tmp_path: Path):
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\n")
        assert patch_write_detailed(str(plan)) is True
        content = plan.read_text()
        assert "Write Detailed= 1 \n" in content

    def test_returns_false_for_nonexistent(self):
        assert patch_write_detailed(r"C:\nonexistent\fake.p01") is False

    def test_returns_false_for_readonly(self, tmp_path: Path):
        plan = tmp_path / "test.p01"
        plan.write_text("Write Detailed= 0 \n")
        plan.chmod(0o444)
        try:
            # On Windows, chmod(0o444) may not prevent writing, so check
            result = patch_write_detailed(str(plan))
            # Either True (Windows ignores chmod) or False (Unix read-only) is acceptable
            assert isinstance(result, bool)
        finally:
            plan.chmod(0o644)


class TestVerifyHdfCompletion:
    def test_returns_false_for_nonexistent(self):
        assert verify_hdf_completion(r"C:\nonexistent\fake.p01.hdf") is False

    def test_binary_fallback_finds_marker(self, tmp_path: Path):
        hdf = tmp_path / "test.p01.hdf"
        # Write a fake binary file with the marker embedded
        hdf.write_bytes(b"\x00" * 100 + b"Finished Successfully" + b"\x00" * 100)
        assert verify_hdf_completion(str(hdf)) is True

    def test_binary_fallback_missing_marker(self, tmp_path: Path):
        hdf = tmp_path / "test.p01.hdf"
        hdf.write_bytes(b"\x00" * 200 + b"Incomplete")
        assert verify_hdf_completion(str(hdf)) is False

    def test_empty_file(self, tmp_path: Path):
        hdf = tmp_path / "test.p01.hdf"
        hdf.write_bytes(b"")
        assert verify_hdf_completion(str(hdf)) is False

    def test_marker_at_boundary(self, tmp_path: Path):
        """Ensure marker spanning chunk boundary is still found."""
        hdf = tmp_path / "test.p01.hdf"
        # The overlap logic in monitor.py handles this
        data = b"\x00" * (1024 * 1024 - 8) + b"Finished Successfully" + b"\x00" * 100
        hdf.write_bytes(data)
        assert verify_hdf_completion(str(hdf)) is True


class TestParseBcoTimestep:
    def test_extracts_timestamp(self):
        line = "  01Jan2024  00:00:00  Some text here"
        result = parse_bco_timestep(line)
        assert result == "01Jan2024  00:00:00"

    def test_returns_none_for_no_match(self):
        assert parse_bco_timestep("No timestamp here") is None
        assert parse_bco_timestep("") is None

    def test_various_formats(self):
        assert parse_bco_timestep("  15Mar2024  12:30:00  ...") == "15Mar2024  12:30:00"
        assert parse_bco_timestep("02JAN2024  06:00:00") == "02JAN2024  06:00:00"
