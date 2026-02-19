"""HEC-RAS simulation execution — CLI (default) and COM backends."""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing import Process, Queue

from hecras_runner.file_ops import cleanup_temp_dir, copy_project_to_temp, copy_results_back

HECRAS_PROGID = "RAS66.HECRASController"

# Known HEC-RAS install locations (newest first)
_COMMON_PATHS = [
    r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe",
    r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
    r"C:\Program Files\HEC\HEC-RAS\6.4.1\Ras.exe",
    r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe",
    r"C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe",
]


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


# ── HEC-RAS discovery ──


def find_hecras_exe(log: Callable[[str], None] = print) -> str | None:
    """Locate the HEC-RAS executable (Ras.exe).

    Search order:
    1. Windows registry (``HKLM\\SOFTWARE\\HEC\\HEC-RAS``)
    2. ``shutil.which("Ras.exe")`` (PATH lookup)
    3. Common installation paths
    """
    # 1. Registry scan
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\HEC\HEC-RAS") as reg_key:
            i = 0
            versions: list[str] = []
            while True:
                try:
                    versions.append(winreg.EnumKey(reg_key, i))
                    i += 1
                except OSError:
                    break

            if versions:
                latest = sorted(versions)[-1]
                try:
                    with winreg.OpenKey(reg_key, latest) as ver_key:
                        install_dir, _ = winreg.QueryValueEx(ver_key, "InstallDir")
                    candidate = os.path.join(install_dir, "Ras.exe")
                    if os.path.isfile(candidate):
                        log(f"Found HEC-RAS via registry: {candidate}")
                        return candidate
                except Exception:
                    pass
    except Exception:
        pass

    # 2. PATH lookup
    which_result = shutil.which("Ras.exe")
    if which_result:
        log(f"Found HEC-RAS on PATH: {which_result}")
        return which_result

    # 3. Common paths
    for path in _COMMON_PATHS:
        if os.path.isfile(path):
            log(f"Found HEC-RAS at common path: {path}")
            return path

    log("HEC-RAS executable not found")
    return None


def check_hecras_installed(
    backend: str = "cli",
    log: Callable[[str], None] = print,
) -> bool:
    """Check if HEC-RAS is available for the given backend.

    Parameters
    ----------
    backend : str
        ``"cli"`` checks for Ras.exe; ``"com"`` checks for COM server.
    """
    if backend == "cli":
        return find_hecras_exe(log=log) is not None

    # COM backend
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
        log(f"HEC-RAS COM check failed: {e}")
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


# ── CLI backend helpers ──

_SIM_DATE_RE = re.compile(r"^Simulation Date=(.+)$", re.MULTILINE)


def _parse_sim_dates(plan_path: str) -> tuple[str, str]:
    """Extract simulation start and end from ``Simulation Date=`` line.

    Returns ``(start, end)`` strings, e.g.
    ``("01JAN2024,0000", "02JAN2024,1200")``.
    Returns ``("", "")`` if not found.
    """
    try:
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ("", "")

    m = _SIM_DATE_RE.search(text)
    if not m:
        return ("", "")

    parts = m.group(1).strip().split(",")
    if len(parts) >= 4:
        return (f"{parts[0]},{parts[1]}", f"{parts[2]},{parts[3]}")
    return ("", "")


def _kill_process_tree(pid: int, log: Callable[[str], None] = print) -> None:
    """Kill a process and all its children via ``taskkill /F /T``."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=30,
        )
        log(f"Killed process tree for PID {pid}")
    except (subprocess.SubprocessError, OSError) as e:
        log(f"Failed to kill PID {pid}: {e}")


def run_hecras_cli(
    project_path: str,
    plan_suffix: str,
    plan_name: str = "",
    ras_exe: str | None = None,
    max_cores: int | None = None,
    timeout_seconds: float = 7200.0,
    log: Callable[[str], None] = print,
    on_progress: Callable[[float, str], None] | None = None,
    result_queue: Queue | None = None,
    **_kwargs: object,
) -> SimulationResult:
    """Run a single HEC-RAS plan via ``Ras.exe -c``.

    This is a module-level function suitable as a ``multiprocessing.Process`` target.

    Parameters
    ----------
    project_path : str
        Path to the .prj file (typically a temp copy).
    plan_suffix : str
        Plan suffix, e.g. ``"01"`` for ``p01``.
    plan_name : str
        Human-readable plan title (for logging / result).
    ras_exe : str, optional
        Path to Ras.exe. If None, calls ``find_hecras_exe()``.
    max_cores : int, optional
        If set, adds ``-MaxCores N`` flag.
    timeout_seconds : float
        Seconds before killing the process.
    log : callable
        Logging callback.
    on_progress : callable, optional
        Progress callback ``(fraction, timestamp)``. If provided, a daemon thread
        monitors the .bco file.
    result_queue : Queue, optional
        If provided, the result is also put onto it (for parallel mode).
    """
    from hecras_runner.monitor import monitor_bco, patch_write_detailed, verify_hdf_completion

    start = time.monotonic()

    if not ras_exe:
        ras_exe = find_hecras_exe(log=log)
    if not ras_exe:
        result = SimulationResult(
            plan_name=plan_name,
            plan_suffix=plan_suffix,
            success=False,
            elapsed_seconds=0.0,
            error_message="HEC-RAS executable not found",
        )
        if result_queue is not None:
            result_queue.put(result)
        return result

    # Build plan file reference (e.g. "p01")
    plan_file = f"p{plan_suffix}"
    label = plan_name or plan_file

    prj_dir = os.path.dirname(project_path)
    basename = os.path.splitext(os.path.basename(project_path))[0]

    # Build command as a shell string — Ras.exe requires shell=True on Windows
    # Plan arg is the plan filename (e.g. "small_project_01.p01")
    plan_filename = f"{basename}.{plan_file}"
    cmd = f'"{ras_exe}" -c "{project_path}" "{plan_filename}"'
    if max_cores is not None:
        cmd += f" -MaxCores {max_cores}"
    cmd += " -hideCompute"

    log(f"[{label}] Running: {cmd}")

    # Patch Write Detailed for .bco monitoring
    plan_path = os.path.join(prj_dir, f"{basename}.{plan_file}")
    hdf_path = os.path.join(prj_dir, f"{basename}.{plan_file}.hdf")

    # Delete pre-existing HDF to avoid false positives from previous runs
    if os.path.isfile(hdf_path):
        try:
            os.remove(hdf_path)
            log(f"[{label}] Removed pre-existing HDF: {os.path.basename(hdf_path)}")
        except OSError:
            pass

    if on_progress:
        patch_write_detailed(plan_path)

    # Parse simulation dates for .bco monitoring
    sim_start, sim_end = _parse_sim_dates(plan_path)

    # Start the process
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            cwd=prj_dir,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as e:
        elapsed = time.monotonic() - start
        result = SimulationResult(
            plan_name=plan_name,
            plan_suffix=plan_suffix,
            success=False,
            elapsed_seconds=elapsed,
            error_message=f"Failed to start Ras.exe: {e}",
        )
        if result_queue is not None:
            result_queue.put(result)
        return result

    # Optional .bco monitoring in a daemon thread
    monitor_thread = None
    if on_progress and sim_start and sim_end:
        bco_suffix = f"bco{plan_suffix}"
        bco_path = os.path.join(prj_dir, f"{basename}.{bco_suffix}")
        monitor_thread = threading.Thread(
            target=monitor_bco,
            args=(bco_path, sim_start, sim_end, on_progress),
            kwargs={"timeout": timeout_seconds},
            daemon=True,
        )
        monitor_thread.start()

    # Wait for completion
    try:
        proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        log(f"[{label}] Timeout after {timeout_seconds}s — killing process tree")
        _kill_process_tree(proc.pid, log=log)
        proc.wait(timeout=30)
        elapsed = time.monotonic() - start
        result = SimulationResult(
            plan_name=plan_name,
            plan_suffix=plan_suffix,
            success=False,
            elapsed_seconds=elapsed,
            error_message=f"Timeout after {timeout_seconds}s",
        )
        if result_queue is not None:
            result_queue.put(result)
        return result

    elapsed = time.monotonic() - start

    # Exit code 0 is NOT reliable — verify HDF for ground truth
    success = verify_hdf_completion(hdf_path)
    error_msg = None

    if not success:
        stderr_text = ""
        if proc.stderr:
            stderr_text = proc.stderr.read().decode("utf-8", errors="replace").strip()
        error_msg = (
            f"HDF completion check failed (exit code {proc.returncode})"
            + (f": {stderr_text}" if stderr_text else "")
        )
        log(f"[{label}] {error_msg}")
    else:
        log(f"[{label}] Completed successfully in {elapsed:.1f}s")

    result = SimulationResult(
        plan_name=plan_name,
        plan_suffix=plan_suffix,
        success=success,
        elapsed_seconds=elapsed,
        error_message=error_msg,
    )

    if result_queue is not None:
        result_queue.put(result)
    return result


# ── COM backend ──


def run_hecras_plan(
    project_path: str,
    plan_name: str,
    show_ras: bool = True,
    log: Callable[[str], None] = print,
    result_queue: Queue | None = None,
    plan_suffix: str = "",
    **_kwargs: object,
) -> SimulationResult:
    """Run a single HEC-RAS plan via COM.

    This is a module-level function suitable as a ``multiprocessing.Process`` target.
    Handles CoInitialize/CoUninitialize internally.

    If *result_queue* is provided, the result is also put onto it (for parallel mode).
    """
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
                log(f"[{plan_name}] Computing...")
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


# ── Orchestration ──


def run_simulations(
    project_path: str,
    jobs: list[SimulationJob],
    parallel: bool = True,
    cleanup: bool = True,
    show_ras: bool = True,
    log: Callable[[str], None] = print,
    backend: str = "cli",
    ras_exe: str | None = None,
    max_cores: int | None = None,
    timeout_seconds: float = 7200.0,
    on_progress: Callable[[float, str], None] | None = None,
) -> list[SimulationResult]:
    """Run one or more HEC-RAS simulation jobs.

    Each job gets its own temp directory copy. Results are copied back
    after all simulations finish. Returns a list of SimulationResult.

    Parameters
    ----------
    backend : str
        ``"cli"`` (default) uses ``Ras.exe -c``; ``"com"`` uses COM automation.
    ras_exe : str, optional
        Path to Ras.exe (CLI backend only). Auto-detected if None.
    max_cores : int, optional
        Limit cores per simulation (CLI backend only).
    timeout_seconds : float
        Per-plan timeout in seconds (CLI backend only, default 7200).
    on_progress : callable, optional
        Progress callback for CLI backend.
    """
    project_path = os.path.abspath(project_path)
    main_dir = os.path.dirname(project_path)

    # Resolve ras_exe once for CLI backend
    if backend == "cli" and not ras_exe:
        ras_exe = find_hecras_exe(log=log)

    # Select the runner function based on backend
    run_fn = run_hecras_cli if backend == "cli" else run_hecras_plan

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
                kwargs: dict[str, object] = {"result_queue": result_queue}
                if backend == "cli":
                    kwargs.update(
                        plan_suffix=job.plan_suffix,
                        plan_name=job.plan_name,
                        ras_exe=ras_exe,
                        max_cores=max_cores,
                        timeout_seconds=timeout_seconds,
                        # on_progress omitted: callbacks are not picklable
                        # across multiprocessing.Process on Windows (spawn).
                    )
                    p = Process(
                        target=run_fn,
                        args=(temp_prj,),
                        kwargs=kwargs,
                    )
                else:
                    kwargs.update(
                        show_ras=show_ras,
                        plan_suffix=job.plan_suffix,
                    )
                    p = Process(
                        target=run_fn,
                        args=(temp_prj, job.plan_name),
                        kwargs=kwargs,
                    )
                p.start()
                log(f"Started {job.plan_name} in parallel")
                processes.append(p)

            for p in processes:
                p.join()

            # Collect results (one per job, blocking get is reliable after join)
            for _ in temp_entries:
                results.append(result_queue.get())
        else:
            for temp_prj, job in temp_entries:
                if backend == "cli":
                    result = run_fn(
                        temp_prj,
                        plan_suffix=job.plan_suffix,
                        plan_name=job.plan_name,
                        ras_exe=ras_exe,
                        max_cores=max_cores,
                        timeout_seconds=timeout_seconds,
                        log=log,
                        on_progress=on_progress,
                    )
                else:
                    result = run_fn(
                        temp_prj,
                        job.plan_name,
                        show_ras=show_ras,
                        log=log,
                        plan_suffix=job.plan_suffix,
                    )
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
