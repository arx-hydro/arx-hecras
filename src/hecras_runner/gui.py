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
    SimulationJob,
    SimulationResult,
    check_hecras_installed,
    find_hecras_processes,
    open_parent_instance,
    refresh_parent_instance,
    run_simulations,
)

# Column definitions for plan table: (id, heading, width, anchor)
_PLAN_COLUMNS = [
    ("sel", "\u2713", 30, "center"),
    ("key", "Plan", 50, "center"),
    ("title", "Title", 120, "w"),
    ("geom", "Geometry", 150, "w"),
    ("flow", "Flow", 150, "w"),
    ("dss", "DSS Files", 200, "w"),
]

CHECK_MARK = "\u2713"
DASH = "\u2014"


class HECRASParallelRunnerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"HEC-RAS Parallel Runner v{__version__}")
        self.root.geometry("1100x750")

        self.project_path = tk.StringVar()
        self.dss_path = tk.StringVar()
        self.run_parallel = tk.BooleanVar(value=True)
        self.cleanup_temp = tk.BooleanVar(value=True)
        self.debug_mode = tk.BooleanVar(value=False)
        self.show_ras = tk.BooleanVar(value=True)
        self.filter_var = tk.StringVar()

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.project: RasProject | None = None
        self._plan_selected: dict[str, bool] = {}  # plan_key -> selected
        self._all_plan_rows: list[tuple[str, ...]] = []  # cached rows for filtering

        # Parent HEC-RAS instance
        self._parent_ras: object | None = None
        self._com_initialized = False

        self._create_widgets()
        self._process_log_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_widgets(self) -> None:
        # Main horizontal PanedWindow
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        # ── Left pane: controls ──
        left = ttk.Frame(paned)
        paned.add(left, weight=3)

        # Title
        ttk.Label(left, text="HEC-RAS Parallel Runner", font=("Arial", 16, "bold")).pack(
            pady=(10, 5)
        )

        # Project file row
        proj_frame = ttk.Frame(left)
        proj_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(proj_frame, text="Project (.prj):").pack(side="left")
        ttk.Entry(proj_frame, textvariable=self.project_path, width=45).pack(
            side="left", padx=5, fill="x", expand=True
        )
        ttk.Button(proj_frame, text="Browse...", command=self._browse_project).pack(side="left")

        # DSS override row
        dss_frame = ttk.Frame(left)
        dss_frame.pack(fill="x", padx=10, pady=2)
        ttk.Label(dss_frame, text="DSS Override:").pack(side="left")
        ttk.Entry(dss_frame, textvariable=self.dss_path, width=45).pack(
            side="left", padx=5, fill="x", expand=True
        )
        ttk.Button(dss_frame, text="Browse...", command=self._browse_dss).pack(side="left")

        # Plan table
        plan_frame = ttk.LabelFrame(left, text="Plan Selection", padding="5")
        plan_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Filter + select buttons row
        filter_row = ttk.Frame(plan_frame)
        filter_row.pack(fill="x", pady=(0, 3))
        ttk.Label(filter_row, text="Filter:").pack(side="left")
        filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var, width=20)
        filter_entry.pack(side="left", padx=5)
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Button(filter_row, text="Select All", command=self._select_all).pack(
            side="right", padx=2
        )
        ttk.Button(filter_row, text="Deselect All", command=self._deselect_all).pack(
            side="right", padx=2
        )

        # Treeview
        col_ids = [c[0] for c in _PLAN_COLUMNS]
        self.plan_tree = ttk.Treeview(
            plan_frame, columns=col_ids, show="headings", height=8, selectmode="none"
        )
        for col_id, heading, width, anchor in _PLAN_COLUMNS:
            self.plan_tree.heading(col_id, text=heading)
            self.plan_tree.column(col_id, width=width, minwidth=width // 2, anchor=anchor)

        # Bold tag for current plan
        self.plan_tree.tag_configure("current", font=("TkDefaultFont", 9, "bold"))

        tree_scroll = ttk.Scrollbar(plan_frame, orient="vertical", command=self.plan_tree.yview)
        self.plan_tree.configure(yscrollcommand=tree_scroll.set)
        self.plan_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Bind click on selection column
        self.plan_tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # Placeholder label (shown when no project loaded)
        self._tree_placeholder = ttk.Label(
            plan_frame, text="Browse a .prj file to load plans", foreground="gray"
        )
        self._tree_placeholder.place(relx=0.5, rely=0.5, anchor="center")

        # Execution options
        options_frame = ttk.LabelFrame(left, text="Execution Options", padding="5")
        options_frame.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(
            options_frame, text="Run plans in parallel", variable=self.run_parallel
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            options_frame,
            text="Clean up temporary files",
            variable=self.cleanup_temp,
        ).grid(row=0, column=1, sticky="w", padx=(20, 0))
        ttk.Checkbutton(options_frame, text="Show HEC-RAS window", variable=self.show_ras).grid(
            row=1, column=0, sticky="w"
        )
        ttk.Checkbutton(options_frame, text="Debug mode (verbose)", variable=self.debug_mode).grid(
            row=1, column=1, sticky="w", padx=(20, 0)
        )

        # Execute button + progress bar
        exec_frame = ttk.Frame(left)
        exec_frame.pack(fill="x", padx=10, pady=5)
        self.execute_btn = ttk.Button(
            exec_frame, text="EXECUTE SIMULATIONS", command=self._execute, width=30
        )
        self.execute_btn.pack(pady=(0, 5))
        self.progress = ttk.Progressbar(exec_frame, mode="indeterminate")
        self.progress.pack(fill="x")

        # ── Right pane: log ──
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        log_label = ttk.Label(right, text="Execution Log", font=("Arial", 10, "bold"))
        log_label.pack(anchor="w", padx=5, pady=(5, 2))

        self.log_text = scrolledtext.ScrolledText(
            right, width=40, height=20, font=("Courier", 9), wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # ── Status bar (outside paned window) ──
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, relief="sunken", anchor="w", padding=(5, 2)
        )
        status_bar.pack(fill="x", side="bottom")

    # ── Log handling ──

    def _process_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                if not self.debug_mode.get() and message.startswith("[DEBUG]"):
                    continue
                self.log_text.insert("end", f"{time.strftime('%H:%M:%S')} - {message}\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.root.after(100, self._process_log_queue)

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

    def _browse_dss(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select DSS File",
            filetypes=[("DSS files", "*.dss"), ("All files", "*.*")],
        )
        if filename:
            self.dss_path.set(filename)
            self.log(f"DSS file selected: {filename}")

    # ── Plan loading with table ──

    def _load_project(self, prj_path: str) -> None:
        try:
            self.project = parse_project(prj_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse project: {e}")
            return

        # Build lookup maps
        geom_map = {g.key: g.title for g in self.project.geometries}
        flow_map = {f.key: f for f in self.project.flows}

        # Clear existing tree
        self.plan_tree.delete(*self.plan_tree.get_children())
        self._plan_selected.clear()
        self._all_plan_rows.clear()

        if not self.project.plans:
            self._tree_placeholder.configure(text="No plans found in project", foreground="red")
            self._tree_placeholder.place(relx=0.5, rely=0.5, anchor="center")
            return

        # Hide placeholder
        self._tree_placeholder.place_forget()

        for plan in self.project.plans:
            self._plan_selected[plan.key] = True

            geom_label = f"{plan.geom_ref}: {geom_map.get(plan.geom_ref, '?')}"
            flow_entry = flow_map.get(plan.flow_ref)
            flow_label = f"{plan.flow_ref}: {flow_entry.title}" if flow_entry else plan.flow_ref
            dss_label = ", ".join(flow_entry.dss_files) if flow_entry else ""

            row = (CHECK_MARK, plan.key, plan.title, geom_label, flow_label, dss_label)
            self._all_plan_rows.append(row)

            tags = ("current",) if plan.key == self.project.current_plan else ()
            self.plan_tree.insert("", "end", iid=plan.key, values=row, tags=tags)

        self.log(f"Loaded {len(self.project.plans)} plans from {self.project.title}")

        # Check for running HEC-RAS
        self._check_hecras_running()

    def _apply_filter(self) -> None:
        """Re-populate tree with rows matching filter text."""
        text = self.filter_var.get().lower()
        self.plan_tree.delete(*self.plan_tree.get_children())

        if self.project is None:
            return

        for row in self._all_plan_rows:
            if text and not any(text in col.lower() for col in row):
                continue
            plan_key = row[1]
            sel = CHECK_MARK if self._plan_selected.get(plan_key, False) else DASH
            display_row = (sel, *row[1:])
            tags = ("current",) if plan_key == (self.project.current_plan or "") else ()
            self.plan_tree.insert("", "end", iid=plan_key, values=display_row, tags=tags)

    def _on_tree_click(self, event: tk.Event) -> None:
        """Toggle selection when clicking the checkmark column."""
        region = self.plan_tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        col = self.plan_tree.identify_column(event.x)
        if col != "#1":  # sel column
            return

        item = self.plan_tree.identify_row(event.y)
        if not item:
            return

        # Toggle
        current = self._plan_selected.get(item, False)
        self._plan_selected[item] = not current
        new_sel = CHECK_MARK if not current else DASH

        # Update the displayed row
        values = list(self.plan_tree.item(item, "values"))
        values[0] = new_sel
        self.plan_tree.item(item, values=values)

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

    # ── Execution ──

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
        self.progress.start()
        self.log_text.delete("1.0", "end")

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

            dss = self.dss_path.get() or None

            jobs = [
                SimulationJob(
                    plan_name=plan.title,
                    plan_suffix=plan.key[1:],
                    dss_path=dss,
                )
                for plan in plans
            ]

            self.status_var.set("Running simulations...")
            results = run_simulations(
                project_path=self.project_path.get(),
                jobs=jobs,
                parallel=self.run_parallel.get(),
                cleanup=self.cleanup_temp.get(),
                show_ras=self.show_ras.get(),
                log=self.log,
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
        self.status_var.set("Ready")
        self.log("=" * 50)
        self.log("SIMULATIONS COMPLETED")
        self.log("=" * 50)

        # Refresh parent HEC-RAS
        self._refresh_parent_hecras()

        # Show completion dialog
        self._show_completion_dialog(results, total_elapsed)

    def _show_completion_dialog(
        self, results: list[SimulationResult], total_elapsed: float
    ) -> None:
        """Show a modal dialog with per-plan simulation results."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Simulation Complete")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(True, True)

        n_success = sum(1 for r in results if r.success)
        n_fail = len(results) - n_success

        # Summary
        summary_frame = ttk.Frame(dialog, padding="10")
        summary_frame.pack(fill="x")

        mins, secs = divmod(int(total_elapsed), 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        ttk.Label(
            summary_frame,
            text=f"Completed in {time_str}",
            font=("Arial", 12, "bold"),
        ).pack(anchor="w")
        status_text = f"{n_success} succeeded"
        if n_fail:
            status_text += f", {n_fail} failed"
        ttk.Label(summary_frame, text=status_text).pack(anchor="w")

        # Results table
        if results:
            table_frame = ttk.Frame(dialog, padding="10")
            table_frame.pack(fill="both", expand=True)

            cols = ("plan", "status", "elapsed", "files")
            tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=len(results))
            tree.heading("plan", text="Plan")
            tree.heading("status", text="Status")
            tree.heading("elapsed", text="Elapsed")
            tree.heading("files", text="Files Copied")
            tree.column("plan", width=150)
            tree.column("status", width=80, anchor="center")
            tree.column("elapsed", width=80, anchor="center")
            tree.column("files", width=80, anchor="center")

            tree.tag_configure("success", foreground="green")
            tree.tag_configure("failure", foreground="red")

            for r in results:
                r_mins, r_secs = divmod(int(r.elapsed_seconds), 60)
                elapsed_str = f"{r_mins}m {r_secs}s" if r_mins else f"{r_secs}s"
                status = "OK" if r.success else "FAILED"
                tag = "success" if r.success else "failure"
                tree.insert(
                    "",
                    "end",
                    values=(r.plan_name, status, elapsed_str, len(r.files_copied)),
                    tags=(tag,),
                )
            tree.pack(fill="both", expand=True)

        # Error details
        failures = [r for r in results if not r.success and r.error_message]
        if failures:
            err_frame = ttk.LabelFrame(dialog, text="Error Details", padding="5")
            err_frame.pack(fill="x", padx=10, pady=5)
            for r in failures:
                ttk.Label(
                    err_frame,
                    text=f"{r.plan_name}: {r.error_message}",
                    foreground="red",
                    wraplength=400,
                ).pack(anchor="w", pady=2)

        # OK button
        ttk.Button(dialog, text="OK", command=dialog.destroy, width=15).pack(pady=10)

        # Center on parent
        dialog.update_idletasks()
        w = max(dialog.winfo_width(), 500)
        h = max(dialog.winfo_height(), 300)
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")


def main() -> None:
    root = tk.Tk()
    HECRASParallelRunnerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
