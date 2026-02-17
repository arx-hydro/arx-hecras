# HEC-RAS Parallel Runner

Production-ready headless runner with installation checks and cleanup.

## What's New (v4)

- **HEC-RAS installation check** before running any simulations
- **Proper COM cleanup** — `QuitRas()` and `CoUninitialize()` in `finally` blocks
- **Temp directory cleanup** after all results are copied back
- **PyInstaller support** — `resource_path()` helper for packaged `.exe`
- Improved error handling with `try/finally` throughout

## How It Works

1. Verifies HEC-RAS 6.6 is installed and COM-registered
2. Copies the project to a temp directory per plan
3. Patches DSS paths in unsteady flow files
4. Launches parallel processes via COM
5. Copies result files back to the main project
6. Cleans up all temp directories

## Usage

Edit the paths in `run_simulations()`, then:

```
python run_hecras_parallel.py
```

## Requirements

- Python 3.x
- HEC-RAS 6.6
- `pywin32`

## Author

Siamak Farrokhzadeh — February 2026
