# arx-hecras — HEC-RAS Parallel Runner

## Overview
Python tool to run multiple HEC-RAS simulation plans in parallel. Supports two backends:
- **CLI** (default) — `Ras.exe -c` subprocess with HDF completion verification
- **COM** — legacy `win32com.client` automation (use `--use-com`)

Each plan runs in an isolated temp directory copy to avoid file locking conflicts, then results are copied back.

## Package Structure (`src/hecras_runner/`)

- **`parser.py`** — Parse `.prj`/`.p##`/`.g##`/`.u##` files into dataclasses. Zero external deps.
  - `parse_project(prj_path) -> RasProject` — main entry point
  - Dataclasses: `RasProject`, `PlanEntry` (incl. `sim_start`/`sim_end`), `GeomEntry`, `FlowEntry`
- **`file_ops.py`** — File operations: temp copy, DSS patching, result copy-back, cleanup
  - `copy_project_to_temp()`, `update_dss_paths()`, `copy_results_back()`, `cleanup_temp_dir()`
- **`monitor.py`** — Completion detection & progress monitoring. Zero hard deps (h5py optional).
  - `patch_write_detailed(plan_path)` — enable .bco output in plan file
  - `verify_hdf_completion(hdf_path)` — check .p##.hdf for "Finished/Completed Successfully" (h5py or binary fallback)
  - `monitor_bco(bco_path, ...)` — poll .bco file for progress timestamps
  - `parse_bco_timestep(line)` — extract timestamp from .bco line
- **`runner.py`** — Simulation execution with backend dispatch
  - `run_simulations(backend="cli"|"com")` — single entry point for both CLI and GUI
  - `run_hecras_cli()` — runs a single plan via `Ras.exe -c` (CLI backend)
  - `run_hecras_plan()` — runs a single plan via COM (COM backend)
  - `find_hecras_exe()` — locate Ras.exe (registry → PATH → common paths)
  - `check_hecras_installed(backend)` — dual-mode availability check
  - `SimulationJob` / `SimulationResult` dataclasses
- **`cli.py`** — argparse CLI entry point (`python -m hecras_runner`)
  - `--use-com` — select COM backend (default is CLI)
  - `--max-cores N` — limit cores per simulation (CLI backend)
  - `--timeout SECONDS` — per-plan timeout (default 7200)
- **`gui.py`** — Tkinter GUI; auto-populates plans from `.prj` file

## Key constraints
- **Windows-only** — CLI backend needs `Ras.exe`; COM backend needs `pywin32`
- **HEC-RAS 6.6** — CLI: `Ras.exe -c`; COM ProgID: `RAS66.HECRASController`
- CLI sets `Current Plan=` in .prj before launch (Ras.exe ignores plan argument in 6.6)
- Exit code 0 from Ras.exe is NOT reliable — always verify HDF completion
- Core modules (parser, file_ops, monitor) have zero external deps for QGIS plugin reuse

## Dependencies
- Core: none (stdlib only)
- Optional: `pywin32` (COM backend), `h5py` (HDF verification, falls back to binary scan)
- Dev: `pytest`, `ruff`, `pyinstaller`

## Repository Layout

```
src/hecras_runner/     # Python package
tests/                 # Unit tests (114 tests, no HEC-RAS needed)
  synthetic/           # Minimal hand-crafted test project
test_projects/         # Real HEC-RAS project for integration tests
  small_project_01.*   # 2D unsteady flow model (4 plans, 1 geometry)
  Terrain/existing_01/ # Clipped 1m terrain (EPSG:32640)
docs/                  # Architecture and reference documentation
  db_schema.sql        # PostgreSQL schema for distributed job queue
```

## Testing
- `pytest` runs 115 unit tests (no HEC-RAS needed)
- `pytest -m integration` for 3 integration tests (requires HEC-RAS 6.6)
- Test project: `test_projects/small_project_01.*` (2D unsteady, UTM 40N)
- Synthetic data: `tests/synthetic/minimal.*` (minimal hand-crafted)

## Linting
- `ruff check src/ tests/` — lint
- `ruff format src/ tests/` — format
- Config in `pyproject.toml`: py313, line-length 100, rules E/W/F/I/N/UP/B/SIM/RUF

## Database (distributed job queue)
- Schema: `hecras_runner` on `hydro_arx_dev` RDS instance
- Tables: `workers`, `batches`, `jobs`, `metrics`, `schema_version`
- Service account: `hecras_runner` (read/write on schema only)
- Migration: `docs/db_schema.sql` (run via psql)
- In-app auto-migration planned for Phase 3 (`src/hecras_runner/db.py`)

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
