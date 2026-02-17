# Parallel Runner — Tool Evolution

History of Siamak Farrokhzadeh's HEC-RAS parallel runner, reconstructed from working files.

## Timeline

```
Parallel_HECRAS1.py   (Jun 2025)  v1  Manual directory separation
        |
Parallel_HECRAS.py    (Jun 2025)  v2  Automated temp directory isolation
        |
Parallel_HECRAS2.py   (Jun 2025)  v3  Bug fixes, generic test project
        |
hecras_parallel_runner.py (Feb 2026)  v4  Production hardening
        |
hecras_gui_runner.py  (Feb 2026)  v5  Full tkinter GUI
        |
PyInstaller specs     (Feb 2026)  v6  Packaged as .exe (~16 MB)
```

## Version Details

### v1 — First Prototype (`Parallel_HECRAS1.py`)

**Approach:** User manually duplicates the HEC-RAS project into separate directories (e.g. `Model/` and `Model1/`). Each plan runs in its own process.

**Key features:**
- `multiprocessing.Process` per plan
- Per-process log files (`plan1_log.txt`, `plan2_log.txt`)
- `Processing_Status` polling for completion
- `multiprocessing.set_start_method('spawn')` for Windows

**Limitations:** Manual directory duplication, no result collection, hardcoded paths.

**Tested against:** `DCP2_AB.prj` (real PINI project)

---

### v2 — Temp Directory Isolation (`Parallel_HECRAS.py`)

**What changed:** Automated the directory isolation that was manual in v1.

**New functions:**
- `copy_project_to_temp()` — clones full project folder to `HECRAS_*` temp dir
- `copy_results_to_main_project()` — harvests results back by extension+suffix
- `update_dss_path_in_u_files()` — patches DSS paths in `.u` files after copy

**Known bugs:**
- DSS update called inside the file copy loop (runs N times instead of once)
- Result copy-back missing `u` and `g` extensions
- No temp cleanup

**Tested against:** HAFEET project (`PB_M2.prj`, plans with suffixes 46/47)

---

### v3 — Bug Fixes (`Parallel_HECRAS2.py`)

**What changed:** Fixed the bugs from v2 and switched to a generic test project.

**Fixes:**
- DSS path update moved to after all files are copied
- Result copy-back now includes `u` and `g` extensions
- Switched from `Processing_Status` to `Compute_Complete()` for polling

**Remaining issues:** Mixed indentation (tabs/spaces), no cleanup, no install check.

**Tested against:** `C:\Test\PRtest1.prj` (generic test model)

> Note: `Parallel_HECRAS3.py` also exists — same code as v2 applied to a different run configuration of the HAFEET project. Not a distinct evolution step.

---

### v4 — Production Hardening (`hecras_parallel_runner.py`)

**What changed:** Made the tool reliable enough for distribution.

**New features:**
- `check_hecras_installed()` — verifies COM registration before running
- `QuitRas()` call after each simulation
- `CoUninitialize()` in `finally` blocks (prevents COM leaks)
- `cleanup_temp_dirs()` — removes temp directories after results are copied
- `resource_path()` — PyInstaller helper for bundled resources
- `try/finally` wrapping the full simulation pipeline

---

### v5 — Tkinter GUI (`hecras_gui_runner.py`)

**What changed:** Full graphical interface replacing hardcoded paths.

**GUI features:**
- File browser dialogs for `.prj` and `.dss` selection
- Plan configuration tree — add/remove plans with per-component suffixes
- Independent plan, geometry, and flow suffix fields
- Parallel vs sequential execution toggle
- Optional temp file cleanup checkbox
- Threaded execution (GUI doesn't freeze during simulation)
- Real-time scrolling log panel with timestamps
- Progress bar and status bar

**Architecture:** `HECRASParallelRunnerGUI` class (tkinter) runs simulation logic in a background thread. COM operations happen in child processes via `multiprocessing.Process`. Log messages pass through a `queue.Queue` to the UI thread.

---

### v6 — PyInstaller Packaging

**Spec files:**
- `HECRAS_Parallel_Runner.spec` — windowed exe (no console, `console=False`)
- `HECRAS_Parallel_Runner_Debug.spec` — console exe (`console=True`)

Both target `hecras_gui_runner.py` as the entry point. Output: `dist/HECRAS_Parallel_Runner.exe` (~16 MB). Distributed to team members as a standalone tool.

## All Versions Use COM

Every version uses `win32com.client.Dispatch("RAS66.HECRASController")` for execution. None have been migrated to CLI invocation. The research report recommends CLI (`Ras.exe -p <project> -c <plan>`) for 2D support and HEC-RAS 2025 forward-compatibility.

## Real Project Names Found in Code

These show the inconsistent naming the planned audit tool aims to solve:
- `proposed_UBRSMA45130_200_DCP3AA` / `proposed_UBRSMA45130_500_DCP3AA`
- `T1_100yrs_30CC_V01` / `T1_100yrs_30CC_03`
- `DCP2_AB.prj`
- `PB_M2.prj`
- Plan titles: `plan01`, `plan02`, `plan03`, `plan04`
- Geometry title: `geoBR`
- Flow titles: `unsteady01`–`unsteady04`
