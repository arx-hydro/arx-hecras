# HEC-RAS Parallel Runner

Parallel HEC-RAS simulation tool with GUI, packaged as a standalone Windows executable.

## What's New (v6)

- **PyInstaller packaging** — distributable `.exe` with no Python install required
- Two build targets:
  - `HECRAS_Parallel_Runner.spec` — windowed (no console)
  - `HECRAS_Parallel_Runner_Debug.spec` — with console for troubleshooting

## Files

| File | Purpose |
|------|---------|
| `hecras_gui_runner.py` | Tkinter GUI application |
| `run_hecras_parallel.py` | Headless CLI runner |
| `HECRAS_Parallel_Runner.spec` | PyInstaller spec — windowed exe |
| `HECRAS_Parallel_Runner_Debug.spec` | PyInstaller spec — console exe |

## Building

```
pip install pyinstaller pywin32
pyinstaller HECRAS_Parallel_Runner.spec
```

Output: `dist/HECRAS_Parallel_Runner.exe` (~16 MB)

## Usage

**From exe:** double-click `HECRAS_Parallel_Runner.exe`

**From source (GUI):**

```
python hecras_gui_runner.py
```

**From source (headless):**

```
python run_hecras_parallel.py
```

## Requirements

- HEC-RAS 6.6 installed on target machine
- For running from source: Python 3.x + `pywin32`

## Author

Siamak Farrokhzadeh — February 2026
