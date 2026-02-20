"""HEC-RAS discovery — locate executables and manage parent instances."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from collections.abc import Callable

HECRAS_PROGID = "RAS66.HECRASController"

# Known HEC-RAS install locations (newest first)
_COMMON_PATHS = [
    r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe",
    r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
    r"C:\Program Files\HEC\HEC-RAS\6.4.1\Ras.exe",
    r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe",
    r"C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe",
]


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
    NOT call QuitRas -- this instance stays open for the user.
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
