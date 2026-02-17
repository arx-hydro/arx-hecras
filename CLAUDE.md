# arx-hecras — HEC-RAS Parallel Runner

## Overview
Python tool to run multiple HEC-RAS simulation plans in parallel using COM automation (`win32com.client`). Each plan runs in an isolated temp directory copy to avoid file locking conflicts, then results are copied back.

## Architecture
- **`run_hecras_parallel.py`** — Single-file script, all logic here
  - `run_simulations()` — Entry point; defines project paths, plans, launches processes
  - `copy_project_to_temp()` — Clones project to temp dir, patches DSS paths in `.u` files
  - `run_hecras_plan()` — COM automation via `RAS66.HECRASController` (runs per-process)
  - `update_dss_path_in_u_files()` — Rewrites `DSS File=` lines in unsteady flow files
  - `copy_results_to_main_project()` — Copies output files back by extension+suffix matching
- **`tests/`** — Full HEC-RAS project (PRtest1) with 4 plans, geometry, terrain, land cover

## Key constraints
- **Windows-only** — depends on COM (`pythoncom`, `win32com.client`) and HEC-RAS installation
- **HEC-RAS 6.6** — COM ProgID is `RAS66.HECRASController`
- Paths are currently hardcoded in `run_simulations()`
- PyInstaller `.spec` files reference `hecras_gui_runner.py` (not yet in repo)

## Dependencies
- `pywin32` (provides `win32com.client` and `pythoncom`)
- Python stdlib: `os`, `time`, `shutil`, `tempfile`, `multiprocessing`

## HEC-RAS file extensions
- `.prj` — Project file
- `.g##` — Geometry, `.g##.hdf` — Geometry HDF
- `.p##` — Plan, `.p##.hdf` — Plan results HDF
- `.u##` — Unsteady flow, `.u##.hdf` — Unsteady flow HDF
- `.b##` — Boundary conditions
- `.bco##` — Boundary condition output
- `.x##` — Cross-section output
- `.ic.o##` — Initial condition output
- `.dss` — Data Storage System (hydrologic timeseries)
- `.rasmap` — RAS Mapper configuration
