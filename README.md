# HEC-RAS Parallel Runner

Parallel HEC-RAS simulation tool with GUI, packaged as a standalone Windows executable.

## Package Structure

```
src/hecras_runner/
    __init__.py       # version
    parser.py         # Parse .prj/.p##/.g##/.u## files
    file_ops.py       # Temp copy, DSS patching, result copy-back
    runner.py         # COM wrapper + orchestration
    cli.py            # argparse CLI entry point
    __main__.py       # enables python -m hecras_runner
    gui.py            # Tkinter GUI
```

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Usage

**GUI (exe):** double-click `HECRAS_Parallel_Runner.exe`

**GUI (from source):**
```
python src/hecras_runner/gui.py
```

**CLI:**
```
python -m hecras_runner project.prj --list
python -m hecras_runner project.prj --all
python -m hecras_runner project.prj --plans plan01 plan03
python -m hecras_runner project.prj --all --sequential --no-cleanup
```

## Building

```
pip install -e ".[dev]"
pyinstaller HECRAS_Parallel_Runner.spec
```

Output: `dist/HECRAS_Parallel_Runner.exe`

## Testing

```
pytest              # unit tests (no HEC-RAS needed)
pytest -m integration  # requires HEC-RAS 6.6
```

## Requirements

- Python 3.13+
- HEC-RAS 6.6 installed on target machine (for running simulations)
- `pywin32` (COM automation)
