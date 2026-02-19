"""Completion detection and progress monitoring for HEC-RAS simulations.

Zero hard deps — h5py is optional (falls back to binary scan for HDF verification).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable


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
                on_progress(0.0, last_timestamp)

        time.sleep(poll_interval)
