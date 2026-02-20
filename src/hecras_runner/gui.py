"""PyQt6 GUI for HEC-RAS parallel runner."""

from __future__ import annotations

import contextlib
import importlib
import multiprocessing
import os
import queue
import sys
import threading
import time
import traceback

from PyQt6.QtCore import (
    QModelIndex,
    QObject,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hecras_runner import __version__
from hecras_runner.discovery import (
    check_hecras_installed,
    find_hecras_exe,
    find_hecras_processes,
    open_parent_instance,
    refresh_parent_instance,
)
from hecras_runner.models import (
    COL_DSS,
    COL_FLOW,
    COL_GEOM,
    COL_KEY,
    COL_LOG,
    COL_PROGRESS,
    COL_SEL,
    COL_TITLE,
    PlanFilterProxy,
    PlanRow,
    PlanTableModel,
)
from hecras_runner.parser import RasProject, parse_project
from hecras_runner.runner import (
    ProgressMessage,
    SimulationJob,
    SimulationResult,
    run_simulations,
)
from hecras_runner.settings import load_settings, save_settings
from hecras_runner.version_check import VersionInfo, check_for_update

# ── Thread-safe log emitter ──


class LogEmitter(QObject):
    """Emits log messages from any thread to the GUI thread via signal."""

    message = pyqtSignal(str)

    def log(self, text: str) -> None:
        self.message.emit(text)


# ── Filtered table view ──


class FilteredTableView(QTableView):
    """QTableView with inline filter inputs embedded below the header row.

    The filter row resizes with columns and scrolls with the table content.
    """

    _FILTER_HEIGHT = 24

    def __init__(self, filter_columns: dict[int, str], parent=None):
        """Create a table view with filter inputs for specified columns.

        Parameters
        ----------
        filter_columns : dict[int, str]
            Mapping of column index to placeholder text.
        """
        self._in_geom_update = False
        super().__init__(parent)
        self._filter_edits: dict[int, QLineEdit] = {}
        self._filter_bar = QWidget(self)
        self._filter_bar.setStyleSheet(
            "background-color: #f0f0f0; border-bottom: 1px solid #d0d0d0;"
        )

        for col, placeholder in filter_columns.items():
            edit = QLineEdit(self._filter_bar)
            edit.setPlaceholderText(placeholder)
            edit.setProperty("class", "columnFilter")
            self._filter_edits[col] = edit

        self.setViewportMargins(0, self._FILTER_HEIGHT, 0, 0)

        hdr = self.horizontalHeader()
        hdr.sectionResized.connect(lambda *_: self._reposition_filters())
        hdr.geometriesChanged.connect(self._reposition_filters)

    def filter_edit(self, col: int) -> QLineEdit | None:
        """Return the QLineEdit for the given column, or None."""
        return self._filter_edits.get(col)

    def updateGeometries(self):  # noqa: N802
        super().updateGeometries()
        # Re-apply viewport margins after QTableView layout (it may reset them)
        if not self._in_geom_update:
            self._in_geom_update = True
            self.setViewportMargins(0, self._FILTER_HEIGHT, 0, 0)
            self._in_geom_update = False
        self._reposition_filters()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._reposition_filters()

    def scrollContentsBy(self, dx, dy):  # noqa: N802
        super().scrollContentsBy(dx, dy)
        if dx:
            self._reposition_filters()

    def _reposition_filters(self) -> None:
        hdr = self.horizontalHeader()
        if not hdr or not hdr.count():
            return
        vp = self.viewport()
        self._filter_bar.setGeometry(
            vp.x(),
            vp.y() - self._FILTER_HEIGHT,
            vp.width(),
            self._FILTER_HEIGHT,
        )
        offset = hdr.offset()
        for col, edit in self._filter_edits.items():
            x = hdr.sectionPosition(col) - offset
            w = hdr.sectionSize(col)
            edit.setGeometry(x, 0, w, self._FILTER_HEIGHT)


# ── Inline stylesheet ──

_STYLESHEET = """
QMainWindow {
    background-color: #fafafa;
    font-family: "Segoe UI";
}
QGroupBox {
    font-weight: bold;
    border: 1px solid #cccccc;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QTableView {
    gridline-color: #e0e0e0;
    selection-background-color: #d9d9d9;
    alternate-background-color: #fafafa;
}
QTableView::item {
    padding: 2px 4px;
}
QHeaderView::section {
    background-color: #f0f0f0;
    border: none;
    border-bottom: 2px solid #1a1a1a;
    padding: 4px;
    font-weight: bold;
}
QPlainTextEdit {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9pt;
    background-color: #1e1e1e;
    color: #dcdcdc;
    border: 1px solid #cccccc;
}
QPushButton#runBtn {
    background-color: #1a1a1a;
    color: white;
    font-weight: bold;
    font-size: 10pt;
    padding: 6px 16px;
    border-radius: 4px;
    border: none;
    max-width: 200px;
}
QPushButton#runBtn:hover {
    background-color: #333333;
}
QPushButton#runBtn:disabled {
    background-color: #cccccc;
    color: #888888;
}
QPushButton#workerBtn {
    font-weight: bold;
    font-size: 10pt;
    padding: 4px 16px;
    border-radius: 4px;
}
QTabWidget::pane {
    border: 1px solid #cccccc;
}
QTabBar::tab {
    padding: 6px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: white;
    border-bottom: 2px solid #1a1a1a;
}
QTabBar::tab:!selected {
    background: #e0e0e0;
}
QLineEdit.columnFilter {
    border: 1px solid #d0d0d0;
    padding: 1px 3px;
    font-size: 8pt;
    font-weight: normal;
}
"""


# ── Plan Log Dialog ──


class PlanLogDialog(QDialog):
    """Shows filtered log messages for a specific plan."""

    def __init__(self, plan_title: str, messages: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Log \u2014 {plan_title}")
        self.resize(650, 420)

        layout = QVBoxLayout(self)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlainText("\n".join(messages) if messages else "(no log messages)")
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._copy_btn = copy_btn

    def _copy(self) -> None:
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._text.toPlainText())
        self._copy_btn.setText("Copied!")
        QTimer.singleShot(1500, lambda: self._copy_btn.setText("Copy"))


# ── Database Connection Dialog ──


class DbConnectionDialog(QDialog):
    """Modal dialog for DB connection settings + test."""

    test_requested = pyqtSignal()
    save_requested = pyqtSignal()

    def __init__(
        self,
        host: str,
        port: str,
        dbname: str,
        user: str,
        password: str,
        share_path: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Database Connection")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.host_edit = QLineEdit(host)
        self.port_edit = QLineEdit(port)
        self.dbname_edit = QLineEdit(dbname)
        self.user_edit = QLineEdit(user)
        self.password_edit = QLineEdit(password)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.share_edit = QLineEdit(share_path)

        form.addRow("Host:", self.host_edit)
        form.addRow("Port:", self.port_edit)
        form.addRow("Database:", self.dbname_edit)
        form.addRow("User:", self.user_edit)
        form.addRow("Password:", self.password_edit)

        # Share path with browse
        share_row = QHBoxLayout()
        share_row.addWidget(self.share_edit)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self._browse_share)
        share_row.addWidget(browse_btn)
        form.addRow("Share Path:", share_row)

        layout.addLayout(form)

        self.status_label = QLabel("Not connected")
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self.test_requested.emit)
        btn_row.addWidget(test_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: (self.save_requested.emit(), self.accept()))
        btn_row.addWidget(save_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _browse_share(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Network Share")
        if path:
            self.share_edit.setText(path)

    def values(self) -> dict[str, str]:
        return {
            "host": self.host_edit.text(),
            "port": self.port_edit.text(),
            "dbname": self.dbname_edit.text(),
            "user": self.user_edit.text(),
            "password": self.password_edit.text(),
            "share_path": self.share_edit.text(),
        }


# ── Icon path ──


def _icon_path() -> str:
    """Resolve path to arx_icon.png (works in dev and PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    return os.path.join(base, "resources", "arx_icon.png")


# ── Pure helpers (testable without QApplication) ──


def build_plan_rows(project: RasProject) -> list[PlanRow]:
    """Convert a parsed RasProject into PlanRow list for the table model."""
    geom_map = {g.key: g.title for g in project.geometries}
    flow_map = {f.key: f for f in project.flows}

    rows: list[PlanRow] = []
    for plan in project.plans:
        geom_label = f"{plan.geom_ref}: {geom_map.get(plan.geom_ref, '?')}"
        flow_entry = flow_map.get(plan.flow_ref)
        flow_label = f"{plan.flow_ref}: {flow_entry.title}" if flow_entry else plan.flow_ref
        dss_label = ", ".join(flow_entry.dss_files) if flow_entry else ""

        rows.append(
            PlanRow(
                selected=True,
                key=plan.key,
                title=plan.title,
                geom=geom_label,
                flow=flow_label,
                dss=dss_label,
                progress="\u2014",  # em dash
                log="View",
                is_current=(plan.key == project.current_plan),
            )
        )
    return rows


def format_result_progress(result: SimulationResult) -> tuple[str, str]:
    """Return (progress_text, tag) for a completed simulation result.

    tag is "success" or "failure".
    """
    r_secs = int(result.elapsed_seconds)
    r_mins, r_secs_rem = divmod(r_secs, 60)
    elapsed_str = f"{r_mins}m{r_secs_rem}s" if r_mins else f"{r_secs_rem}s"

    if result.success:
        return f"Complete ({elapsed_str})", "success"
    return f"Failed ({elapsed_str})", "failure"


def plan_rows_to_jobs(rows: list[PlanRow]) -> list[SimulationJob]:
    """Convert selected PlanRows into SimulationJob list for the runner."""
    return [
        SimulationJob(
            plan_name=r.title,
            plan_suffix=r.key[1:],
            dss_path=None,
        )
        for r in rows
    ]


# ── Main Window ──


class MainWindow(QMainWindow):
    """Main application window."""

    # Signals for cross-thread communication
    _log_signal = pyqtSignal(str)
    _db_result_signal = pyqtSignal(bool, str)  # (success, detail_message)
    _version_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ARX \u2014 HEC-RAS Parallel Runner v{__version__}")
        self.resize(1200, 780)

        # State
        self.project_path = ""
        self.project: RasProject | None = None
        self._plan_progress: dict[str, float] = {}
        self._plan_results: dict[str, SimulationResult] = {}
        self._log_messages: list[str] = []
        self.progress_queue: multiprocessing.Queue | None = None

        # Parent HEC-RAS instance (COM)
        self._parent_ras: object | None = None
        self._com_initialized = False

        # Network state
        self._settings = load_settings()
        self._db_client: object | None = None
        self._worker_info: object | None = None
        self._worker_polling_active = False
        self._distributed_batch_id: str | None = None
        self._worker_mode_active = False

        # Version check result (cached for About dialog)
        self._update_info: VersionInfo | None = None

        # Log emitter for thread-safe logging
        self._log_emitter = LogEmitter()
        self._log_emitter.message.connect(self._append_log)

        # Cross-thread signals
        self._log_signal.connect(self._append_log)
        self._db_result_signal.connect(self._on_db_result)
        self._version_signal.connect(self._on_version_check_result)

        self._build_ui()
        self._build_menu()

        # Progress queue drain timer
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._drain_progress_queue)
        self._progress_timer.start(200)

        # Version check
        self._check_for_updates()

    # ── UI Construction ──

    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        open_act = QAction("&Open Project...", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._browse_project)
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        exit_act = QAction("E&xit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        help_menu = menu.addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _show_about(self) -> None:
        text = (
            f"<h3>HEC-RAS Parallel Runner</h3>"
            f"<p>Version: <b>{__version__}</b></p>"
            f"<p>Run multiple HEC-RAS simulation plans in parallel.</p>"
            f"<p>Arx Engineering</p>"
            f"<hr>"
        )
        if self._update_info is not None:
            text += (
                f"<p style='color: #0078d4;'>"
                f"Update available: <b>v{self._update_info.latest_version}</b></p>"
            )
            if self._update_info.release_notes:
                text += f"<p>{self._update_info.release_notes}</p>"
            if self._update_info.download_url:
                text += (
                    f"<p>Download: <a href='{self._update_info.download_url}'>"
                    f"{self._update_info.download_url}</a></p>"
                )
        else:
            text += "<p style='color: green;'>You are running the latest version.</p>"

        url = self._settings.update_url
        text += f"<p style='color: gray; font-size: 9pt;'>Update URL: {url}</p>"

        msg = QMessageBox(self)
        msg.setWindowTitle("About")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(text)
        msg.exec()

    def _build_ui(self) -> None:
        self.setStyleSheet(_STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # Title row with logo
        title_row = QHBoxLayout()
        title_row.addStretch()
        icon_file = _icon_path()
        if os.path.isfile(icon_file):
            logo_label = QLabel()
            logo_label.setPixmap(
                QPixmap(icon_file).scaled(
                    32,
                    32,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            title_row.addWidget(logo_label)
        title_label = QLabel("ARX \u2014 HEC-RAS Parallel Runner")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_row.addWidget(title_label)
        title_row.addStretch()
        main_layout.addLayout(title_row)

        # Project file row
        proj_row = QHBoxLayout()
        proj_row.addWidget(QLabel("Project (.prj):"))
        self._proj_edit = QLineEdit()
        self._proj_edit.setPlaceholderText("Browse or enter path to .prj file")
        proj_row.addWidget(self._proj_edit, stretch=1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_project)
        proj_row.addWidget(browse_btn)
        main_layout.addLayout(proj_row)

        # Splitter: left (tabs) | right (log)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._splitter, stretch=1)

        # Left pane: tab widget
        self._tabs = QTabWidget()
        self._splitter.addWidget(self._tabs)

        local_tab = QWidget()
        self._build_local_tab(local_tab)
        self._tabs.addTab(local_tab, "Local")

        network_tab = QWidget()
        self._build_network_tab(network_tab)
        self._tabs.addTab(network_tab, "Network")

        # Right pane: progress + log (no status label — #2)
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(
            "font-size: 10pt; font-weight: bold; padding: 4px; color: #1a1a1a;"
        )
        right_layout.addWidget(self._status_label)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Execution Log"))
        self._copy_log_btn = QPushButton("Copy")
        self._copy_log_btn.setFixedWidth(60)
        self._copy_log_btn.clicked.connect(self._copy_log_to_clipboard)
        log_header.addStretch()
        log_header.addWidget(self._copy_log_btn)
        right_layout.addLayout(log_header)

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        right_layout.addWidget(self._log_text)

        self._splitter.addWidget(right_pane)

        # Controls 75%, log 25%
        self._splitter.setSizes([900, 300])

        # Status bar
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Ready")

    # ── Local Tab ──

    def _build_local_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)

        # Plan selection group
        plan_group = QGroupBox("Plan Selection")
        plan_layout = QVBoxLayout(plan_group)

        # Loading indicator (thin indeterminate bar)
        self._plan_loading_bar = QProgressBar()
        self._plan_loading_bar.setRange(0, 0)  # indeterminate
        self._plan_loading_bar.setFixedHeight(4)
        self._plan_loading_bar.setTextVisible(False)
        self._plan_loading_bar.setVisible(False)
        plan_layout.addWidget(self._plan_loading_bar)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        deselect_btn = QPushButton("Deselect All")
        deselect_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(deselect_btn)
        select_btn = QPushButton("Select All")
        select_btn.clicked.connect(self._select_all)
        btn_row.addWidget(select_btn)
        plan_layout.addLayout(btn_row)

        # Plan table with inline filters
        self._plan_model = PlanTableModel()
        self._plan_proxy = PlanFilterProxy()
        self._plan_proxy.setSourceModel(self._plan_model)

        self._plan_table = FilteredTableView(
            filter_columns={
                COL_TITLE: "Filter title...",
                COL_GEOM: "Filter geometry...",
                COL_FLOW: "Filter flow...",
            }
        )
        self._plan_table.setModel(self._plan_proxy)
        self._plan_table.setAlternatingRowColors(True)
        self._plan_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._plan_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._plan_table.verticalHeader().setVisible(False)
        self._plan_table.horizontalHeader().setStretchLastSection(True)

        # Column widths
        hdr = self._plan_table.horizontalHeader()
        hdr.resizeSection(COL_SEL, 30)
        hdr.resizeSection(COL_KEY, 50)
        hdr.resizeSection(COL_TITLE, 130)
        hdr.resizeSection(COL_GEOM, 150)
        hdr.resizeSection(COL_FLOW, 150)
        hdr.resizeSection(COL_DSS, 180)
        hdr.resizeSection(COL_PROGRESS, 80)
        hdr.resizeSection(COL_LOG, 50)
        hdr.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)

        # Connect filter edits to apply_filter
        for col in (COL_TITLE, COL_GEOM, COL_FLOW):
            edit = self._plan_table.filter_edit(col)
            if edit:
                edit.textChanged.connect(self._apply_filter)

        self._plan_table.clicked.connect(self._on_table_click)
        plan_layout.addWidget(self._plan_table)

        layout.addWidget(plan_group, stretch=1)

        # Execution options
        options_group = QGroupBox("Execution Options")
        options_layout = QHBoxLayout(options_group)

        self._chk_parallel = QCheckBox("Run plans in parallel")
        self._chk_parallel.setChecked(True)
        options_layout.addWidget(self._chk_parallel)

        self._chk_cleanup = QCheckBox("Clean up temporary files")
        self._chk_cleanup.setChecked(True)
        options_layout.addWidget(self._chk_cleanup)

        self._chk_debug = QCheckBox("Debug mode (verbose)")
        options_layout.addWidget(self._chk_debug)

        options_layout.addStretch()
        layout.addWidget(options_group)

        # Execute button
        exec_row = QHBoxLayout()
        exec_row.addStretch()
        self._execute_btn = QPushButton("Run Local")
        self._execute_btn.setObjectName("runBtn")
        self._execute_btn.clicked.connect(self._execute)
        exec_row.addWidget(self._execute_btn)
        exec_row.addStretch()
        layout.addLayout(exec_row)

    # ── Network Tab ──

    def _build_network_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)

        # Enable toggle
        self._net_enabled_chk = QCheckBox("Enable Network Mode")
        self._net_enabled_chk.setChecked(self._settings.network.enabled)
        self._net_enabled_chk.toggled.connect(self._toggle_network_widgets)
        layout.addWidget(self._net_enabled_chk)

        # Connection row: traffic light + DB button + worker button
        conn_row = QHBoxLayout()

        # Traffic light
        self._traffic_light = QLabel()
        self._traffic_light.setFixedSize(20, 20)
        self._set_traffic_light("orange")
        conn_row.addWidget(self._traffic_light)

        self._db_btn = QPushButton("Database")
        self._db_btn.clicked.connect(self._show_db_connection_modal)
        conn_row.addWidget(self._db_btn)

        conn_row.addStretch()

        self._worker_btn = QPushButton("Worker")
        self._worker_btn.setObjectName("workerBtn")
        self._worker_btn.setCheckable(True)
        self._worker_btn.setStyleSheet(
            "QPushButton { background-color: #FFD699; }"
            "QPushButton:checked { background-color: #228B22; color: white; }"
        )
        self._worker_btn.clicked.connect(self._toggle_accept_jobs)
        conn_row.addWidget(self._worker_btn)

        layout.addLayout(conn_row)

        # Worker list
        worker_group = QGroupBox("Workers")
        worker_layout = QVBoxLayout(worker_group)

        self._worker_table = QTableWidget(0, 4)
        self._worker_table.setHorizontalHeaderLabels(["Host", "IP", "Status", "HEC-RAS"])
        self._worker_table.horizontalHeader().setStretchLastSection(True)
        self._worker_table.setColumnWidth(0, 120)
        self._worker_table.setColumnWidth(1, 110)
        self._worker_table.setColumnWidth(2, 80)
        self._worker_table.setColumnWidth(3, 60)
        self._worker_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._worker_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        worker_layout.addWidget(self._worker_table)

        self._worker_placeholder = QLabel("Connect to DB to see workers")
        self._worker_placeholder.setStyleSheet("color: gray;")
        self._worker_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        worker_layout.addWidget(self._worker_placeholder)

        layout.addWidget(worker_group, stretch=1)

        # Actions row
        action_row = QHBoxLayout()
        self._dist_execute_btn = QPushButton("Run Distributed")
        self._dist_execute_btn.setObjectName("runBtn")
        self._dist_execute_btn.clicked.connect(self._execute_distributed)
        action_row.addWidget(self._dist_execute_btn)

        self._save_settings_btn = QPushButton("Save Settings")
        self._save_settings_btn.clicked.connect(self._save_network_settings)
        action_row.addWidget(self._save_settings_btn)

        action_row.addStretch()
        layout.addLayout(action_row)

        # Apply initial enable/disable state
        self._toggle_network_widgets(self._settings.network.enabled)

    def _set_traffic_light(self, color: str) -> None:
        color_map = {
            "orange": "#CC8800",
            "red": "#CC0000",
            "yellow": "#CCCC00",
            "green": "#00AA00",
        }
        fill = color_map.get(color, color)
        self._traffic_light.setStyleSheet(
            f"background-color: {fill}; border-radius: 10px; border: 1px solid #888;"
        )

    def _toggle_network_widgets(self, enabled: bool = False) -> None:
        self._db_btn.setEnabled(enabled)
        self._worker_btn.setEnabled(enabled)
        self._dist_execute_btn.setEnabled(enabled)
        self._save_settings_btn.setEnabled(enabled)

    # ── Logging ──

    def log(self, message: str) -> None:
        """Thread-safe log method — can be called from any thread."""
        self._log_signal.emit(message)

    def _append_log(self, message: str) -> None:
        """Append a log message (must be called on GUI thread)."""
        if not self._chk_debug.isChecked() and message.startswith("[DEBUG]"):
            return
        formatted = f"{time.strftime('%H:%M:%S')} - {message}"
        self._log_messages.append(formatted)
        self._log_text.appendPlainText(formatted)

    def _copy_log_to_clipboard(self) -> None:
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._log_text.toPlainText())
        self._copy_log_btn.setText("Copied!")
        QTimer.singleShot(1500, lambda: self._copy_log_btn.setText("Copy"))

    # ── Progress queue drain ──

    def _drain_progress_queue(self) -> None:
        if self.progress_queue is None:
            return

        progress_updated = False
        try:
            while True:
                msg = self.progress_queue.get_nowait()
                if isinstance(msg, SimulationResult):
                    self._update_single_plan_result(msg)
                elif isinstance(msg, ProgressMessage):
                    self._plan_progress[msg.plan_suffix] = msg.fraction
                    progress_updated = True
        except (queue.Empty, EOFError):
            pass

        if not progress_updated:
            return

        # Update plan table progress column (only for plans still running)
        for suffix, fraction in self._plan_progress.items():
            plan_key = f"p{suffix}"
            if plan_key not in {f"p{r.plan_suffix}" for r in self._plan_results.values()}:
                pct = int(fraction * 100)
                self._plan_model.update_progress(plan_key, f"{pct}%")

    # ── Project loading ──

    def _browse_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select HEC-RAS Project File",
            "",
            "Project files (*.prj);;All files (*.*)",
        )
        if filename:
            self._proj_edit.setText(filename)
            self.project_path = filename
            self.log(f"Project selected: {filename}")
            self._load_project(filename)

    def _load_project(self, prj_path: str) -> None:
        self.setCursor(Qt.CursorShape.WaitCursor)
        self._statusbar.showMessage("Loading project...")
        self._plan_loading_bar.setVisible(True)
        QApplication.processEvents()

        try:
            self.project = parse_project(prj_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to parse project: {e}")
            return
        finally:
            self.unsetCursor()
            self._plan_loading_bar.setVisible(False)
            self._statusbar.showMessage("Ready")

        rows = build_plan_rows(self.project)
        self._plan_model.set_plans(rows)
        self._plan_results.clear()
        self._plan_progress.clear()
        self.log(f"Loaded {len(self.project.plans)} plans from {self.project.title}")

        self._check_hecras_running()

    # ── Plan table interaction ──

    def _on_table_click(self, proxy_index: QModelIndex) -> None:
        source_index = self._plan_proxy.mapToSource(proxy_index)
        col = source_index.column()
        row_num = source_index.row()

        if col == COL_LOG:
            plan_row = self._plan_model.get_row(row_num)
            if plan_row:
                self._show_plan_log(plan_row.key, plan_row.title)

    def _show_plan_log(self, plan_key: str, plan_title: str) -> None:
        filtered = [m for m in self._log_messages if plan_title in m or plan_key in m]
        dialog = PlanLogDialog(plan_title, filtered, parent=self)
        dialog.exec()

    def _select_all(self) -> None:
        self._plan_model.set_all_selected(True)

    def _deselect_all(self) -> None:
        self._plan_model.set_all_selected(False)

    def _apply_filter(self) -> None:
        title_edit = self._plan_table.filter_edit(COL_TITLE)
        geom_edit = self._plan_table.filter_edit(COL_GEOM)
        flow_edit = self._plan_table.filter_edit(COL_FLOW)
        self._plan_proxy.set_filters(
            title=title_edit.text() if title_edit else "",
            geom=geom_edit.text() if geom_edit else "",
            flow=flow_edit.text() if flow_edit else "",
        )

    # ── Parent HEC-RAS management ──

    def _ensure_com_initialized(self) -> None:
        if self._com_initialized:
            return
        try:
            pythoncom = importlib.import_module("pythoncom")
            pythoncom.CoInitialize()
            self._com_initialized = True
        except Exception:
            pass

    def _check_hecras_running(self) -> None:
        pids = find_hecras_processes()
        if pids:
            self.log(f"Detected {len(pids)} running HEC-RAS process(es).")
            self._statusbar.showMessage(f"HEC-RAS running (PID: {', '.join(str(p) for p in pids)})")
        else:
            answer = QMessageBox.question(
                self,
                "Open HEC-RAS?",
                "HEC-RAS is not currently running.\n\n"
                "Would you like to open this project in HEC-RAS?\n"
                "(Keeps it open so you can view results after simulation.)",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._open_parent_hecras()

    def _open_parent_hecras(self) -> None:
        self._ensure_com_initialized()
        try:
            self._parent_ras = open_parent_instance(self.project_path, log=self.log)
            self._statusbar.showMessage("HEC-RAS opened (parent instance)")
        except Exception as e:
            self.log(f"Could not open HEC-RAS: {e}")
            self._parent_ras = None

    def _refresh_parent_hecras(self) -> None:
        if self._parent_ras is None:
            return
        try:
            refresh_parent_instance(self._parent_ras, self.project_path, log=self.log)
        except Exception:
            self.log("Parent HEC-RAS is no longer available.")
            self._parent_ras = None

    # ── Local Execution ──

    def _execute(self) -> None:
        if not self.project_path:
            QMessageBox.critical(self, "Error", "Please select a project file")
            return

        if not os.path.exists(self.project_path):
            QMessageBox.critical(self, "Error", "Project file does not exist")
            return

        if self.project is None:
            self._load_project(self.project_path)
            if self.project is None:
                return

        selected = [r for r in self._plan_model.all_rows() if r.selected]
        if not selected:
            QMessageBox.critical(self, "Error", "Please select at least one plan")
            return

        self._execute_btn.setEnabled(False)
        self._plan_progress.clear()
        self._plan_results.clear()
        self._completed_count = 0
        self._total_plan_count = len(selected)

        self._status_label.setText(f"Running: 0 / {self._total_plan_count} complete")

        self._log_text.clear()
        self._log_messages.clear()

        # Mark all selected plans as "Running..." in the table
        for r in selected:
            self._plan_model.update_progress(r.key, "Running...")

        self.progress_queue = multiprocessing.Queue()

        plans_for_runner = plan_rows_to_jobs(selected)

        thread = threading.Thread(target=self._run_thread, args=(plans_for_runner,), daemon=True)
        thread.start()

    def _run_thread(self, plans: list[SimulationJob]) -> None:
        start_time = time.monotonic()
        results: list[SimulationResult] = []
        try:
            self.log("=" * 50)
            self.log("STARTING HEC-RAS SIMULATIONS")
            self.log("=" * 50)

            QTimer.singleShot(
                0, lambda: self._statusbar.showMessage("Checking HEC-RAS installation...")
            )

            if not check_hecras_installed(log=self.log):
                self.log("ERROR: HEC-RAS is not properly installed or registered.")
                return

            QTimer.singleShot(0, lambda: self._statusbar.showMessage("Running simulations..."))

            def _on_plan_result(result: SimulationResult) -> None:
                # Put on progress_queue so the GUI thread picks it up
                if self.progress_queue is not None:
                    self.progress_queue.put(result)

            results = run_simulations(
                project_path=self.project_path,
                jobs=plans,
                parallel=self._chk_parallel.isChecked(),
                cleanup=self._chk_cleanup.isChecked(),
                show_ras=False,
                log=self.log,
                progress_queue=self.progress_queue,
                result_callback=_on_plan_result,
            )

        except Exception as e:
            self.log(f"Error during simulation: {e}")
            self.log(traceback.format_exc())
        finally:
            total_elapsed = time.monotonic() - start_time
            QTimer.singleShot(0, lambda r=results, t=total_elapsed: self._on_complete(r, t))

    def _on_complete(self, results: list[SimulationResult], total_elapsed: float) -> None:
        self._execute_btn.setEnabled(True)
        self.progress_queue = None

        # Final pass — ensure any results not yet shown are updated
        self._update_plan_results(results)

        # Log compute messages from each plan
        for r in results:
            if r.compute_messages:
                self.log(f"--- {r.plan_name} compute messages ---")
                for line in r.compute_messages.splitlines():
                    if line.strip():
                        self.log(line)

        n_success = sum(1 for r in results if r.success)
        n_fail = len(results) - n_success
        mins, secs = divmod(int(total_elapsed), 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        self._status_label.setText(f"Done: {n_success} OK, {n_fail} failed \u2014 {time_str}")

        self.log("=" * 50)
        self.log(f"COMPLETE: {n_success} succeeded, {n_fail} failed in {time_str}")
        self.log("=" * 50)

        self._statusbar.showMessage(f"Done: {n_success} OK, {n_fail} failed \u2014 {time_str}")

        self._refresh_parent_hecras()

    def _update_single_plan_result(self, r: SimulationResult) -> None:
        """Update one plan's progress cell immediately when it finishes."""
        self._plan_results[r.plan_suffix] = r
        plan_key = f"p{r.plan_suffix}"
        progress_text, tag = format_result_progress(r)
        self._plan_model.update_result(plan_key, progress_text, tag)

        # Update status label with running count
        self._completed_count = len(self._plan_results)
        total = getattr(self, "_total_plan_count", self._completed_count)
        self._status_label.setText(f"Running: {self._completed_count} / {total} complete")

    def _update_plan_results(self, results: list[SimulationResult]) -> None:
        for r in results:
            self._plan_results[r.plan_suffix] = r
            plan_key = f"p{r.plan_suffix}"
            progress_text, tag = format_result_progress(r)
            self._plan_model.update_result(plan_key, progress_text, tag)

    # ── Network: DB connection ──

    def _show_db_connection_modal(self) -> None:
        dialog = DbConnectionDialog(
            host=self._settings.db.host,
            port=str(self._settings.db.port),
            dbname=self._settings.db.dbname,
            user=self._settings.db.user,
            password=self._settings.db.password,
            share_path=self._settings.network.share_path,
            parent=self,
        )
        self._current_db_dialog = dialog

        dialog.test_requested.connect(lambda: self._test_db_connection(dialog))
        dialog.save_requested.connect(lambda: self._save_db_from_dialog(dialog))
        dialog.exec()
        self._current_db_dialog = None

    def _save_db_from_dialog(self, dialog: DbConnectionDialog) -> None:
        vals = dialog.values()
        self._settings.db.host = vals["host"]
        self._settings.db.port = int(vals["port"] or "5432")
        self._settings.db.dbname = vals["dbname"]
        self._settings.db.user = vals["user"]
        self._settings.db.password = vals["password"]
        self._settings.network.share_path = vals["share_path"]
        self._save_network_settings()

    def _test_db_connection(self, dialog: DbConnectionDialog) -> None:
        """Test DB connection in a background thread with debug logging."""
        vals = dialog.values()
        dialog.status_label.setText("Connecting...")
        self._set_traffic_light("yellow")

        # #5 — Close any existing failing/stale connection first
        if self._db_client is not None:
            self.log("Closing previous DB connection...")
            with contextlib.suppress(Exception):
                self._db_client.close()  # type: ignore[attr-defined]
            self._db_client = None

        conninfo = (
            f"host={vals['host']} port={vals['port']} dbname={vals['dbname']} user={vals['user']}"
        )
        self.log(f"DB: Attempting connection to {conninfo}")

        def _connect() -> None:
            try:
                from hecras_runner.db import DbClient
                from hecras_runner.settings import DbSettings

                settings = DbSettings(
                    host=vals["host"],
                    port=int(vals["port"] or "5432"),
                    dbname=vals["dbname"],
                    user=vals["user"],
                    password=vals["password"],
                )
                client = DbClient.connect(settings, log=self.log)

                if client is not None:
                    self._db_client = client
                    self.log("DB: Connection successful")
                    self._db_result_signal.emit(True, "Connected")
                else:
                    self.log("DB: DbClient.connect() returned None")
                    self._db_result_signal.emit(False, "Connection failed (see log)")
            except Exception as e:
                self.log(f"DB: Connection exception: {e}")
                self.log(traceback.format_exc())
                self._db_result_signal.emit(False, f"Error: {e}")

        threading.Thread(target=_connect, daemon=True).start()

    def _on_db_result(self, success: bool, detail: str) -> None:
        """Handle DB connection result on the GUI thread."""
        dialog = getattr(self, "_current_db_dialog", None)
        if success:
            self._set_traffic_light("green")
            if dialog:
                dialog.status_label.setText("Connected")
            self._start_worker_polling()
        else:
            self._set_traffic_light("red")
            if dialog:
                dialog.status_label.setText(detail)

    def _toggle_accept_jobs(self) -> None:
        if self._worker_mode_active:
            self._worker_mode_active = False
            self._worker_btn.setChecked(False)
            self._stop_worker()
        else:
            self._worker_mode_active = True
            self._worker_btn.setChecked(True)
            self._start_worker()
            if not self._worker_mode_active:
                self._worker_btn.setChecked(False)

    def _save_network_settings(self) -> None:
        self._settings.network.enabled = self._net_enabled_chk.isChecked()
        self._settings.network.worker_mode = self._worker_mode_active
        save_settings(self._settings)
        self.log("Settings saved.")

    # ── Network: Worker list polling ──

    def _start_worker_polling(self) -> None:
        if self._worker_polling_active:
            return
        self._worker_polling_active = True
        self._poll_workers()

    def _poll_workers(self) -> None:
        if not self._worker_polling_active or self._db_client is None:
            return

        def _fetch() -> None:
            try:
                workers = self._db_client.get_active_workers()  # type: ignore[attr-defined]
                QTimer.singleShot(0, lambda w=workers: self._update_worker_table(w))
            except Exception as exc:
                msg = f"Poll error: {exc}"
                QTimer.singleShot(0, lambda m=msg: self.log(m))

        threading.Thread(target=_fetch, daemon=True).start()
        QTimer.singleShot(10000, self._poll_workers)

    def _update_worker_table(self, workers: list[dict]) -> None:
        self._worker_table.setRowCount(0)

        if not workers:
            self._worker_placeholder.setVisible(True)
            return

        self._worker_placeholder.setVisible(False)
        self._worker_table.setRowCount(len(workers))
        for i, w in enumerate(workers):
            self._worker_table.setItem(i, 0, QTableWidgetItem(w["hostname"]))
            self._worker_table.setItem(i, 1, QTableWidgetItem(w["ip_address"]))
            status_item = QTableWidgetItem(w["status"])
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._worker_table.setItem(i, 2, status_item)
            hecras_item = QTableWidgetItem(w["hecras_version"])
            hecras_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._worker_table.setItem(i, 3, hecras_item)

    # ── Network: Distributed execution ──

    def _execute_distributed(self) -> None:
        if self._db_client is None:
            QMessageBox.critical(self, "Error", "Not connected to database")
            return

        if not self._settings.network.share_path:
            QMessageBox.critical(self, "Error", "Share path not configured")
            return

        if not self.project_path or self.project is None:
            QMessageBox.critical(self, "Error", "No project loaded")
            return

        selected = [r for r in self._plan_model.all_rows() if r.selected]
        if not selected:
            QMessageBox.critical(self, "Error", "Please select at least one plan")
            return

        self._dist_execute_btn.setEnabled(False)
        self._status_label.setText("Running...")

        thread = threading.Thread(target=self._distributed_thread, args=(selected,), daemon=True)
        thread.start()

    def _distributed_thread(self, plan_rows: list[PlanRow]) -> None:
        try:
            from hecras_runner.transfer import project_to_share

            self.log("Uploading project to share...")
            QTimer.singleShot(0, lambda: self._statusbar.showMessage("Uploading to share..."))

            jobs_for_db: list[dict] = []
            for row in plan_rows:
                suffix = row.key[1:]
                import uuid

                job_id = str(uuid.uuid4())
                project_to_share(
                    self.project_path,
                    self._settings.network.share_path,
                    job_id,
                    suffix,
                    log=self.log,
                )
                jobs_for_db.append(
                    {
                        "plan_name": row.title,
                        "plan_suffix": suffix,
                    }
                )

            self.log("Submitting batch to database...")
            batch_id = self._db_client.submit_batch(  # type: ignore[attr-defined]
                project_path=self._settings.network.share_path,
                project_title=self.project.title if self.project else "",
                jobs=jobs_for_db,
                submitted_by=os.environ.get("USERNAME", ""),
            )
            self._distributed_batch_id = batch_id
            self.log(f"Batch {batch_id} submitted with {len(plan_rows)} jobs")
            QTimer.singleShot(
                0, lambda: self._statusbar.showMessage(f"Batch {batch_id[:8]}... queued")
            )

            QTimer.singleShot(0, self._poll_batch_status)

        except Exception as e:
            self.log(f"Distributed submission failed: {e}")
            QTimer.singleShot(0, lambda: self._dist_execute_btn.setEnabled(True))

    def _poll_batch_status(self) -> None:
        if self._distributed_batch_id is None or self._db_client is None:
            return

        def _check() -> None:
            try:
                status = self._db_client.get_batch_status(  # type: ignore[attr-defined]
                    self._distributed_batch_id
                )
                QTimer.singleShot(0, lambda s=status: self._handle_batch_status(s))
            except Exception as exc:
                msg = f"Batch poll error: {exc}"
                QTimer.singleShot(0, lambda m=msg: self.log(m))
                QTimer.singleShot(5000, self._poll_batch_status)

        threading.Thread(target=_check, daemon=True).start()

    def _handle_batch_status(self, status: dict) -> None:
        total = status.get("total", 0)
        completed = status.get("completed", 0)
        failed = status.get("failed", 0)
        running = status.get("running", 0)

        self._status_label.setText(
            f"Batch: {completed} done, {running} running, {failed} failed / {total} total"
        )

        batch_status = status.get("status", "")
        if batch_status in ("completed", "failed"):
            self._on_distributed_complete(status)
        else:
            QTimer.singleShot(5000, self._poll_batch_status)

    def _on_distributed_complete(self, status: dict) -> None:
        self._dist_execute_btn.setEnabled(True)

        completed = status.get("completed", 0)
        failed = status.get("failed", 0)

        self._status_label.setText(f"Done: {completed} OK, {failed} failed")

        if self._distributed_batch_id and self._db_client:
            try:
                from hecras_runner.transfer import results_from_share

                jobs = self._db_client.get_batch_jobs(  # type: ignore[attr-defined]
                    self._distributed_batch_id
                )
                main_dir = os.path.dirname(self.project_path)
                for job in jobs:
                    if job["status"] == "completed":
                        results_dir = os.path.join(
                            self._settings.network.share_path, "results", job["id"]
                        )
                        results_from_share(results_dir, main_dir, job["plan_suffix"], log=self.log)
            except Exception as e:
                self.log(f"Result retrieval error: {e}")

        self._distributed_batch_id = None
        self.log(f"Distributed batch complete: {completed} succeeded, {failed} failed")
        self._statusbar.showMessage("Ready")

        self._refresh_parent_hecras()

    # ── Network: Worker mode ──

    def _start_worker(self) -> None:
        if self._db_client is None:
            QMessageBox.critical(self, "Error", "Connect to database first")
            self._worker_mode_active = False
            return

        ras_exe = find_hecras_exe(log=self.log)
        if not ras_exe:
            QMessageBox.critical(self, "Error", "HEC-RAS not found")
            self._worker_mode_active = False
            return

        try:
            self._worker_info = self._db_client.register_worker(  # type: ignore[attr-defined]
                hecras_path=ras_exe,
            )
            worker_id = self._worker_info.worker_id  # type: ignore[attr-defined]
            self._db_client.start_heartbeat(worker_id)  # type: ignore[attr-defined]
            self.log(f"Worker mode started ({worker_id[:8]}...)")
            self._statusbar.showMessage("Worker: idle")

            # Ensure polling is active, then force an immediate refresh
            self._start_worker_polling()
            self._poll_workers()
            self._worker_poll_jobs()
        except Exception as e:
            self.log(f"Worker registration failed: {e}")
            self._worker_mode_active = False

    def _stop_worker(self) -> None:
        if self._db_client is not None and self._worker_info is not None:
            with contextlib.suppress(Exception):
                worker_id = self._worker_info.worker_id  # type: ignore[attr-defined]
                self._db_client.set_worker_offline(worker_id)  # type: ignore[attr-defined]
                self._db_client.stop_heartbeat()  # type: ignore[attr-defined]
        self._worker_info = None
        self._statusbar.showMessage("Ready")
        self.log("Worker mode stopped.")

    def _worker_poll_jobs(self) -> None:
        if not self._worker_mode_active or self._db_client is None or self._worker_info is None:
            return

        def _try_claim() -> None:
            try:
                worker_id = self._worker_info.worker_id  # type: ignore[attr-defined]
                job = self._db_client.claim_job(worker_id)  # type: ignore[attr-defined]
                if job:
                    QTimer.singleShot(0, lambda j=job: self._run_worker_job(j))
                else:
                    QTimer.singleShot(5000, self._worker_poll_jobs)
            except Exception as e:
                self.log(f"Job claim error: {e}")
                QTimer.singleShot(10000, self._worker_poll_jobs)

        threading.Thread(target=_try_claim, daemon=True).start()

    def _run_worker_job(self, job: dict) -> None:
        job_id = job["job_id"]
        plan_name = job["plan_name"]
        self.log(f"Running job {job_id[:8]}...: {plan_name}")
        self._statusbar.showMessage(f"Worker: running {plan_name}")

        def _execute() -> None:
            try:
                from hecras_runner.file_ops import cleanup_temp_dir, copy_project_to_temp
                from hecras_runner.runner import run_hecras_cli

                self._db_client.start_job(job_id)  # type: ignore[attr-defined]

                ras_exe = find_hecras_exe(log=self.log)
                temp_prj = copy_project_to_temp(job["project_path"], log=self.log)
                result = run_hecras_cli(
                    temp_prj,
                    plan_suffix=job["plan_suffix"],
                    plan_name=plan_name,
                    ras_exe=ras_exe,
                    log=self.log,
                )

                self._db_client.complete_job(  # type: ignore[attr-defined]
                    job_id,
                    success=result.success,
                    elapsed_seconds=result.elapsed_seconds,
                    error_message=result.error_message,
                    hdf_verified=result.success,
                )
                cleanup_temp_dir(os.path.dirname(temp_prj), log=self.log)

                status = "OK" if result.success else "FAILED"
                self.log(f"Job {job_id[:8]}...: {status} ({result.elapsed_seconds:.1f}s)")
            except Exception as e:
                self.log(f"Job {job_id[:8]}... ERROR: {e}")
                with contextlib.suppress(Exception):
                    self._db_client.complete_job(  # type: ignore[attr-defined]
                        job_id,
                        success=False,
                        elapsed_seconds=0.0,
                        error_message=str(e),
                    )

            QTimer.singleShot(0, lambda: self._statusbar.showMessage("Worker: idle"))
            QTimer.singleShot(1000, self._worker_poll_jobs)

        threading.Thread(target=_execute, daemon=True).start()

    # ── Version check ──

    def _check_for_updates(self) -> None:
        def _on_result(info: VersionInfo | None) -> None:
            self._version_signal.emit(info)

        check_for_update(__version__, self._settings.update_url, _on_result)

    def _on_version_check_result(self, info: VersionInfo | None) -> None:
        """Cache version info for the About dialog. Show popup if update available."""
        self._update_info = info
        if info is not None:
            self._statusbar.showMessage(f"Update available: v{info.latest_version}")

    # ── Close handling ──

    def closeEvent(self, event) -> None:  # noqa: N802
        # Stop worker if active
        if self._worker_mode_active:
            self._stop_worker()

        # Stop worker polling
        self._worker_polling_active = False

        # Close DB connection
        if self._db_client is not None:
            with contextlib.suppress(Exception):
                self._db_client.close()  # type: ignore[attr-defined]

        if self._parent_ras is not None:
            answer = QMessageBox.question(
                self,
                "Close HEC-RAS?",
                "A parent HEC-RAS instance is open.\n\nClose HEC-RAS as well?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                with contextlib.suppress(Exception):
                    self._parent_ras.QuitRas()  # type: ignore[attr-defined]
            self._parent_ras = None

        if self._com_initialized:
            try:
                pythoncom = importlib.import_module("pythoncom")
                pythoncom.CoUninitialize()
            except Exception:
                pass

        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon_file = _icon_path()
    if os.path.isfile(icon_file):
        app.setWindowIcon(QIcon(icon_file))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
