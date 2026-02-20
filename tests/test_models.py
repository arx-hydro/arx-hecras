"""Tests for hecras_runner.models (PlanRow, PlanTableModel, PlanFilterProxy)."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from hecras_runner.models import (
    COL_DSS,
    COL_FLOW,
    COL_GEOM,
    COL_KEY,
    COL_LOG,
    COL_PROGRESS,
    COL_SEL,
    COL_TITLE,
    COLUMNS,
    PlanFilterProxy,
    PlanRow,
    PlanTableModel,
)

# ── PlanRow ──


class TestPlanRow:
    def test_defaults(self):
        row = PlanRow()
        assert row.selected is True
        assert row.key == ""
        assert row.title == ""
        assert row.geom == ""
        assert row.flow == ""
        assert row.dss == ""
        assert row.progress == ""
        assert row.log == "View"
        assert row.is_current is False
        assert row.result_tag == ""

    def test_custom_values(self):
        row = PlanRow(
            selected=False,
            key="p02",
            title="plan_02",
            geom="g01: geom_01",
            flow="u01: flow_01",
            dss="input.dss",
            progress="42%",
            log="View",
            is_current=True,
            result_tag="success",
        )
        assert row.key == "p02"
        assert row.is_current is True
        assert row.result_tag == "success"


# ── PlanTableModel ──


class TestPlanTableModel:
    @pytest.fixture
    def model(self, qapp):
        return PlanTableModel()

    @pytest.fixture
    def sample_rows(self):
        return [
            PlanRow(key="p01", title="plan_01", geom="g01: geom_01", flow="u01: flow_01"),
            PlanRow(
                key="p02",
                title="plan_02",
                geom="g02: geom_02",
                flow="u02: flow_02",
                is_current=True,
            ),
            PlanRow(key="p03", title="plan_03", geom="g01: geom_01", flow="u01: flow_01"),
        ]

    def test_empty_model(self, model):
        assert model.rowCount() == 0
        assert model.columnCount() == len(COLUMNS)

    def test_set_plans(self, model, sample_rows):
        model.set_plans(sample_rows)
        assert model.rowCount() == 3

    def test_get_row(self, model, sample_rows):
        model.set_plans(sample_rows)
        assert model.get_row(0).key == "p01"
        assert model.get_row(2).key == "p03"
        assert model.get_row(5) is None
        assert model.get_row(-1) is None

    def test_all_rows(self, model, sample_rows):
        model.set_plans(sample_rows)
        rows = model.all_rows()
        assert len(rows) == 3
        assert rows[0].key == "p01"

    def test_display_role(self, model, sample_rows):
        model.set_plans(sample_rows)
        # Column 0 (checkbox) returns None for display
        assert model.data(model.index(0, COL_SEL), Qt.ItemDataRole.DisplayRole) is None
        assert model.data(model.index(0, COL_KEY), Qt.ItemDataRole.DisplayRole) == "p01"
        assert model.data(model.index(0, COL_TITLE), Qt.ItemDataRole.DisplayRole) == "plan_01"
        assert model.data(model.index(0, COL_GEOM)) == "g01: geom_01"
        assert model.data(model.index(0, COL_FLOW)) == "u01: flow_01"
        assert model.data(model.index(0, COL_DSS)) == ""
        assert model.data(model.index(0, COL_PROGRESS)) == ""
        assert model.data(model.index(0, COL_LOG)) == "View"

    def test_checkstate_role(self, model, sample_rows):
        model.set_plans(sample_rows)
        assert (
            model.data(model.index(0, COL_SEL), Qt.ItemDataRole.CheckStateRole)
            == Qt.CheckState.Checked
        )

    def test_font_role_current_plan(self, model, sample_rows):
        model.set_plans(sample_rows)
        # Row 1 is current — should return bold font
        font = model.data(model.index(1, COL_TITLE), Qt.ItemDataRole.FontRole)
        assert font is not None
        assert font.bold() is True
        # Row 0 is not current — should return None
        assert model.data(model.index(0, COL_TITLE), Qt.ItemDataRole.FontRole) is None

    def test_foreground_role_success(self, model, sample_rows):
        model.set_plans(sample_rows)
        model.update_result("p01", "Complete (5s)", "success")
        color = model.data(model.index(0, COL_TITLE), Qt.ItemDataRole.ForegroundRole)
        assert color is not None
        assert color.name() == "#228b22"

    def test_foreground_role_failure(self, model, sample_rows):
        model.set_plans(sample_rows)
        model.update_result("p01", "Failed (3s)", "failure")
        color = model.data(model.index(0, COL_TITLE), Qt.ItemDataRole.ForegroundRole)
        assert color is not None
        assert color.name() == "#8b0000"

    def test_foreground_role_none(self, model, sample_rows):
        model.set_plans(sample_rows)
        assert model.data(model.index(0, COL_TITLE), Qt.ItemDataRole.ForegroundRole) is None

    def test_alignment_role(self, model, sample_rows):
        model.set_plans(sample_rows)
        # Centered columns
        for col in (COL_SEL, COL_KEY, COL_PROGRESS, COL_LOG):
            align = model.data(model.index(0, col), Qt.ItemDataRole.TextAlignmentRole)
            assert align == Qt.AlignmentFlag.AlignCenter
        # Left-aligned columns
        align = model.data(model.index(0, COL_TITLE), Qt.ItemDataRole.TextAlignmentRole)
        assert align == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    def test_toggle_selection(self, model, sample_rows):
        model.set_plans(sample_rows)
        assert model.all_rows()[0].selected is True
        model.toggle_selection(0)
        assert model.all_rows()[0].selected is False
        model.toggle_selection(0)
        assert model.all_rows()[0].selected is True

    def test_toggle_selection_out_of_range(self, model, sample_rows):
        model.set_plans(sample_rows)
        model.toggle_selection(99)  # should not raise

    def test_set_all_selected(self, model, sample_rows):
        model.set_plans(sample_rows)
        model.set_all_selected(False)
        assert all(not r.selected for r in model.all_rows())
        model.set_all_selected(True)
        assert all(r.selected for r in model.all_rows())

    def test_update_progress(self, model, sample_rows):
        model.set_plans(sample_rows)
        model.update_progress("p02", "42%")
        assert model.all_rows()[1].progress == "42%"

    def test_update_result(self, model, sample_rows):
        model.set_plans(sample_rows)
        model.update_result("p01", "Complete (5s)", "success")
        row = model.all_rows()[0]
        assert row.progress == "Complete (5s)"
        assert row.result_tag == "success"

    def test_header_data(self, model):
        for i, name in enumerate(COLUMNS):
            assert model.headerData(i, Qt.Orientation.Horizontal) == name
        # Vertical header returns None
        assert model.headerData(0, Qt.Orientation.Vertical) is None

    def test_flags_checkbox_column(self, model, sample_rows):
        model.set_plans(sample_rows)
        flags = model.flags(model.index(0, COL_SEL))
        assert flags & Qt.ItemFlag.ItemIsUserCheckable

    def test_flags_regular_column(self, model, sample_rows):
        model.set_plans(sample_rows)
        flags = model.flags(model.index(0, COL_TITLE))
        assert flags & Qt.ItemFlag.ItemIsEnabled
        assert flags & Qt.ItemFlag.ItemIsSelectable

    def test_set_data_checkbox(self, model, sample_rows):
        model.set_plans(sample_rows)
        idx = model.index(0, COL_SEL)
        result = model.setData(idx, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
        assert result is True
        assert model.all_rows()[0].selected is False

    def test_set_data_wrong_role(self, model, sample_rows):
        model.set_plans(sample_rows)
        idx = model.index(0, COL_TITLE)
        result = model.setData(idx, "new", Qt.ItemDataRole.EditRole)
        assert result is False

    def test_invalid_index(self, model):
        from PyQt6.QtCore import QModelIndex

        assert model.data(QModelIndex(), Qt.ItemDataRole.DisplayRole) is None


# ── PlanFilterProxy ──


class TestPlanFilterProxy:
    @pytest.fixture
    def proxy_with_data(self, qapp):
        model = PlanTableModel()
        model.set_plans(
            [
                PlanRow(key="p01", title="plan_01", geom="g01: geom_01", flow="u01: flow_01"),
                PlanRow(key="p02", title="plan_02", geom="g02: geom_02", flow="u02: flow_02"),
                PlanRow(key="p03", title="another_plan", geom="g01: geom_01", flow="u01: flow_01"),
            ]
        )
        proxy = PlanFilterProxy()
        proxy.setSourceModel(model)
        return proxy

    def test_no_filter_shows_all(self, proxy_with_data):
        assert proxy_with_data.rowCount() == 3

    def test_filter_by_title(self, proxy_with_data):
        proxy_with_data.set_filters(title="plan_01")
        assert proxy_with_data.rowCount() == 1

    def test_filter_by_geom(self, proxy_with_data):
        proxy_with_data.set_filters(geom="g01")
        assert proxy_with_data.rowCount() == 2

    def test_filter_by_flow(self, proxy_with_data):
        proxy_with_data.set_filters(flow="flow_02")
        assert proxy_with_data.rowCount() == 1

    def test_combined_filters(self, proxy_with_data):
        proxy_with_data.set_filters(title="plan", geom="g01")
        assert proxy_with_data.rowCount() == 2  # plan_01 + another_plan, both g01

    def test_case_insensitive(self, proxy_with_data):
        proxy_with_data.set_filters(title="PLAN_01")
        assert proxy_with_data.rowCount() == 1

    def test_clear_filters(self, proxy_with_data):
        proxy_with_data.set_filters(title="plan_01")
        assert proxy_with_data.rowCount() == 1
        proxy_with_data.set_filters()
        assert proxy_with_data.rowCount() == 3

    def test_no_match(self, proxy_with_data):
        proxy_with_data.set_filters(title="nonexistent")
        assert proxy_with_data.rowCount() == 0
