# arx-hecras — HEC-RAS Parallel Runner

## Overview
Python tool to run multiple HEC-RAS simulation plans in parallel using COM automation. Each plan runs in an isolated temp directory copy to avoid file locking conflicts, then results are copied back.

## Package Structure (`src/hecras_runner/`)

- **`parser.py`** — Parse `.prj`/`.p##`/`.g##`/`.u##` files into dataclasses. Zero external deps.
  - `parse_project(prj_path) -> RasProject` — main entry point
  - Dataclasses: `RasProject`, `PlanEntry`, `GeomEntry`, `FlowEntry`
- **`file_ops.py`** — File operations: temp copy, DSS patching, result copy-back, cleanup
  - `copy_project_to_temp()`, `update_dss_paths()`, `copy_results_back()`, `cleanup_temp_dir()`
- **`runner.py`** — COM wrapper + orchestration (only module importing win32com via importlib)
  - `run_simulations()` — single entry point for both CLI and GUI
  - `run_hecras_plan()` — runs a single plan (multiprocessing target)
  - `SimulationJob` dataclass
- **`cli.py`** — argparse CLI entry point (`python -m hecras_runner`)
- **`gui.py`** — Tkinter GUI; auto-populates plans from `.prj` file

## Key constraints
- **Windows-only** — depends on COM (`pythoncom`, `win32com.client`) and HEC-RAS installation
- **HEC-RAS 6.6** — COM ProgID is `RAS66.HECRASController`
- COM has no 2D model support — future work should migrate to CLI execution
- Core modules (parser, file_ops) have zero external deps for QGIS plugin reuse

## Dependencies
- `pywin32` (provides `win32com.client` and `pythoncom`)
- Dev: `pytest`, `ruff`, `pyinstaller`

## Testing
- `pytest` runs 48 unit tests (no HEC-RAS needed)
- `pytest -m integration` for full simulation tests (requires HEC-RAS 6.6)
- Test data: `tests/PRtest1.*` (real project) + `tests/synthetic/` (minimal hand-crafted)

## Linting
- `ruff check src/ tests/` — lint
- `ruff format src/ tests/` — format
- Config in `pyproject.toml`: py313, line-length 100, rules E/W/F/I/N/UP/B/SIM/RUF

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
