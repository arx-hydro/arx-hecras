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
  - `SimulationJob` / `SimulationResult` dataclasses
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

## Repository Layout

```
src/hecras_runner/     # Python package
tests/                 # Unit tests (66 tests, no HEC-RAS needed)
  synthetic/           # Minimal hand-crafted test project
test_projects/         # Real HEC-RAS project for integration tests
  small_project_01.*   # 2D unsteady flow model (4 plans, 1 geometry)
  Terrain/existing_01/ # Clipped 1m terrain (EPSG:32640)
docs/                  # Architecture and reference documentation
```

## Testing
- `pytest` runs 66 unit tests (no HEC-RAS needed)
- `pytest -m integration` for 2 integration tests (requires HEC-RAS 6.6)
- Test project: `test_projects/small_project_01.*` (2D unsteady, UTM 40N)
- Synthetic data: `tests/synthetic/minimal.*` (minimal hand-crafted)

## Linting
- `ruff check src/ tests/` — lint
- `ruff format src/ tests/` — format
- Config in `pyproject.toml`: py313, line-length 100, rules E/W/F/I/N/UP/B/SIM/RUF

## HEC-RAS file extensions
- `.prj` — Project file
- `.g##` — Geometry, `.g##.hdf` — Geometry HDF (tracked: contains 2D mesh)
- `.p##` — Plan, `.p##.hdf` — Plan results HDF (gitignored)
- `.u##` — Unsteady flow, `.u##.hdf` — Unsteady flow HDF (gitignored)
- `.b##` — Boundary conditions (gitignored)
- `.bco##` — Boundary condition output (gitignored)
- `.x##` — Cross-section output (gitignored)
- `.ic.o##` — Initial condition output (gitignored)
- `.dss` — Data Storage System (input tracked via `!` override, output gitignored)
- `.rasmap` — RAS Mapper configuration (tracked)
