"""Completion detection and progress monitoring for HEC-RAS simulations.

Zero hard deps — h5py is optional (falls back to binary scan for HDF verification).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import datetime


def patch_write_detailed(plan_path: str) -> bool:
    """Set ``Write Detailed= 1`` in a .p## file so .bco output is generated.

    Returns True if the file was modified (or already had the setting),
    False if the file could not be read/written.
    """
    try:
        with open(plan_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    found = False
    for i, line in enumerate(lines):
        if line.startswith("Write Detailed="):
            lines[i] = "Write Detailed= 1 \n"
            found = True
            break

    if not found:
        # Append if not present
        lines.append("Write Detailed= 1 \n")

    try:
        with open(plan_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        return False
    return True


def verify_hdf_completion(hdf_path: str) -> bool:
    """Check a .p##.hdf file for success markers indicating simulation completion.

    Looks for ``"Finished Successfully"`` or ``"Completed Successfully"`` in HDF
    attributes (e.g. ``Results/Unsteady/Summary/Solution``).
    Tries h5py first, then falls back to a raw binary scan.

    Returns True if the completion marker is found, False otherwise.
    """
    if not os.path.isfile(hdf_path):
        return False

    # Success markers found in HEC-RAS HDF output
    success_markers = ("Finished Successfully", "Completed Successfully")

    # Try h5py first
    try:
        import h5py

        with h5py.File(hdf_path, "r") as hf:
            # Check known attribute locations
            for attr_path in (
                "Results/Unsteady/Summary",
                "Results/Steady/Summary",
                "Plan Data/Plan Information",
                "Results/Summary",
            ):
                if attr_path in hf:
                    group = hf[attr_path]
                    for attr_name in group.attrs:
                        val = group.attrs[attr_name]
                        text = (
                            val if isinstance(val, str)
                            else val.decode("utf-8", errors="replace")
                            if isinstance(val, bytes)
                            else str(val)
                        )
                        if any(m in text for m in success_markers):
                            return True
            return False
    except Exception:
        pass

    # Binary fallback — scan for the UTF-8 byte sequences
    markers = (b"Finished Successfully", b"Completed Successfully")
    try:
        chunk_size = 1024 * 1024  # 1 MB chunks
        overlap = max(len(m) for m in markers) - 1
        with open(hdf_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                if any(m in chunk for m in markers):
                    return True
                # Only seek back for overlap if we read a full chunk (more data ahead)
                if len(chunk) == chunk_size:
                    f.seek(f.tell() - overlap)
    except OSError:
        pass
    return False


# ── Datetime parsing and progress computation ──

# Month abbreviations used by HEC-RAS (case-insensitive)
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# .bco format: "01Jan2024  00:00:00"
_BCO_DT_RE = re.compile(r"(\d{2})(\w{3})(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")

# Plan file format: "01JAN2024,0000" or "01JAN2024,2400"
_PLAN_DT_RE = re.compile(r"(\d{2})(\w{3})(\d{4}),(\d{4})")


def _parse_hecras_datetime(s: str) -> datetime | None:
    """Parse a HEC-RAS datetime string into a :class:`datetime`.

    Supports two formats:

    - .bco format: ``"01Jan2024  00:00:00"``
    - Plan file format: ``"01JAN2024,0000"``

    Returns None if the string cannot be parsed.
    """
    if not s:
        return None

    # Try .bco format first
    m = _BCO_DT_RE.search(s)
    if m:
        day, mon_str, year, hour, minute, second = m.groups()
        month = _MONTH_MAP.get(mon_str.upper())
        if month is None:
            return None
        h, mi = int(hour), int(minute)
        # HEC-RAS uses 2400 to mean midnight of next day
        if h == 24:
            h, mi = 0, 0
            from datetime import timedelta
            dt = datetime(int(year), month, int(day), 0, 0, int(second))
            return dt + timedelta(days=1)
        return datetime(int(year), month, int(day), h, mi, int(second))

    # Try plan format
    m = _PLAN_DT_RE.search(s)
    if m:
        day, mon_str, year, hhmm = m.groups()
        month = _MONTH_MAP.get(mon_str.upper())
        if month is None:
            return None
        h, mi = int(hhmm[:2]), int(hhmm[2:])
        if h == 24:
            h, mi = 0, 0
            from datetime import timedelta
            dt = datetime(int(year), month, int(day), 0, 0, 0)
            return dt + timedelta(days=1)
        return datetime(int(year), month, int(day), h, mi, 0)

    return None


def compute_progress(
    current_ts: str,
    start_ts: str,
    end_ts: str,
) -> float:
    """Compute simulation progress as a fraction from 0.0 to 1.0.

    Parameters
    ----------
    current_ts : str
        Current simulation timestamp (from .bco).
    start_ts : str
        Simulation start datetime (from plan file).
    end_ts : str
        Simulation end datetime (from plan file).

    Returns 0.0 if any timestamp cannot be parsed or if the range is zero.
    """
    current = _parse_hecras_datetime(current_ts)
    start = _parse_hecras_datetime(start_ts)
    end = _parse_hecras_datetime(end_ts)

    if current is None or start is None or end is None:
        return 0.0

    total = (end - start).total_seconds()
    if total <= 0:
        return 0.0

    elapsed = (current - start).total_seconds()
    return max(0.0, min(1.0, elapsed / total))


# Pattern: "01Jan2024  00:00:00" or similar timestamps in .bco files
_BCO_TIMESTAMP_RE = re.compile(
    r"(\d{2}\w{3}\d{4}\s+\d{2}:\d{2}:\d{2})"
)


def parse_bco_timestep(line: str) -> str | None:
    """Extract a simulation timestamp from a .bco log line.

    Returns the timestamp string (e.g. ``"01Jan2024  00:00:00"``) or None.
    """
    m = _BCO_TIMESTAMP_RE.search(line)
    return m.group(1) if m else None


def monitor_bco(
    bco_path: str,
    sim_start: str,
    sim_end: str,
    on_progress: Callable[[float, str], None],
    poll_interval: float = 0.5,
    timeout: float = 7200.0,
) -> None:
    """Poll a .bco file for simulation progress until completion or timeout.

    Parameters
    ----------
    bco_path : str
        Path to the .bco## file written by HEC-RAS.
    sim_start : str
        Simulation start date string from plan file (e.g. ``"01JAN2024,0000"``).
    sim_end : str
        Simulation end date string from plan file (e.g. ``"02JAN2024,1200"``).
    on_progress : callable
        Called with ``(fraction, latest_timestamp)`` where fraction is 0.0-1.0.
    poll_interval : float
        Seconds between polls.
    timeout : float
        Maximum seconds to monitor before giving up.
    """
    start_time = time.monotonic()
    file_pos = 0
    last_timestamp = ""

    while (time.monotonic() - start_time) < timeout:
        try:
            with open(bco_path, encoding="utf-8", errors="replace") as f:
                f.seek(file_pos)
                new_data = f.read()
                file_pos = f.tell()
        except OSError:
            time.sleep(poll_interval)
            continue

        if new_data:
            for line in new_data.splitlines():
                ts = parse_bco_timestep(line)
                if ts:
                    last_timestamp = ts

            if last_timestamp:
                fraction = compute_progress(last_timestamp, sim_start, sim_end)
                on_progress(fraction, last_timestamp)

        time.sleep(poll_interval)
