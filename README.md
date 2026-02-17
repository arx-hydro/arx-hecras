# HEC-RAS Parallel Runner

Parallel HEC-RAS execution with automated temp directory isolation.

## What's New (v2)

- **Automated temp directories** — no more manual project duplication
- `copy_project_to_temp()` clones the full project folder per plan
- `copy_results_to_main_project()` harvests results back by extension
- DSS file path patching in unsteady flow files (`.u15`, `.u17`)

## How It Works

1. Copies the entire HEC-RAS project folder to a temp directory per plan
2. Patches `DSS File=` paths in `.u` files for the temp location
3. Launches each plan as a separate process via COM
4. Waits for all processes to complete
5. Copies result files back to the original project directory

## Known Issues

- DSS path update runs inside the file copy loop (executes repeatedly per file)
- Result copy-back is missing `u` and `g` extensions from the list
- No temp directory cleanup after execution
- No HEC-RAS installation verification
- Hardcoded to HAFEET project paths

## Requirements

- Python 3.x
- HEC-RAS 6.6
- `pywin32`

## Author

Siamak Farrokhzadeh — June 2025
