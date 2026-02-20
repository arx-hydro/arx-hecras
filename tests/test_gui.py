"""Tests for gui.py pure helper functions (no QApplication needed)."""

from __future__ import annotations

import pytest

from hecras_runner.gui import build_plan_rows, format_result_progress, plan_rows_to_jobs
from hecras_runner.models import PlanRow
from hecras_runner.parser import FlowEntry, GeomEntry, PlanEntry, RasProject
from hecras_runner.runner import SimulationResult

# ── build_plan_rows ──


class TestBuildPlanRows:
    def test_basic_conversion(self):
        project = RasProject(
            title="Test Project",
            path="test.prj",
            current_plan="p01",
            plans=[
                PlanEntry(key="p01", title="plan_01", geom_ref="g01", flow_ref="u01"),
                PlanEntry(key="p02", title="plan_02", geom_ref="g01", flow_ref="u02"),
            ],
            geometries=[GeomEntry(key="g01", title="geom_01")],
            flows=[
                FlowEntry(key="u01", title="flow_01", dss_files=["input.dss"]),
                FlowEntry(key="u02", title="flow_02", dss_files=[]),
            ],
        )
        rows = build_plan_rows(project)

        assert len(rows) == 2
        assert rows[0].key == "p01"
        assert rows[0].title == "plan_01"
        assert rows[0].geom == "g01: geom_01"
        assert rows[0].flow == "u01: flow_01"
        assert rows[0].dss == "input.dss"
        assert rows[0].selected is True
        assert rows[0].progress == "\u2014"

    def test_current_plan_marked(self):
        project = RasProject(
            title="Test",
            path="t.prj",
            current_plan="p02",
            plans=[
                PlanEntry(key="p01", title="plan_01", geom_ref="g01", flow_ref="u01"),
                PlanEntry(key="p02", title="plan_02", geom_ref="g01", flow_ref="u01"),
            ],
            geometries=[GeomEntry(key="g01", title="geom_01")],
            flows=[FlowEntry(key="u01", title="flow_01", dss_files=[])],
        )
        rows = build_plan_rows(project)
        assert rows[0].is_current is False
        assert rows[1].is_current is True

    def test_missing_geom_shows_question_mark(self):
        project = RasProject(
            title="Test",
            path="t.prj",
            current_plan="p01",
            plans=[PlanEntry(key="p01", title="plan_01", geom_ref="g99", flow_ref="u01")],
            geometries=[],
            flows=[FlowEntry(key="u01", title="flow_01", dss_files=[])],
        )
        rows = build_plan_rows(project)
        assert rows[0].geom == "g99: ?"

    def test_missing_flow_uses_ref(self):
        project = RasProject(
            title="Test",
            path="t.prj",
            current_plan="p01",
            plans=[PlanEntry(key="p01", title="plan_01", geom_ref="g01", flow_ref="u99")],
            geometries=[GeomEntry(key="g01", title="geom_01")],
            flows=[],
        )
        rows = build_plan_rows(project)
        assert rows[0].flow == "u99"
        assert rows[0].dss == ""

    def test_empty_project(self):
        project = RasProject(
            title="Empty",
            path="t.prj",
            current_plan="",
            plans=[],
            geometries=[],
            flows=[],
        )
        assert build_plan_rows(project) == []


# ── format_result_progress ──


class TestFormatResultProgress:
    @pytest.mark.parametrize(
        ("elapsed", "success", "expected_text", "expected_tag"),
        [
            (5.0, True, "Complete (5s)", "success"),
            (125.0, True, "Complete (2m5s)", "success"),
            (3.0, False, "Failed (3s)", "failure"),
            (90.0, False, "Failed (1m30s)", "failure"),
        ],
        ids=["short-success", "long-success", "short-failure", "long-failure"],
    )
    def test_formatting(self, elapsed, success, expected_text, expected_tag):
        result = SimulationResult(
            plan_name="plan01", plan_suffix="01", success=success, elapsed_seconds=elapsed
        )
        text, tag = format_result_progress(result)
        assert text == expected_text
        assert tag == expected_tag


# ── plan_rows_to_jobs ──


class TestPlanRowsToJobs:
    def test_conversion(self):
        rows = [
            PlanRow(key="p01", title="plan_01"),
            PlanRow(key="p03", title="plan_03"),
        ]
        jobs = plan_rows_to_jobs(rows)
        assert len(jobs) == 2
        assert jobs[0].plan_name == "plan_01"
        assert jobs[0].plan_suffix == "01"
        assert jobs[0].dss_path is None
        assert jobs[1].plan_name == "plan_03"
        assert jobs[1].plan_suffix == "03"

    def test_empty_list(self):
        assert plan_rows_to_jobs([]) == []
