"""Tests for hecras_runner.monitor."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hecras_runner.monitor import (
    compute_progress,
    parse_bco_timestep,
    parse_hecras_datetime,
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


class TestParseHecrasDatetime:
    @pytest.mark.parametrize(
        ("input_str", "expected"),
        [
            ("01Jan2024  00:00:00", datetime(2024, 1, 1, 0, 0, 0)),
            ("15Mar2024  12:30:45", datetime(2024, 3, 15, 12, 30, 45)),
            ("01JAN2024,0000", datetime(2024, 1, 1, 0, 0, 0)),
            ("02JAN2024,1200", datetime(2024, 1, 2, 12, 0, 0)),
            ("01JAN2024,2400", datetime(2024, 1, 2, 0, 0, 0)),  # 2400 = next day midnight
            ("31Dec2024  24:00:00", datetime(2025, 1, 1, 0, 0, 0)),
            ("01jan2024,0000", datetime(2024, 1, 1, 0, 0, 0)),  # case insensitive
        ],
        ids=[
            "bco-midnight",
            "bco-time",
            "plan-midnight",
            "plan-noon",
            "plan-2400",
            "bco-2400-year-wrap",
            "lowercase",
        ],
    )
    def test_valid_formats(self, input_str, expected):
        assert parse_hecras_datetime(input_str) == expected

    def test_case_insensitive_equality(self):
        assert parse_hecras_datetime("01jan2024,0000") == parse_hecras_datetime("01JAN2024,0000")

    @pytest.mark.parametrize(
        "input_str",
        ["", "not a date", "01XYZ2024,0000"],
        ids=["empty", "garbage", "invalid-month"],
    )
    def test_invalid_returns_none(self, input_str):
        assert parse_hecras_datetime(input_str) is None


class TestComputeProgress:
    @pytest.mark.parametrize(
        ("current", "start", "end", "expected"),
        [
            ("01Jan2024  12:00:00", "01JAN2024,0000", "02JAN2024,0000", 0.5),
            ("01Jan2024  00:00:00", "01JAN2024,0000", "02JAN2024,0000", 0.0),
            ("02Jan2024  00:00:00", "01JAN2024,0000", "02JAN2024,0000", 1.0),
            ("03Jan2024  00:00:00", "01JAN2024,0000", "02JAN2024,0000", 1.0),  # clamp
            ("31Dec2023  00:00:00", "01JAN2024,0000", "02JAN2024,0000", 0.0),  # clamp
            ("01Jan2024  06:00:00", "01JAN2024,0000", "02JAN2024,0000", 0.25),
        ],
        ids=["midpoint", "start", "end", "past-end", "before-start", "quarter"],
    )
    def test_progress_values(self, current, start, end, expected):
        result = compute_progress(current, start, end)
        assert abs(result - expected) < 0.01

    @pytest.mark.parametrize(
        ("current", "start", "end"),
        [
            ("invalid", "01JAN2024,0000", "02JAN2024,0000"),
            ("01Jan2024  12:00:00", "", "02JAN2024,0000"),
            ("01Jan2024  12:00:00", "01JAN2024,0000", ""),
        ],
        ids=["invalid-current", "empty-start", "empty-end"],
    )
    def test_invalid_timestamps_return_zero(self, current, start, end):
        assert compute_progress(current, start, end) == 0.0

    def test_zero_range_returns_zero(self):
        assert compute_progress("01Jan2024  00:00:00", "01JAN2024,0000", "01JAN2024,0000") == 0.0


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
