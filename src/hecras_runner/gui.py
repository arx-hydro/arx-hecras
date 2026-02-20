"""Tkinter GUI for HEC-RAS parallel runner."""

from __future__ import annotations

import contextlib
import importlib
import multiprocessing
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from hecras_runner import __version__
from hecras_runner.parser import RasProject, parse_project
from hecras_runner.runner import (
    ProgressMessage,
    SimulationJob,
    SimulationResult,
    check_hecras_installed,
    find_hecras_processes,
    open_parent_instance,
    refresh_parent_instance,
    run_simulations,
)
from hecras_runner.settings import load_settings, save_settings
from hecras_runner.version_check import VersionInfo, check_for_update

# Column definitions for plan table: (id, heading, width, anchor)
_PLAN_COLUMNS = [
    ("sel", "\u2713", 30, "center"),
    ("key", "Plan", 50, "center"),
    ("title", "Title", 120, "w"),
    ("geom", "Geometry", 150, "w"),
    ("flow", "Flow", 150, "w"),
    ("dss", "DSS Files", 180, "w"),
    ("progress", "Progress", 70, "center"),
    ("log", "Log", 40, "center"),
]

# Column indices for structured access
_COL_SEL = 0
_COL_KEY = 1
_COL_TITLE = 2
_COL_GEOM = 3
_COL_FLOW = 4
_COL_DSS = 5
_COL_PROGRESS = 6
_COL_LOG = 7

CHECK_MARK = "\u2611"  # ☑
DASH = "\u2610"  # ☐


class HECRASParallelRunnerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"HEC-RAS Parallel Runner v{__version__}")
        self.root.geometry("1100x750")

        self.project_path = tk.StringVar()
        self.run_parallel = tk.BooleanVar(value=True)
        self.cleanup_temp = tk.BooleanVar(value=True)
        self.debug_mode = tk.BooleanVar(value=False)
        self._filter_title = tk.StringVar()
        self._filter_geom = tk.StringVar()
        self._filter_flow = tk.StringVar()

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.progress_queue: multiprocessing.Queue | None = None
        self.project: RasProject | None = None
        self._plan_selected: dict[str, bool] = {}  # plan_key -> selected
        self._all_plan_rows: list[tuple[str, ...]] = []  # cached rows for filtering
        self._plan_progress: dict[str, float] = {}  # plan_suffix -> fraction
        self._plan_results: dict[str, SimulationResult] = {}  # plan_suffix -> result
        self._log_messages: list[str] = []  # accumulated log messages

        # Parent HEC-RAS instance
        self._parent_ras: object | None = None
        self._com_initialized = False

        # Network state
        self._settings = load_settings()
        self._db_client: object | None = None
        self._worker_info: object | None = None
        self._worker_polling_active = False
        self._distributed_batch_id: str | None = None

        # Network tkinter vars
        self._net_enabled = tk.BooleanVar(value=self._settings.network.enabled)
        self._db_host = tk.StringVar(value=self._settings.db.host)
        self._db_port = tk.StringVar(value=str(self._settings.db.port))
        self._db_name = tk.StringVar(value=self._settings.db.dbname)
        self._db_user = tk.StringVar(value=self._settings.db.user)
        self._db_password = tk.StringVar(value=self._settings.db.password)
        self._share_path = tk.StringVar(value=self._settings.network.share_path)
        self._worker_mode = tk.BooleanVar(value=self._settings.network.worker_mode)
        self._db_status = tk.StringVar(value="Not connected")

        self._create_widgets()
        self._process_log_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._check_for_updates()

    def _check_for_updates(self) -> None:
        """Check for newer version in the background."""

        def _on_result(info: VersionInfo | None) -> None:
            if info is not None:
                self.root.after(0, lambda: self._show_update_available(info))

        check_for_update(__version__, self._settings.update_url, _on_result)

    def _show_update_available(self, info: VersionInfo) -> None:
        """Show update notification to the user."""
        msg = f"A new version is available: v{info.latest_version}\n\n"
        if info.release_notes:
            msg += f"{info.release_notes}\n\n"
        if info.download_url:
            msg += f"Download: {info.download_url}"
        messagebox.showinfo("Update Available", msg)

    def _create_widgets(self) -> None:
        # Make tabs more obvious with stronger contrast
        style = ttk.Style()
        style.configure("TNotebook.Tab", padding=(8, 4))
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#ffffff"), ("!selected", "#c0c0c0")],
            foreground=[("selected", "#000000"), ("!selected", "#555555")],
        )

        # Main horizontal PanedWindow
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        # ── Left pane: notebook with tabs ──
        left = ttk.Frame(paned)
        paned.add(left, weight=3)

        # Title
        ttk.Label(left, text="HEC-RAS Parallel Runner", font=("Arial", 16, "bold")).pack(
            pady=(10, 5)
        )

        # Project file row (shared across tabs)
        proj_frame = ttk.Frame(left)
        proj_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(proj_frame, text="Project (.prj)").pack(side="left")
        ttk.Entry(proj_frame, textvariable=self.project_path, width=45).pack(
            side="left", padx=5, fill="x", expand=True
        )
        ttk.Button(proj_frame, text="Browse...", command=self._browse_project).pack(side="left")

        # Notebook tabs
        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # Tab 0: Local
        local_tab = ttk.Frame(self.notebook)
        self.notebook.add(local_tab, text="Local")
        self._create_local_tab(local_tab)

        # Tab 1: Network
        network_tab = ttk.Frame(self.notebook)
        self.notebook.add(network_tab, text="Network")
        self._create_network_tab(network_tab)

        # ── Right pane: log ──
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        # Status + progress at top of log pane
        self.status_var = tk.StringVar(value="Ready")
        status_frame = ttk.Frame(right)
        status_frame.pack(fill="x", padx=5, pady=(5, 0))
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            font=("TkDefaultFont", 9, "bold"),
        ).pack(fill="x")
        self.progress = ttk.Progressbar(status_frame, mode="determinate", length=200)
        self.progress.pack(fill="x", pady=(2, 5))

        # Log header with copy button
        log_header = ttk.Frame(right)
        log_header.pack(fill="x", padx=5, pady=(0, 2))
        ttk.Label(log_header, text="Execution Log", font=("Arial", 10, "bold")).pack(side="left")
        self._copy_log_btn = ttk.Button(
            log_header, text="Copy", width=6, command=self._copy_log_to_clipboard
        )
        self._copy_log_btn.pack(side="right")

        self.log_text = scrolledtext.ScrolledText(
            right, width=40, height=20, font=("Courier", 9), wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=(0, 5))

    # ── Local tab ──

    def _create_local_tab(self, parent: ttk.Frame) -> None:
        # Plan table
        plan_frame = ttk.LabelFrame(parent, text="Plan Selection", padding="5")
        plan_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Select buttons row
        btn_row = ttk.Frame(plan_frame)
        btn_row.pack(fill="x", pady=(0, 3))
        ttk.Button(btn_row, text="Select All", command=self._select_all).pack(side="right", padx=2)
        ttk.Button(btn_row, text="Deselect All", command=self._deselect_all).pack(
            side="right", padx=2
        )

        # Per-column filter row above the treeview
        filter_frame = ttk.Frame(plan_frame)
        filter_frame.pack(fill="x", pady=(0, 2))
        ttk.Label(filter_frame, text="Filter:", foreground="gray").pack(side="left", padx=(0, 5))
        # Spacers for sel + key columns (approx widths)
        ttk.Frame(filter_frame, width=80).pack(side="left")
        ttk.Entry(filter_frame, textvariable=self._filter_title, width=15).pack(side="left", padx=2)
        ttk.Entry(filter_frame, textvariable=self._filter_geom, width=18).pack(side="left", padx=2)
        ttk.Entry(filter_frame, textvariable=self._filter_flow, width=18).pack(side="left", padx=2)
        self._filter_title.trace_add("write", lambda *_: self._apply_filter())
        self._filter_geom.trace_add("write", lambda *_: self._apply_filter())
        self._filter_flow.trace_add("write", lambda *_: self._apply_filter())

        # Tree + scrollbar container
        tree_container = ttk.Frame(plan_frame)
        tree_container.pack(fill="both", expand=True)

        # Treeview — parent is tree_container so pack works correctly
        col_ids = [c[0] for c in _PLAN_COLUMNS]
        self.plan_tree = ttk.Treeview(
            tree_container, columns=col_ids, show="headings", height=8, selectmode="none"
        )
        for col_id, heading, width, anchor in _PLAN_COLUMNS:
            self.plan_tree.heading(col_id, text=heading)
            self.plan_tree.column(col_id, width=width, minwidth=width // 2, anchor=anchor)

        # Tags for current plan and results
        self.plan_tree.tag_configure("current", font=("TkDefaultFont", 9, "bold"))
        self.plan_tree.tag_configure("success", foreground="#228B22")
        self.plan_tree.tag_configure("failure", foreground="#8B0000")

        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.plan_tree.yview)
        self.plan_tree.configure(yscrollcommand=tree_scroll.set)
        self.plan_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Bind click on selection column
        self.plan_tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # Execution options
        options_frame = ttk.LabelFrame(parent, text="Execution Options", padding="5")
        options_frame.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(
            options_frame, text="Run plans in parallel", variable=self.run_parallel
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            options_frame,
            text="Clean up temporary files",
            variable=self.cleanup_temp,
        ).grid(row=0, column=1, sticky="w", padx=(20, 0))
        ttk.Checkbutton(options_frame, text="Debug mode (verbose)", variable=self.debug_mode).grid(
            row=1, column=0, sticky="w"
        )

        # Execute button
        exec_frame = ttk.Frame(parent)
        exec_frame.pack(fill="x", padx=10, pady=5)
        self.execute_btn = ttk.Button(
            exec_frame, text="EXECUTE SIMULATIONS", command=self._execute, width=30
        )
        self.execute_btn.pack(pady=(0, 5))

    # ── Network tab ──

    def _create_network_tab(self, parent: ttk.Frame) -> None:
        # Enable toggle
        ttk.Checkbutton(
            parent,
            text="Enable Network Mode",
            variable=self._net_enabled,
            command=self._toggle_network_widgets,
        ).pack(anchor="w", padx=10, pady=(10, 5))

        # Compact connection row: traffic light + Database button + Open to Work checkbox
        conn_row = ttk.Frame(parent)
        conn_row.pack(fill="x", padx=10, pady=5)

        # Traffic light indicator (canvas circle)
        self._conn_canvas = tk.Canvas(conn_row, width=20, height=20, highlightthickness=0)
        self._conn_canvas.pack(side="left", padx=(0, 5))
        # Orange = not yet configured/tested
        self._conn_indicator = self._conn_canvas.create_oval(2, 2, 18, 18, fill="#CC8800")

        # Database button → opens modal
        self._db_btn = ttk.Button(conn_row, text="Database", command=self._show_db_connection_modal)
        self._db_btn.pack(side="left", padx=(0, 10))

        # Worker toggle button — pale green off, dark green on
        self._worker_btn = tk.Button(
            conn_row,
            text="Worker",
            bg="#90EE90",
            activebackground="#90EE90",
            font=("TkDefaultFont", 10, "bold"),
            width=10,
            relief="raised",
            command=self._toggle_accept_jobs,
        )
        self._worker_btn.pack(side="right", padx=(10, 0))

        # Worker list
        worker_frame = ttk.LabelFrame(parent, text="Workers", padding="5")
        worker_frame.pack(fill="both", expand=True, padx=10, pady=5)

        worker_cols = ("hostname", "ip", "status", "hecras")
        self.worker_tree = ttk.Treeview(
            worker_frame, columns=worker_cols, show="headings", height=5, selectmode="none"
        )
        self.worker_tree.heading("hostname", text="Host")
        self.worker_tree.heading("ip", text="IP")
        self.worker_tree.heading("status", text="Status")
        self.worker_tree.heading("hecras", text="HEC-RAS")
        self.worker_tree.column("hostname", width=120)
        self.worker_tree.column("ip", width=110)
        self.worker_tree.column("status", width=80, anchor="center")
        self.worker_tree.column("hecras", width=60, anchor="center")
        self.worker_tree.pack(fill="both", expand=True)

        self._worker_placeholder = ttk.Label(
            worker_frame, text="Connect to DB to see workers", foreground="gray"
        )
        self._worker_placeholder.place(relx=0.5, rely=0.5, anchor="center")

        # Actions
        action_frame = ttk.Frame(parent)
        action_frame.pack(fill="x", padx=10, pady=5)

        self.dist_execute_btn = ttk.Button(
            action_frame, text="Run Distributed", command=self._execute_distributed, width=20
        )
        self.dist_execute_btn.pack(side="left", padx=(0, 10))

        self._save_settings_btn = ttk.Button(
            action_frame, text="Save Settings", command=self._save_network_settings, width=15
        )
        self._save_settings_btn.pack(side="left", padx=(0, 10))

        # Initial state
        self._toggle_network_widgets()

    def _toggle_network_widgets(self) -> None:
        """Enable/disable network tab widgets based on toggle."""
        state = "normal" if self._net_enabled.get() else "disabled"
        self._db_btn.configure(state=state)
        self._worker_btn.configure(state=state)
        self.dist_execute_btn.configure(state=state)
        self._save_settings_btn.configure(state=state)

    # ── Network: DB connection ──

    def _set_conn_indicator(self, color: str) -> None:
        """Update the traffic light indicator color (orange/yellow/green/red)."""
        color_map = {
            "orange": "#CC8800",
            "red": "#CC0000",
            "yellow": "#CCCC00",
            "green": "#00AA00",
        }
        fill = color_map.get(color, color)
        self._conn_canvas.itemconfig(self._conn_indicator, fill=fill)

    def _test_db_connection(self) -> None:
        """Test DB connection in a thread to avoid blocking GUI."""
        self._db_status.set("Connecting...")
        self._set_conn_indicator("yellow")

        def _connect() -> None:
            from hecras_runner.db import DbClient
            from hecras_runner.settings import DbSettings

            settings = DbSettings(
                host=self._db_host.get(),
                port=int(self._db_port.get() or "5432"),
                dbname=self._db_name.get(),
                user=self._db_user.get(),
                password=self._db_password.get(),
            )
            client = DbClient.connect(settings, log=self.log)

            def _update() -> None:
                if client is not None:
                    self._db_client = client
                    self._db_status.set("Connected")
                    self._set_conn_indicator("green")
                    self._start_worker_polling()
                else:
                    self._db_status.set("Connection failed")
                    self._set_conn_indicator("red")

            self.root.after(0, _update)

        threading.Thread(target=_connect, daemon=True).start()

    def _show_db_connection_modal(self) -> None:
        """Show a modal dialog with DB connection fields + share path."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Database Connection")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding="10")
        frame.pack(fill="both", expand=True)

        row = 0
        for label, var, width, show in [
            ("Host:", self._db_host, 25, None),
            ("Port:", self._db_port, 8, None),
            ("Database:", self._db_name, 20, None),
            ("User:", self._db_user, 20, None),
            ("Password:", self._db_password, 20, "*"),
        ]:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 5), pady=2)
            kw = {"show": show} if show else {}
            ttk.Entry(frame, textvariable=var, width=width, **kw).grid(
                row=row, column=1, sticky="ew", pady=2
            )
            row += 1

        # Share path
        ttk.Label(frame, text="Share Path:").grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 5),
            pady=2,
        )
        share_row = ttk.Frame(frame)
        share_row.grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Entry(share_row, textvariable=self._share_path, width=30).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(share_row, text="...", width=3, command=self._browse_share).pack(
            side="left", padx=(5, 0)
        )
        row += 1

        # Status label
        ttk.Label(frame, textvariable=self._db_status).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        row += 1

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(10, 0))

        ttk.Button(btn_frame, text="Test Connection", command=self._test_db_connection).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(
            btn_frame,
            text="Save",
            command=lambda: (self._save_network_settings(), dialog.destroy()),
        ).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side="left")

        # Center on parent
        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"+{x}+{y}")

    def _toggle_accept_jobs(self) -> None:
        """Toggle worker mode via button click."""
        if self._worker_mode.get():
            # Currently on → turn off
            self._worker_mode.set(False)
            self._stop_worker()
            self._worker_btn.configure(bg="#90EE90", activebackground="#90EE90", relief="raised")
        else:
            # Currently off → turn on
            self._worker_mode.set(True)
            self._start_worker()
            # _start_worker may have reset the var on error
            if self._worker_mode.get():
                self._worker_btn.configure(
                    bg="#228B22", activebackground="#228B22", fg="white", relief="sunken"
                )
            else:
                self._worker_btn.configure(
                    bg="#90EE90", activebackground="#90EE90", fg="black", relief="raised"
                )

    def _browse_share(self) -> None:
        path = filedialog.askdirectory(title="Select Network Share")
        if path:
            self._share_path.set(path)

    def _save_network_settings(self) -> None:
        """Persist network settings to disk."""
        self._settings.db.host = self._db_host.get()
        self._settings.db.port = int(self._db_port.get() or "5432")
        self._settings.db.dbname = self._db_name.get()
        self._settings.db.user = self._db_user.get()
        self._settings.db.password = self._db_password.get()
        self._settings.network.enabled = self._net_enabled.get()
        self._settings.network.share_path = self._share_path.get()
        self._settings.network.worker_mode = self._worker_mode.get()

        save_settings(self._settings)
        self.log("Settings saved.")

    # ── Network: Worker list polling ──

    def _start_worker_polling(self) -> None:
        """Start polling for active workers every 10s."""
        if self._worker_polling_active:
            return
        self._worker_polling_active = True
        self._poll_workers()

    def _poll_workers(self) -> None:
        """Fetch active workers from DB and update the treeview."""
        if not self._worker_polling_active or self._db_client is None:
            return

        def _fetch() -> None:
            try:
                workers = self._db_client.get_active_workers()  # type: ignore[attr-defined]
                self.root.after(0, self._update_worker_tree, workers)
            except Exception as exc:
                msg = f"Poll error: {exc}"
                self.root.after(0, lambda m=msg: self._db_status.set(m))

        threading.Thread(target=_fetch, daemon=True).start()
        self.root.after(10000, self._poll_workers)

    def _update_worker_tree(self, workers: list[dict]) -> None:
        """Update the worker treeview with fresh data."""
        self.worker_tree.delete(*self.worker_tree.get_children())

        if not workers:
            self._worker_placeholder.place(relx=0.5, rely=0.5, anchor="center")
            return

        self._worker_placeholder.place_forget()
        n_busy = sum(1 for w in workers if w["status"] == "busy")
        for w in workers:
            self.worker_tree.insert(
                "",
                "end",
                values=(w["hostname"], w["ip_address"], w["status"], w["hecras_version"]),
            )

        # Update frame label with counts
        n_online = len(workers)
        status = f"{n_online} online"
        if n_busy:
            status += f", {n_busy} busy"

    # ── Network: Distributed execution ──

    def _execute_distributed(self) -> None:
        """Submit selected plans to the distributed job queue."""
        if self._db_client is None:
            messagebox.showerror("Error", "Not connected to database")
            return

        if not self._share_path.get():
            messagebox.showerror("Error", "Share path not configured")
            return

        if not self.project_path.get() or self.project is None:
            messagebox.showerror("Error", "No project loaded")
            return

        selected_keys = {key for key, sel in self._plan_selected.items() if sel}
        if not selected_keys:
            messagebox.showerror("Error", "Please select at least one plan")
            return

        selected_plans = [p for p in self.project.plans if p.key in selected_keys]

        self.dist_execute_btn.configure(state="disabled")
        self.progress.configure(mode="determinate", maximum=100, value=0)

        thread = threading.Thread(
            target=self._distributed_thread, args=(selected_plans,), daemon=True
        )
        thread.start()

    def _distributed_thread(self, plans: list) -> None:
        """Upload project to share + submit batch to DB."""
        try:
            from hecras_runner.transfer import project_to_share

            self.log("Uploading project to share...")
            self.status_var.set("Uploading to share...")

            jobs_for_db: list[dict] = []
            for plan in plans:
                suffix = plan.key[1:]
                import uuid

                job_id = str(uuid.uuid4())
                project_to_share(
                    self.project_path.get(),
                    self._share_path.get(),
                    job_id,
                    suffix,
                    log=self.log,
                )
                jobs_for_db.append(
                    {
                        "plan_name": plan.title,
                        "plan_suffix": suffix,
                    }
                )

            self.log("Submitting batch to database...")
            batch_id = self._db_client.submit_batch(  # type: ignore[attr-defined]
                project_path=self._share_path.get(),
                project_title=self.project.title if self.project else "",
                jobs=jobs_for_db,
                submitted_by=os.environ.get("USERNAME", ""),
            )
            self._distributed_batch_id = batch_id
            self.log(f"Batch {batch_id} submitted with {len(plans)} jobs")
            self.status_var.set(f"Batch {batch_id[:8]}... queued")

            # Start polling for batch completion
            self.root.after(0, self._poll_batch_status)

        except Exception as e:
            self.log(f"Distributed submission failed: {e}")
            self.root.after(0, lambda: self.dist_execute_btn.configure(state="normal"))

    def _poll_batch_status(self) -> None:
        """Poll batch status every 5s until completion."""
        if self._distributed_batch_id is None or self._db_client is None:
            return

        def _check() -> None:
            try:
                status = self._db_client.get_batch_status(  # type: ignore[attr-defined]
                    self._distributed_batch_id
                )
                self.root.after(0, self._handle_batch_status, status)
            except Exception as exc:
                msg = f"Batch poll error: {exc}"
                self.root.after(0, lambda m=msg: self.log(m))
                self.root.after(5000, self._poll_batch_status)

        threading.Thread(target=_check, daemon=True).start()

    def _handle_batch_status(self, status: dict) -> None:
        """Process batch status update."""
        total = status.get("total", 0)
        completed = status.get("completed", 0)
        failed = status.get("failed", 0)
        running = status.get("running", 0)

        if total > 0:
            pct = ((completed + failed) / total) * 100
            self.progress["value"] = pct

        self.status_var.set(
            f"Batch: {completed} done, {running} running, {failed} failed / {total} total"
        )

        batch_status = status.get("status", "")
        if batch_status in ("completed", "failed"):
            self._on_distributed_complete(status)
        else:
            self.root.after(5000, self._poll_batch_status)

    def _on_distributed_complete(self, status: dict) -> None:
        """Handle distributed batch completion."""
        self.dist_execute_btn.configure(state="normal")
        self.progress.configure(value=100)

        completed = status.get("completed", 0)
        failed = status.get("failed", 0)

        if self._distributed_batch_id and self._db_client:
            # Retrieve results from share
            try:
                from hecras_runner.transfer import results_from_share

                jobs = self._db_client.get_batch_jobs(  # type: ignore[attr-defined]
                    self._distributed_batch_id
                )
                main_dir = os.path.dirname(self.project_path.get())
                for job in jobs:
                    if job["status"] == "completed":
                        results_dir = os.path.join(self._share_path.get(), "results", job["id"])
                        results_from_share(results_dir, main_dir, job["plan_suffix"], log=self.log)
            except Exception as e:
                self.log(f"Result retrieval error: {e}")

        self._distributed_batch_id = None
        self.log(f"Distributed batch complete: {completed} succeeded, {failed} failed")
        self.status_var.set("Ready")

        # Refresh parent HEC-RAS
        self._refresh_parent_hecras()

    # ── Network: Worker mode ──

    def _start_worker(self) -> None:
        """Register as a worker and start accepting jobs."""
        if self._db_client is None:
            messagebox.showerror("Error", "Connect to database first")
            self._worker_mode.set(False)
            return

        from hecras_runner.runner import find_hecras_exe

        ras_exe = find_hecras_exe(log=self.log)
        if not ras_exe:
            messagebox.showerror("Error", "HEC-RAS not found")
            self._worker_mode.set(False)
            return

        try:
            self._worker_info = self._db_client.register_worker(  # type: ignore[attr-defined]
                hecras_path=ras_exe,
            )
            worker_id = self._worker_info.worker_id  # type: ignore[attr-defined]
            self._db_client.start_heartbeat(worker_id)  # type: ignore[attr-defined]
            self.log(f"Worker mode started ({worker_id[:8]}...)")
            self.status_var.set("Worker: idle")

            # Start job polling in background
            self._worker_poll_jobs()
        except Exception as e:
            self.log(f"Worker registration failed: {e}")
            self._worker_mode.set(False)

    def _stop_worker(self) -> None:
        """Stop accepting jobs."""
        if self._db_client is not None and self._worker_info is not None:
            try:
                worker_id = self._worker_info.worker_id  # type: ignore[attr-defined]
                self._db_client.set_worker_offline(worker_id)  # type: ignore[attr-defined]
                self._db_client.stop_heartbeat()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._worker_info = None
        self.status_var.set("Ready")
        self.log("Worker mode stopped.")

    def _worker_poll_jobs(self) -> None:
        """Poll for available jobs in worker mode."""
        if not self._worker_mode.get() or self._db_client is None or self._worker_info is None:
            return

        def _try_claim() -> None:
            try:
                worker_id = self._worker_info.worker_id  # type: ignore[attr-defined]
                job = self._db_client.claim_job(worker_id)  # type: ignore[attr-defined]
                if job:
                    self.root.after(0, lambda: self._run_worker_job(job))
                else:
                    self.root.after(5000, self._worker_poll_jobs)
            except Exception as e:
                self.log(f"Job claim error: {e}")
                self.root.after(10000, self._worker_poll_jobs)

        threading.Thread(target=_try_claim, daemon=True).start()

    def _run_worker_job(self, job: dict) -> None:
        """Execute a claimed job in a background thread."""
        job_id = job["job_id"]
        plan_name = job["plan_name"]
        self.log(f"Running job {job_id[:8]}...: {plan_name}")
        self.status_var.set(f"Worker: running {plan_name}")

        def _execute() -> None:
            try:
                from hecras_runner.file_ops import cleanup_temp_dir, copy_project_to_temp
                from hecras_runner.runner import find_hecras_exe, run_hecras_cli

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

            self.root.after(0, lambda: self.status_var.set("Worker: idle"))
            self.root.after(1000, self._worker_poll_jobs)

        threading.Thread(target=_execute, daemon=True).start()

    # ── Log handling ──

    def _process_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                if not self.debug_mode.get() and message.startswith("[DEBUG]"):
                    continue
                formatted = f"{time.strftime('%H:%M:%S')} - {message}"
                self._log_messages.append(formatted)
                self.log_text.insert("end", formatted + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass

        # Drain progress queue
        self._drain_progress_queue()

        self.root.after(100, self._process_log_queue)

    def _drain_progress_queue(self) -> None:
        """Read all pending ProgressMessage objects and update plan table + bar."""
        if self.progress_queue is None:
            return

        updated = False
        try:
            while True:
                msg: ProgressMessage = self.progress_queue.get_nowait()
                self._plan_progress[msg.plan_suffix] = msg.fraction
                updated = True
        except (queue.Empty, EOFError):
            pass

        if not updated:
            return

        # Update treeview progress column for each plan
        for item_id in self.plan_tree.get_children():
            values = list(self.plan_tree.item(item_id, "values"))
            plan_key = values[_COL_KEY] if len(values) > _COL_KEY else ""
            suffix = plan_key[1:] if plan_key.startswith("p") else ""
            if suffix in self._plan_progress:
                pct = int(self._plan_progress[suffix] * 100)
                values[_COL_PROGRESS] = f"{pct}%"
                self.plan_tree.item(item_id, values=values)

        # Update progress bar (average across tracked plans)
        if self._plan_progress:
            avg = sum(self._plan_progress.values()) / len(self._plan_progress)
            # Switch from indeterminate to determinate once we have real progress
            if str(self.progress.cget("mode")) == "indeterminate":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=100)
            self.progress["value"] = avg * 100

    def _copy_log_to_clipboard(self) -> None:
        """Copy execution log contents to clipboard."""
        text = self.log_text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._copy_log_btn.configure(text="Copied!")
        self.root.after(1500, lambda: self._copy_log_btn.configure(text="Copy"))

    def log(self, message: str) -> None:
        self.log_queue.put(message)

    # ── File browsing ──

    def _browse_project(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select HEC-RAS Project File",
            filetypes=[("Project files", "*.prj"), ("All files", "*.*")],
        )
        if filename:
            self.project_path.set(filename)
            self.log(f"Project selected: {filename}")
            self._load_project(filename)

    # ── Plan loading with table ──

    def _load_project(self, prj_path: str) -> None:
        self.root.config(cursor="wait")
        self.status_var.set("Loading project...")
        self.root.update_idletasks()
        try:
            self.project = parse_project(prj_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse project: {e}")
            return
        finally:
            self.root.config(cursor="")
            self.status_var.set("Ready")

        # Build lookup maps
        geom_map = {g.key: g.title for g in self.project.geometries}
        flow_map = {f.key: f for f in self.project.flows}

        # Clear existing tree
        self.plan_tree.delete(*self.plan_tree.get_children())
        self._plan_selected.clear()
        self._all_plan_rows.clear()

        if not self.project.plans:
            self.log("No plans found in project.")
            return

        for plan in self.project.plans:
            self._plan_selected[plan.key] = True

            geom_label = f"{plan.geom_ref}: {geom_map.get(plan.geom_ref, '?')}"
            flow_entry = flow_map.get(plan.flow_ref)
            flow_label = f"{plan.flow_ref}: {flow_entry.title}" if flow_entry else plan.flow_ref
            dss_label = ", ".join(flow_entry.dss_files) if flow_entry else ""

            row = (
                CHECK_MARK,
                plan.key,
                plan.title,
                geom_label,
                flow_label,
                dss_label,
                DASH,
                "View",
            )
            self._all_plan_rows.append(row)

            tags = ("current",) if plan.key == self.project.current_plan else ()
            self.plan_tree.insert("", "end", iid=plan.key, values=row, tags=tags)

        self.log(f"Loaded {len(self.project.plans)} plans from {self.project.title}")

        # Check for running HEC-RAS
        self._check_hecras_running()

    def _apply_filter(self) -> None:
        """Re-populate tree with rows matching per-column filter text (AND logic)."""
        f_title = self._filter_title.get().lower()
        f_geom = self._filter_geom.get().lower()
        f_flow = self._filter_flow.get().lower()

        self.plan_tree.delete(*self.plan_tree.get_children())

        if self.project is None:
            return

        for row in self._all_plan_rows:
            # row: (sel, key, title, geom, flow, dss, progress, log)
            if f_title and f_title not in row[_COL_TITLE].lower():
                continue
            if f_geom and f_geom not in row[_COL_GEOM].lower():
                continue
            if f_flow and f_flow not in row[_COL_FLOW].lower():
                continue

            plan_key = row[_COL_KEY]
            sel = CHECK_MARK if self._plan_selected.get(plan_key, False) else DASH

            # Preserve result status if available
            suffix = plan_key[1:] if plan_key.startswith("p") else ""
            result = self._plan_results.get(suffix)
            progress_val = row[_COL_PROGRESS]
            if result is not None:
                r_secs = int(result.elapsed_seconds)
                r_m, r_s = divmod(r_secs, 60)
                elapsed = f"{r_m}m{r_s}s" if r_m else f"{r_s}s"
                progress_val = f"\u2713 {elapsed}" if result.success else f"\u2717 {elapsed}"

            display_row = (
                sel,
                row[_COL_KEY],
                row[_COL_TITLE],
                row[_COL_GEOM],
                row[_COL_FLOW],
                row[_COL_DSS],
                progress_val,
                row[_COL_LOG],
            )

            # Build tags
            tags: list[str] = []
            if plan_key == (self.project.current_plan or ""):
                tags.append("current")
            if result is not None:
                tags.append("success" if result.success else "failure")

            self.plan_tree.insert("", "end", iid=plan_key, values=display_row, tags=tuple(tags))

    def _on_tree_click(self, event: tk.Event) -> None:
        """Handle clicks on selection column (toggle) and log column (popup)."""
        region = self.plan_tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        col = self.plan_tree.identify_column(event.x)
        item = self.plan_tree.identify_row(event.y)
        if not item:
            return

        if col == "#1":  # sel column — toggle selection
            current = self._plan_selected.get(item, False)
            self._plan_selected[item] = not current
            new_sel = CHECK_MARK if not current else DASH
            values = list(self.plan_tree.item(item, "values"))
            values[_COL_SEL] = new_sel
            self.plan_tree.item(item, values=values)

        elif col == f"#{_COL_LOG + 1}":  # log column
            self._show_plan_log(item)

    def _show_plan_log(self, plan_key: str) -> None:
        """Show a popup with log messages filtered for a specific plan."""
        # Look up the plan title for filtering
        values = self.plan_tree.item(plan_key, "values")
        plan_title = values[_COL_TITLE] if len(values) > _COL_TITLE else plan_key

        # Filter log messages that mention this plan
        filtered = [m for m in self._log_messages if plan_title in m or plan_key in m]

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Log — {plan_title}")
        dialog.transient(self.root)
        dialog.geometry("600x400")

        text = scrolledtext.ScrolledText(dialog, font=("Courier", 9), wrap="word")
        text.pack(fill="both", expand=True, padx=5, pady=5)
        text.insert("1.0", "\n".join(filtered) if filtered else "(no log messages for this plan)")
        text.configure(state="disabled")

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=5, pady=5)

        def _copy() -> None:
            dialog.clipboard_clear()
            dialog.clipboard_append(text.get("1.0", "end-1c"))
            copy_btn.configure(text="Copied!")
            dialog.after(1500, lambda: copy_btn.configure(text="Copy"))

        copy_btn = ttk.Button(btn_frame, text="Copy", command=_copy)
        copy_btn.pack(side="left")
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side="right")

    def _select_all(self) -> None:
        for key in self._plan_selected:
            self._plan_selected[key] = True
        self._apply_filter()

    def _deselect_all(self) -> None:
        for key in self._plan_selected:
            self._plan_selected[key] = False
        self._apply_filter()

    # ── Parent HEC-RAS instance ──

    def _ensure_com_initialized(self) -> None:
        """Initialize COM on the main thread (once)."""
        if self._com_initialized:
            return
        try:
            pythoncom = importlib.import_module("pythoncom")
            pythoncom.CoInitialize()
            self._com_initialized = True
        except Exception:
            pass

    def _check_hecras_running(self) -> None:
        """After project load, detect running HEC-RAS and offer to open it."""
        pids = find_hecras_processes()
        if pids:
            self.log(f"Detected {len(pids)} running HEC-RAS process(es).")
            self.status_var.set(f"HEC-RAS running (PID: {', '.join(str(p) for p in pids)})")
        else:
            answer = messagebox.askyesno(
                "Open HEC-RAS?",
                "HEC-RAS is not currently running.\n\n"
                "Would you like to open this project in HEC-RAS?\n"
                "(Keeps it open so you can view results after simulation.)",
            )
            if answer:
                self._open_parent_hecras()

    def _open_parent_hecras(self) -> None:
        """Open HEC-RAS with the current project as parent instance."""
        self._ensure_com_initialized()
        try:
            self._parent_ras = open_parent_instance(self.project_path.get(), log=self.log)
            self.status_var.set("HEC-RAS opened (parent instance)")
        except Exception as e:
            self.log(f"Could not open HEC-RAS: {e}")
            self._parent_ras = None

    def _refresh_parent_hecras(self) -> None:
        """Refresh parent HEC-RAS to show new results."""
        if self._parent_ras is None:
            return
        try:
            refresh_parent_instance(self._parent_ras, self.project_path.get(), log=self.log)
        except Exception:
            self.log("Parent HEC-RAS is no longer available.")
            self._parent_ras = None

    def _on_close(self) -> None:
        """Handle window close — optionally close parent HEC-RAS."""
        # Stop worker if active
        if self._worker_mode.get():
            self._stop_worker()

        # Stop worker polling
        self._worker_polling_active = False

        # Close DB connection
        if self._db_client is not None:
            with contextlib.suppress(Exception):
                self._db_client.close()  # type: ignore[attr-defined]

        if self._parent_ras is not None:
            answer = messagebox.askyesno(
                "Close HEC-RAS?",
                "A parent HEC-RAS instance is open.\n\nClose HEC-RAS as well?",
            )
            if answer:
                with contextlib.suppress(Exception):
                    self._parent_ras.QuitRas()  # type: ignore[attr-defined]
            self._parent_ras = None

        if self._com_initialized:
            try:
                pythoncom = importlib.import_module("pythoncom")
                pythoncom.CoUninitialize()
            except Exception:
                pass

        self.root.destroy()

    # ── Local Execution ──

    def _execute(self) -> None:
        if not self.project_path.get():
            messagebox.showerror("Error", "Please select a project file")
            return

        if not os.path.exists(self.project_path.get()):
            messagebox.showerror("Error", "Project file does not exist")
            return

        if self.project is None:
            self._load_project(self.project_path.get())
            if self.project is None:
                return

        selected_keys = {key for key, sel in self._plan_selected.items() if sel}
        if not selected_keys:
            messagebox.showerror("Error", "Please select at least one plan")
            return

        selected_plans = [p for p in self.project.plans if p.key in selected_keys]

        self.execute_btn.config(state="disabled")
        self._plan_progress.clear()
        self._plan_results.clear()
        self.progress.configure(mode="indeterminate")
        self.progress.start(30)
        self.log_text.delete("1.0", "end")
        self._log_messages.clear()

        # Create progress queue for parallel mode
        self.progress_queue = multiprocessing.Queue()

        thread = threading.Thread(target=self._run_thread, args=(selected_plans,), daemon=True)
        thread.start()

    def _run_thread(self, plans: list) -> None:
        start_time = time.monotonic()
        results: list[SimulationResult] = []
        try:
            self.log("=" * 50)
            self.log("STARTING HEC-RAS SIMULATIONS")
            self.log("=" * 50)

            # Check HEC-RAS
            self.status_var.set("Checking HEC-RAS installation...")
            if not check_hecras_installed(log=self.log):
                self.log("ERROR: HEC-RAS is not properly installed or registered.")
                return

            jobs = [
                SimulationJob(
                    plan_name=plan.title,
                    plan_suffix=plan.key[1:],
                    dss_path=None,
                )
                for plan in plans
            ]

            self.status_var.set("Running simulations...")
            results = run_simulations(
                project_path=self.project_path.get(),
                jobs=jobs,
                parallel=self.run_parallel.get(),
                cleanup=self.cleanup_temp.get(),
                show_ras=False,
                log=self.log,
                progress_queue=self.progress_queue,
            )

            # Load compute messages in debug mode
            if self.debug_mode.get():
                self._load_compute_messages(plans)

        except Exception as e:
            self.log(f"Error during simulation: {e}")
            import traceback

            self.log(traceback.format_exc())
        finally:
            total_elapsed = time.monotonic() - start_time
            self.root.after(0, self._on_complete, results, total_elapsed)

    def _load_compute_messages(self, plans: list) -> None:
        prj_dir = os.path.dirname(self.project_path.get())
        basename = os.path.splitext(os.path.basename(self.project_path.get()))[0]
        for plan in plans:
            msg_file = os.path.join(prj_dir, f"{basename}.{plan.key}.computeMsgs.txt")
            if os.path.isfile(msg_file):
                self.log(f"\n--- Compute Messages for {plan.title} ---")
                try:
                    with open(msg_file, encoding="utf-8", errors="replace") as f:
                        self.log(f.read())
                except OSError as e:
                    self.log(f"Could not read {msg_file}: {e}")

    def _on_complete(self, results: list[SimulationResult], total_elapsed: float) -> None:
        self.execute_btn.config(state="normal")
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=100)
        self.progress_queue = None

        # Update plan table with results
        self._update_plan_results(results)

        # Log summary
        n_success = sum(1 for r in results if r.success)
        n_fail = len(results) - n_success
        mins, secs = divmod(int(total_elapsed), 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        self.log("=" * 50)
        self.log(f"COMPLETE: {n_success} succeeded, {n_fail} failed in {time_str}")
        self.log("=" * 50)

        self.status_var.set(f"Done: {n_success} OK, {n_fail} failed — {time_str}")

        # Refresh parent HEC-RAS
        self._refresh_parent_hecras()

    def _update_plan_results(self, results: list[SimulationResult]) -> None:
        """Update plan table rows with result status and coloring."""
        # Store results keyed by plan suffix
        for r in results:
            self._plan_results[r.plan_suffix] = r

        for item_id in self.plan_tree.get_children():
            values = list(self.plan_tree.item(item_id, "values"))
            plan_key = values[_COL_KEY] if len(values) > _COL_KEY else ""
            suffix = plan_key[1:] if plan_key.startswith("p") else ""

            result = self._plan_results.get(suffix)
            if result is None:
                continue

            # Format elapsed time
            r_secs = int(result.elapsed_seconds)
            r_mins, r_secs = divmod(r_secs, 60)
            elapsed_str = f"{r_mins}m{r_secs}s" if r_mins else f"{r_secs}s"

            # Update progress column
            if result.success:
                values[_COL_PROGRESS] = f"\u2713 {elapsed_str}"
                tag = "success"
            else:
                values[_COL_PROGRESS] = f"\u2717 {elapsed_str}"
                tag = "failure"

            # Preserve "current" tag if applicable
            existing_tags = list(self.plan_tree.item(item_id, "tags"))
            new_tags = [t for t in existing_tags if t not in ("success", "failure")]
            new_tags.append(tag)
            self.plan_tree.item(item_id, values=values, tags=new_tags)


def main() -> None:
    root = tk.Tk()
    HECRASParallelRunnerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
