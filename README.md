# HEC-RAS Parallel Runner

Tkinter GUI application for configuring and running HEC-RAS plans in parallel.

## What's New (v5)

- **Full GUI** with file browser dialogs — no more editing hardcoded paths
- **Per-plan configuration** — set plan, geometry, and flow suffixes independently
- **Parallel/sequential toggle** — run plans concurrently or one at a time
- **Optional temp cleanup** — checkbox to preserve or delete temp files
- **Threaded execution** — GUI stays responsive during simulation
- **Real-time log panel** — monitor progress with timestamped messages
- Headless `run_hecras_parallel.py` retained for scripted/CLI use

## Files

| File | Purpose |
|------|---------|
| `hecras_gui_runner.py` | Tkinter GUI application |
| `run_hecras_parallel.py` | Headless CLI runner |

## Usage

**GUI mode:**

```
python hecras_gui_runner.py
```

**Headless mode** (edit paths in script first):

```
python run_hecras_parallel.py
```

## Requirements

- Python 3.x
- HEC-RAS 6.6
- `pywin32`
- `tkinter` (included with Python)

## Author

Siamak Farrokhzadeh — February 2026
