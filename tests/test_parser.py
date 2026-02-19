"""Tests for hecras_runner.parser."""

from __future__ import annotations

from pathlib import Path

from hecras_runner.parser import (
    FlowEntry,
    GeomEntry,
    PlanEntry,
    parse_flow_file,
    parse_geom_file,
    parse_plan_file,
    parse_project,
)


class TestParseSmallProject:
    """Parse the real small_project_01 project."""

    def test_project_title(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        assert proj.title == "small_project_01"

    def test_four_plans(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        assert len(proj.plans) == 4
        keys = [p.key for p in proj.plans]
        assert keys == ["p01", "p02", "p03", "p04"]

    def test_plan_titles(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        titles = [p.title for p in proj.plans]
        assert titles == ["plan_01", "plan_02", "plan_03", "plan_04"]

    def test_one_geometry(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        assert len(proj.geometries) == 1
        assert proj.geometries[0].key == "g02"
        assert proj.geometries[0].title == "geometry_01"

    def test_four_flows(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        assert len(proj.flows) == 4
        keys = [f.key for f in proj.flows]
        assert keys == ["u01", "u02", "u03", "u04"]

    def test_plan_cross_references(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        for plan in proj.plans:
            assert plan.geom_ref == "g02"
        assert proj.plans[0].flow_ref == "u01"
        assert proj.plans[2].flow_ref == "u03"

    def test_flow_dss_files(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        # u01 has relative DSS path
        u01 = next(f for f in proj.flows if f.key == "u01")
        assert "100yCC_2024.dss" in u01.dss_files
        # u03 has absolute DSS path
        u03 = next(f for f in proj.flows if f.key == "u03")
        assert any("100yCC_2024.dss" in d for d in u03.dss_files)

    def test_current_plan(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        assert proj.current_plan == "p01"

    def test_project_dss_files(self, prtest1_prj: Path):
        proj = parse_project(str(prtest1_prj))
        assert "100yCC_2024.dss" in proj.dss_files


class TestParseSynthetic:
    """Parse the minimal synthetic project."""

    def test_synthetic_project(self, synthetic_prj: Path):
        proj = parse_project(str(synthetic_prj))
        assert proj.title == "Minimal"
        assert len(proj.plans) == 1
        assert proj.plans[0].title == "Test Plan"
        assert len(proj.geometries) == 1
        assert proj.geometries[0].title == "Test Geom"
        assert len(proj.flows) == 1
        assert proj.flows[0].title == "Test Flow"
        assert proj.flows[0].dss_files == ["test.dss", "other.dss"]


class TestMissingFiles:
    """Resilience when referenced files are missing."""

    def test_missing_plan_file(self, tmp_path: Path):
        # Create a .prj that references a non-existent plan
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=Test\nPlan File=p99\n")
        proj = parse_project(str(prj))
        assert proj.title == "Test"
        assert len(proj.plans) == 0

    def test_missing_geom_file(self, tmp_path: Path):
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=Test\nGeom File=g99\n")
        proj = parse_project(str(prj))
        assert len(proj.geometries) == 0

    def test_missing_flow_file(self, tmp_path: Path):
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=Test\nUnsteady File=u99\n")
        proj = parse_project(str(prj))
        assert len(proj.flows) == 0


class TestEncodingFallback:
    """Test encoding fallback for non-UTF-8 files."""

    def test_latin1_file(self, tmp_path: Path):
        # Write a file with latin-1 encoding
        prj = tmp_path / "test.prj"
        prj.write_bytes("Proj Title=T\xe9st\n".encode("latin-1"))
        proj = parse_project(str(prj))
        assert proj.title == "Tést"


class TestIndividualParsers:
    """Test parse_plan_file, parse_geom_file, parse_flow_file directly."""

    def test_parse_plan_file(self, tmp_path: Path):
        p = tmp_path / "test.p01"
        p.write_text("Plan Title=My Plan\nGeom File=g02\nFlow File=u03\n")
        entry = parse_plan_file(str(p), "p01")
        assert entry == PlanEntry(key="p01", title="My Plan", geom_ref="g02", flow_ref="u03")

    def test_parse_geom_file(self, tmp_path: Path):
        g = tmp_path / "test.g01"
        g.write_text("Geom Title=My Geom\n")
        entry = parse_geom_file(str(g), "g01")
        assert entry == GeomEntry(key="g01", title="My Geom")

    def test_parse_flow_file(self, tmp_path: Path):
        u = tmp_path / "test.u01"
        u.write_text("Flow Title=My Flow\nDSS File=a.dss\nDSS File=b.dss\nDSS File=a.dss\n")
        entry = parse_flow_file(str(u), "u01")
        assert entry == FlowEntry(key="u01", title="My Flow", dss_files=["a.dss", "b.dss"])

    def test_parse_nonexistent_returns_none(self):
        assert parse_plan_file("/nonexistent/path.p01", "p01") is None
        assert parse_geom_file("/nonexistent/path.g01", "g01") is None
        assert parse_flow_file("/nonexistent/path.u01", "u01") is None
