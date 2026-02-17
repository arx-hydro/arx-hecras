# Codebase Analysis — Current State

> Analysis of arx-hecras as of February 2026, after tool-history merge.

## Repository Structure

```
arx-hecras/
├── run_hecras_parallel.py          # Headless CLI runner (v4)
├── hecras_gui_runner.py            # Tkinter GUI (v5)
├── HECRAS_Parallel_Runner.spec     # PyInstaller — windowed exe
├── HECRAS_Parallel_Runner_Debug.spec  # PyInstaller — console exe
├── README.md
├── CLAUDE.md
├── .gitignore
├── docs/                           # Research and analysis
└── tests/                          # PRtest1 HEC-RAS project
    ├── PRtest1.prj                 # Project file (4 plans, 1 geometry)
    ├── PRtest1.g01                 # Geometry (2D, 1095 mesh cells)
    ├── PRtest1.g01.hdf            # Compiled geometry HDF
    ├── PRtest1.p01–p04            # Plan files
    ├── PRtest1.u01–u04            # Unsteady flow files
    ├── PRtest1.b01–b04            # Boundary condition files
    ├── PRtest1.rasmap             # RAS Mapper config
    ├── 100yCC_2024.dss            # External HEC-HMS input (4.1 MB)
    ├── 00_projection/32640.prj    # UTM Zone 40N
    ├── Features/Profile Lines.*   # Profile line shapefiles
    ├── Flow_hydrograph/           # Input hydrograph spreadsheet
    ├── Terrain/existing_02/       # DEM (HDF + VRT)
    └── Land Classification/       # Land cover (HDF + TIF)
```

## How the Parallel Runner Works

### Core Flow (`run_hecras_parallel.py`)

```
run_simulations()
    │
    ├─ check_hecras_installed()          # Verify COM registration
    │
    ├─ for each plan:
    │   ├─ copy_project_to_temp()        # Clone to HECRAS_* temp dir
    │   │   └─ update_dss_path_in_u_files()  # Patch DSS paths
    │   └─ Process(target=run_hecras_plan)   # Launch COM in child process
    │
    ├─ join all processes                # Wait for completion
    │
    ├─ for each plan:
    │   └─ copy_results_to_main_project()  # Harvest by extension+suffix
    │
    └─ cleanup_temp_dirs()               # Remove temp directories
```

### Why Temp Directories?

HEC-RAS locks project files during computation. Running two plans against the same project folder causes file access conflicts. Each plan gets its own complete copy in a temp directory, runs in isolation, then results are copied back.

### COM Automation Sequence

```python
pythoncom.CoInitialize()
ras = win32com.client.Dispatch("RAS66.HECRASController")
ras.ShowRas()
ras.Project_Open(project_path)
ras.Plan_SetCurrent(plan_name)
ras.Compute_CurrentPlan()
while ras.Compute_Complete() == 0:
    time.sleep(5)
ras.Project_Close()
ras.QuitRas()
pythoncom.CoUninitialize()
```

### GUI Architecture (`hecras_gui_runner.py`)

- `HECRASParallelRunnerGUI` — main tkinter class
- Simulation runs in a background `threading.Thread`
- COM operations happen in child `multiprocessing.Process` instances
- Log messages flow: child process → `print()` | GUI thread → `queue.Queue` → log panel
- UI polling: `root.after(100, process_log_queue)` checks queue every 100ms

## Test Project Details

**PRtest1** — small 2D unsteady flow model in UTM Zone 40N (UAE/Oman region).

| Component | Title | Details |
|-----------|-------|---------|
| Geometry g01 | `geoBR` | 1 storage area ("Perimeter 1"), 2D, 1095 mesh points, Manning's n=0.06 |
| Flow u01 | `unsteady01` | Low flow — peak ~5 m³/s, 37 hourly intervals |
| Flow u02 | `unsteady02` | Medium flow — peak ~10 m³/s |
| Flow u03 | `unsteady03` | Medium flow — same as u02 (duplicate) |
| Flow u04 | `unsteady04` | High flow — peak ~20 m³/s |
| Plan p01 | `plan01` | g01 + u01, 01Jan–02Jan 2024 |
| Plan p02 | `plan02` | g01 + u02 |
| Plan p03 | `plan03` | g01 + u03 |
| Plan p04 | `plan04` | g01 + u04 |

All 4 plans share the same geometry and simulation period — only the flow input differs. This is the exact scenario the parallel runner is designed for.

## Known Issues

1. **COM is legacy** — no 2D support, uncertain future with HEC-RAS 2025 C# rewrite
2. **Headless runner still has hardcoded paths** — edit `run_simulations()` before use
3. **GUI log doesn't capture child process stdout** — `print()` in COM processes goes to console, not GUI log panel
4. **DSS path patching is extension-specific** — only targets `.u01`–`.u04`, not arbitrary suffixes
5. **No progress reporting** — GUI shows indeterminate progress bar, no per-plan status
6. **Result copy-back is aggressive** — copies any file newer in temp, not just simulation outputs

## Dependencies

| Package | Required By | Purpose |
|---------|------------|---------|
| `pywin32` | Both | `win32com.client`, `pythoncom` for COM automation |
| `tkinter` | GUI only | Standard library, included with Python |
| `pyinstaller` | Build only | Packaging to standalone .exe |

## HEC-RAS File Extension Reference

### Source Files (tracked in git)
- `.prj` — Project definition
- `.g##` — Geometry (text format)
- `.g##.hdf` — Compiled 2D geometry/mesh
- `.p##` — Plan definition
- `.u##` — Unsteady flow definition
- `.f##` — Steady flow definition
- `.b##` — Boundary condition definition
- `.rasmap` — RAS Mapper configuration

### Generated Output (gitignored)
- `.p##.hdf` — Plan results
- `.u##.hdf` — Compiled unsteady flow
- `.bco##` — Boundary condition output
- `.ic.o##` — Initial condition output
- `.x##` — Cross-section output
- `.dss` — Project output timeseries
- `.dsc.h5` — DSS catalog
- `.computeMsgs.txt` — Computation messages
- `.rasmap.backup` — RAS Mapper backup
- `systemInfoEncoded.txt` — Runtime artifact
