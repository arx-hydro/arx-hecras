"""Data models for the PyQt6 GUI — plan table model + filter proxy."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)


@dataclass
class PlanRow:
    """One row in the plan table."""

    selected: bool = True
    key: str = ""  # e.g. "p01"
    title: str = ""
    geom: str = ""  # "g02: geometry_01"
    flow: str = ""  # "u01: flow_title"
    dss: str = ""  # comma-separated DSS file names
    progress: str = ""  # "—" / "42%" / "✓ 5s" / "✗ 3s"
    log: str = "View"
    is_current: bool = False  # bold rendering for current plan
    result_tag: str = ""  # "success" | "failure" | ""


COLUMNS = ["", "Plan", "Title", "Geometry", "Flow", "DSS Files", "Progress", "Log"]
_COL_COUNT = len(COLUMNS)

# Named column indices
COL_SEL = 0
COL_KEY = 1
COL_TITLE = 2
COL_GEOM = 3
COL_FLOW = 4
COL_DSS = 5
COL_PROGRESS = 6
COL_LOG = 7


class PlanTableModel(QAbstractTableModel):
    """Model backing the plan QTableView with native checkbox in column 0."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[PlanRow] = []

    # ── Public API ──

    def set_plans(self, rows: list[PlanRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def get_row(self, row: int) -> PlanRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def all_rows(self) -> list[PlanRow]:
        return self._rows

    def set_all_selected(self, selected: bool) -> None:
        for r in self._rows:
            r.selected = selected
        if self._rows:
            self.dataChanged.emit(
                self.index(0, COL_SEL),
                self.index(len(self._rows) - 1, COL_SEL),
                [Qt.ItemDataRole.CheckStateRole],
            )

    def toggle_selection(self, row: int) -> None:
        if 0 <= row < len(self._rows):
            self._rows[row].selected = not self._rows[row].selected
            idx = self.index(row, COL_SEL)
            self.dataChanged.emit(
                idx,
                idx,
                [Qt.ItemDataRole.CheckStateRole],
            )

    def update_progress(self, plan_key: str, text: str) -> None:
        for i, r in enumerate(self._rows):
            if r.key == plan_key:
                r.progress = text
                idx = self.index(i, COL_PROGRESS)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])
                break

    def update_result(self, plan_key: str, progress_text: str, tag: str) -> None:
        for i, r in enumerate(self._rows):
            if r.key == plan_key:
                r.progress = progress_text
                r.result_tag = tag
                left = self.index(i, 0)
                right = self.index(i, _COL_COUNT - 1)
                self.dataChanged.emit(
                    left, right, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole]
                )
                break

    # ── QAbstractTableModel interface ──

    def rowCount(self, parent=None):  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent=None):  # noqa: N802
        return _COL_COUNT

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.CheckStateRole and col == COL_SEL:
            return Qt.CheckState.Checked if row.selected else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_SEL:
                return None  # checkbox handles display
            if col == COL_KEY:
                return row.key
            if col == COL_TITLE:
                return row.title
            if col == COL_GEOM:
                return row.geom
            if col == COL_FLOW:
                return row.flow
            if col == COL_DSS:
                return row.dss
            if col == COL_PROGRESS:
                return row.progress
            if col == COL_LOG:
                return row.log
            return None

        if role == Qt.ItemDataRole.FontRole:
            if row.is_current:
                from PyQt6.QtGui import QFont

                font = QFont()
                font.setBold(True)
                return font
            return None

        if role == Qt.ItemDataRole.ForegroundRole:
            if row.result_tag == "success":
                from PyQt6.QtGui import QColor

                return QColor("#228B22")
            if row.result_tag == "failure":
                from PyQt6.QtGui import QColor

                return QColor("#8B0000")
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_SEL, COL_KEY, COL_PROGRESS, COL_LOG):
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        if index.isValid() and role == Qt.ItemDataRole.CheckStateRole and index.column() == COL_SEL:
            self._rows[index.row()].selected = value == Qt.CheckState.Checked.value
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return True
        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < _COL_COUNT
        ):
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if index.column() == COL_SEL:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class PlanFilterProxy(QSortFilterProxyModel):
    """Filter proxy for the plan table — filters by title, geom, flow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_title = ""
        self._filter_geom = ""
        self._filter_flow = ""

    def set_filters(self, title: str = "", geom: str = "", flow: str = "") -> None:
        self._filter_title = title.lower()
        self._filter_geom = geom.lower()
        self._filter_flow = flow.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return True

        def _get(col: int) -> str:
            idx = model.index(source_row, col, source_parent)
            val = model.data(idx, Qt.ItemDataRole.DisplayRole)
            return str(val).lower() if val else ""

        if self._filter_title and self._filter_title not in _get(COL_TITLE):
            return False
        if self._filter_geom and self._filter_geom not in _get(COL_GEOM):
            return False
        return not (self._filter_flow and self._filter_flow not in _get(COL_FLOW))
