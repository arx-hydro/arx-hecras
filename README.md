# HEC-RAS Parallel Runner

First prototype for running HEC-RAS simulations in parallel using Python
multiprocessing and COM automation.

## Approach

Each HEC-RAS plan runs in its own process via COM. The user manually
duplicates the project into separate directories before running (e.g.
`Model/` and `Model1/`). Each process writes a log file for troubleshooting.

## Features

- Parallel execution via `multiprocessing.Process`
- Per-process log files with timestamped output
- `Processing_Status` polling for completion detection
- `multiprocessing.set_start_method('spawn')` for Windows compatibility

## Limitations

- Windows only (COM: `RAS66.HECRASController`)
- Requires manual project duplication before each run
- Hardcoded project paths — edit `main()` before use
- 1D models only (COM has no 2D support)
- No automatic result collection

## Requirements

- Python 3.x
- HEC-RAS 6.6
- `pywin32`

## Author

Siamak Farrokhzadeh — June 2025
