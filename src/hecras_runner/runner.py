"""COM wrapper and orchestration for HEC-RAS simulations."""

from __future__ import annotations

import importlib
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing import Process, Queue

from hecras_runner.file_ops import cleanup_temp_dir, copy_project_to_temp, copy_results_back

HECRAS_PROGID = "RAS66.HECRASController"


@dataclass
class SimulationJob:
    """Describes a single plan to run."""

    plan_name: str
    plan_suffix: str
    dss_path: str | None = None


@dataclass
class SimulationResult:
    """Result of a single plan simulation."""

    plan_name: str
    plan_suffix: str
    success: bool
    elapsed_seconds: float
    error_message: str | None = None
    files_copied: list[str] = field(default_factory=list)


def check_hecras_installed(log: Callable[[str], None] = print) -> bool:
    """Check if HEC-RAS is installed and its COM server is accessible."""
    try:
        pythoncom = importlib.import_module("pythoncom")
        win32com_client = importlib.import_module("win32com.client")

        pythoncom.CoInitialize()
        try:
            ras = win32com_client.Dispatch(HECRAS_PROGID)
            ras.QuitRas()
        finally:
            pythoncom.CoUninitialize()
        return True
    except Exception as e:
        log(f"HEC-RAS check failed: {e}")
        return False


# ── Parent instance management ──


def find_hecras_processes() -> list[int]:
    """Return PIDs of running Ras.exe processes."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Ras.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        pids: list[int] = []
        for line in result.stdout.strip().splitlines():
            # CSV format: "Ras.exe","1234","Console","1","123,456 K"
            parts = line.split(",")
            if len(parts) >= 2:
                pid_str = parts[1].strip().strip('"')
                try:
                    pids.append(int(pid_str))
                except ValueError:
                    continue
        return pids
    except (subprocess.SubprocessError, OSError):
        return []


def open_parent_instance(
    project_path: str,
    log: Callable[[str], None] = print,
) -> object:
    """Open HEC-RAS via COM, load project, return controller.

    The caller is responsible for COM initialization (CoInitialize) and should
    NOT call QuitRas — this instance stays open for the user.
    """
    win32com_client = importlib.import_module("win32com.client")

    ras = win32com_client.Dispatch(HECRAS_PROGID)
    ras.ShowRas()
    log(f"Opening project in HEC-RAS: {os.path.basename(project_path)}")
    ras.Project_Open(project_path)
    return ras


def refresh_parent_instance(
    ras: object,
    project_path: str,
    log: Callable[[str], None] = print,
) -> None:
    """Reopen project in existing controller to pick up new result files."""
    try:
        ras.Project_Open(project_path)  # type: ignore[attr-defined]
        log("Refreshed HEC-RAS project to show new results.")
    except Exception as e:
        log(f"Could not refresh HEC-RAS: {e}")


# ── Simulation execution ──


def run_hecras_plan(
    project_path: str,
    plan_name: str,
    show_ras: bool = True,
    log: Callable[[str], None] = print,
    result_queue: Queue | None = None,
) -> SimulationResult:
    """Run a single HEC-RAS plan via COM.

    This is a module-level function suitable as a ``multiprocessing.Process`` target.
    Handles CoInitialize/CoUninitialize internally.

    If *result_queue* is provided, the result is also put onto it (for parallel mode).
    """
    plan_suffix = ""
    # Extract suffix from project path context (e.g. "01" from plan key "p01")
    start = time.monotonic()
    try:
        pythoncom = importlib.import_module("pythoncom")
        win32com_client = importlib.import_module("win32com.client")

        pythoncom.CoInitialize()
        try:
            ras = win32com_client.Dispatch(HECRAS_PROGID)
            if show_ras:
                ras.ShowRas()

            log(f"[{plan_name}] Opening project: {os.path.basename(project_path)}")
            ras.Project_Open(project_path)
            time.sleep(3)

            log(f"[{plan_name}] Setting plan: {plan_name}")
            ras.Plan_SetCurrent(plan_name)
            time.sleep(2)

            log(f"[{plan_name}] Starting computation...")
            ras.Compute_CurrentPlan()

            while ras.Compute_Complete() == 0:
                log(f"[DEBUG] [{plan_name}] Computing...")
                time.sleep(5)

            log(f"[{plan_name}] Computation completed successfully!")
            ras.Project_Close()
            ras.QuitRas()

            elapsed = time.monotonic() - start
            result = SimulationResult(
                plan_name=plan_name,
                plan_suffix=plan_suffix,
                success=True,
                elapsed_seconds=elapsed,
            )

        finally:
            pythoncom.CoUninitialize()

    except Exception as e:
        elapsed = time.monotonic() - start
        log(f"[{plan_name}] ERROR: {e}")
        import traceback

        traceback.print_exc()
        result = SimulationResult(
            plan_name=plan_name,
            plan_suffix=plan_suffix,
            success=False,
            elapsed_seconds=elapsed,
            error_message=str(e),
        )

    if result_queue is not None:
        result_queue.put(result)
    return result


def run_simulations(
    project_path: str,
    jobs: list[SimulationJob],
    parallel: bool = True,
    cleanup: bool = True,
    show_ras: bool = True,
    log: Callable[[str], None] = print,
) -> list[SimulationResult]:
    """Run one or more HEC-RAS simulation jobs.

    Each job gets its own temp directory copy. Results are copied back
    after all simulations finish. Returns a list of SimulationResult.
    """
    project_path = os.path.abspath(project_path)
    main_dir = os.path.dirname(project_path)

    temp_entries: list[tuple[str, SimulationJob]] = []  # (temp_prj_path, job)
    results: list[SimulationResult] = []

    try:
        # 1. Create temp copies
        for job in jobs:
            log(f"\nPreparing {job.plan_name}...")
            temp_prj = copy_project_to_temp(project_path, dss_path=job.dss_path, log=log)
            temp_entries.append((temp_prj, job))

        # 2. Run simulations
        if parallel:
            result_queue: Queue = Queue()
            processes: list[Process] = []
            for temp_prj, job in temp_entries:
                p = Process(
                    target=run_hecras_plan,
                    args=(temp_prj, job.plan_name),
                    kwargs={"show_ras": show_ras, "result_queue": result_queue},
                )
                p.start()
                log(f"Started {job.plan_name} in parallel")
                processes.append(p)

            for p in processes:
                p.join()

            # Drain the queue
            while not result_queue.empty():
                results.append(result_queue.get_nowait())
        else:
            for temp_prj, job in temp_entries:
                result = run_hecras_plan(temp_prj, job.plan_name, show_ras=show_ras, log=log)
                results.append(result)

        log("\nAll simulations completed.")

        # 3. Copy results back and attach file lists to results
        # Build a lookup so we can attach files_copied to the right result
        result_by_name = {r.plan_name: r for r in results}
        for temp_prj, job in temp_entries:
            copied = copy_results_back(temp_prj, main_dir, job.plan_suffix, log=log)
            if job.plan_name in result_by_name:
                result_by_name[job.plan_name].files_copied = copied
                result_by_name[job.plan_name].plan_suffix = job.plan_suffix

        log("\nAll results copied to main project folder.")
        log("Open RAS Mapper and refresh to see new results.")

    except Exception as e:
        log(f"Error during simulation: {e}")
        import traceback

        traceback.print_exc()

    finally:
        if cleanup:
            log("\nCleaning up temporary files...")
            for temp_prj, _job in temp_entries:
                cleanup_temp_dir(os.path.dirname(temp_prj), log=log)

    return results
