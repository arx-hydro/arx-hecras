"""Parse HEC-RAS project files (.prj, .p##, .g##, .u##)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PlanEntry:
    """A single HEC-RAS plan."""

    key: str  # e.g. "p03"
    title: str  # e.g. "plan03"
    geom_ref: str  # e.g. "g01"
    flow_ref: str  # e.g. "u03"


@dataclass
class GeomEntry:
    """A single HEC-RAS geometry."""

    key: str  # e.g. "g01"
    title: str  # e.g. "geoBR"


@dataclass
class FlowEntry:
    """A single HEC-RAS unsteady flow."""

    key: str  # e.g. "u01"
    title: str  # e.g. "unsteady01"
    dss_files: list[str] = field(default_factory=list)


@dataclass
class RasProject:
    """Parsed HEC-RAS project."""

    path: str
    title: str
    plans: list[PlanEntry] = field(default_factory=list)
    geometries: list[GeomEntry] = field(default_factory=list)
    flows: list[FlowEntry] = field(default_factory=list)
    current_plan: str | None = None
    dss_files: list[str] = field(default_factory=list)


def _read_file(path: str) -> str:
    """Read a text file with encoding fallback: utf-8 -> latin-1 -> cp1252."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(path, encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise UnicodeDecodeError("utf-8/latin-1/cp1252", b"", 0, 1, f"Cannot decode {path}")


def _get_value(line: str, prefix: str) -> str | None:
    """Extract value after 'Prefix=' from a line, or None if no match."""
    if line.startswith(prefix):
        return line[len(prefix) :].strip()
    return None


def parse_plan_file(path: str, key: str) -> PlanEntry | None:
    """Parse a .p## file and return a PlanEntry."""
    try:
        text = _read_file(path)
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Cannot read plan file %s: %s", path, e)
        return None

    title = ""
    geom_ref = ""
    flow_ref = ""

    for line in text.splitlines():
        if v := _get_value(line, "Plan Title="):
            title = v
        elif v := _get_value(line, "Geom File="):
            geom_ref = v
        elif v := _get_value(line, "Flow File="):
            flow_ref = v

    return PlanEntry(key=key, title=title, geom_ref=geom_ref, flow_ref=flow_ref)


def parse_geom_file(path: str, key: str) -> GeomEntry | None:
    """Parse a .g## file and return a GeomEntry."""
    try:
        text = _read_file(path)
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Cannot read geometry file %s: %s", path, e)
        return None

    title = ""
    for line in text.splitlines():
        if v := _get_value(line, "Geom Title="):
            title = v
            break

    return GeomEntry(key=key, title=title)


def parse_flow_file(path: str, key: str) -> FlowEntry | None:
    """Parse a .u## file and return a FlowEntry."""
    try:
        text = _read_file(path)
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Cannot read flow file %s: %s", path, e)
        return None

    title = ""
    dss_files: list[str] = []

    for line in text.splitlines():
        if v := _get_value(line, "Flow Title="):
            title = v
        elif (v := _get_value(line, "DSS File=")) and v not in dss_files:
            dss_files.append(v)

    return FlowEntry(key=key, title=title, dss_files=dss_files)


_KEY_PATTERN = re.compile(r"^[a-z]\d{2}$")


def parse_project(prj_path: str) -> RasProject:
    """Parse a .prj file and all referenced plan/geom/flow files.

    Missing referenced files are logged and skipped.
    """
    prj_path = os.path.abspath(prj_path)
    prj_dir = os.path.dirname(prj_path)
    basename = os.path.splitext(os.path.basename(prj_path))[0]

    text = _read_file(prj_path)

    title = ""
    current_plan: str | None = None
    plan_keys: list[str] = []
    geom_keys: list[str] = []
    flow_keys: list[str] = []
    dss_files: list[str] = []

    for line in text.splitlines():
        if v := _get_value(line, "Proj Title="):
            title = v
        elif v := _get_value(line, "Current Plan="):
            current_plan = v
        elif (v := _get_value(line, "Plan File=")) and _KEY_PATTERN.match(v):
            plan_keys.append(v)
        elif (v := _get_value(line, "Geom File=")) and _KEY_PATTERN.match(v):
            geom_keys.append(v)
        elif (v := _get_value(line, "Unsteady File=")) and _KEY_PATTERN.match(v):
            flow_keys.append(v)
        elif (v := _get_value(line, "DSS File=")) and v not in dss_files:
            dss_files.append(v)

    # Parse referenced files
    plans: list[PlanEntry] = []
    for key in plan_keys:
        path = os.path.join(prj_dir, f"{basename}.{key}")
        entry = parse_plan_file(path, key)
        if entry:
            plans.append(entry)

    geometries: list[GeomEntry] = []
    seen_geom_keys = set()
    # Collect geom keys from both .prj and plan references
    all_geom_keys = list(geom_keys)
    for plan in plans:
        if plan.geom_ref and plan.geom_ref not in all_geom_keys:
            all_geom_keys.append(plan.geom_ref)
    for key in all_geom_keys:
        if key in seen_geom_keys:
            continue
        seen_geom_keys.add(key)
        path = os.path.join(prj_dir, f"{basename}.{key}")
        entry = parse_geom_file(path, key)
        if entry:
            geometries.append(entry)

    flows: list[FlowEntry] = []
    seen_flow_keys = set()
    all_flow_keys = list(flow_keys)
    for plan in plans:
        if plan.flow_ref and plan.flow_ref not in all_flow_keys:
            all_flow_keys.append(plan.flow_ref)
    for key in all_flow_keys:
        if key in seen_flow_keys:
            continue
        seen_flow_keys.add(key)
        path = os.path.join(prj_dir, f"{basename}.{key}")
        entry = parse_flow_file(path, key)
        if entry:
            flows.append(entry)

    return RasProject(
        path=prj_path,
        title=title,
        plans=plans,
        geometries=geometries,
        flows=flows,
        current_plan=current_plan,
        dss_files=dss_files,
    )
