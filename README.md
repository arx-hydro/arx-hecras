# HEC-RAS Parallel Runner

Cleaned up parallel runner with bug fixes and generic test project.

## What's New (v3)

- **Fixed:** DSS path update now runs once after all files are copied
- **Fixed:** Result copy-back now includes `u` and `g` extensions
- Switched to generic `C:\Test\PRtest1.prj` for development/testing
- Uses `Compute_Complete()` for polling (replacing `Processing_Status`)
- DSS patching targets `.u03`/`.u04` for the test project

## How It Works

1. Copies the HEC-RAS project to a temp directory per plan
2. Patches `DSS File=` paths in `.u` files (after full copy completes)
3. Launches each plan in a separate process via COM
4. Polls `Compute_Complete()` until done
5. Copies result files (`.p`, `.u`, `.x`, `.g`, `.c`, `.b`, `.bco`, `.dss`, `.ic.o`, `.hdf`) back

## Known Issues

- Mixed indentation (tabs/spaces) in `copy_project_to_temp()` and `run_simulations()`
- No temp directory cleanup
- No HEC-RAS installation check before running
- Hardcoded project paths — edit `run_simulations()` before use

## Requirements

- Python 3.x
- HEC-RAS 6.6
- `pywin32`

## Author

Siamak Farrokhzadeh — June 2025
