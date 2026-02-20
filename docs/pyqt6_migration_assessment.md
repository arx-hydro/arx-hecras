# PyQt6 Migration Assessment

**Date:** 2026-02-20
**Current framework:** Tkinter + ttk (Python stdlib)
**Proposed framework:** PyQt6
**GUI file:** `src/hecras_runner/gui.py` (1,328 lines)

---

## 1. Why Migrate?

| Issue | Tkinter | PyQt6 |
|-------|---------|-------|
| Visual quality | Windows 95/2000 aesthetic | Native Windows 11 look, DPI-aware |
| Widget richness | Basic (Treeview, ScrolledText) | Tables, docks, toolbars, charts, tabs |
| Styling | Minimal (ttk themes) | QSS stylesheets (CSS-like), full theming |
| HiDPI / scaling | Poor, manual workarounds | Automatic, first-class |
| Graphing / viz | None built-in | Multiple options (see section 3) |
| Layout system | pack/grid/place (fragile) | QVBoxLayout/QHBoxLayout/QGridLayout (robust) |
| Ecosystem | Shrinking | Large, active, commercially backed |

## 2. QGIS Compatibility — Risk Eliminated

**Previous concern:** QGIS bundled PyQt5, so PyQt6 would conflict in-process.

**Current status:** QGIS is migrating to Qt6.
- [QGIS 4.0 announced April 2025](https://blog.qgis.org/2025/04/17/qgis-is-moving-to-qt6-and-launching-qgis-4-0/) — Qt6 migration
- [QGIS 4.0 release February 2026](https://blog.qgis.org/2025/10/07/update-on-qgis-4-0-release-schedule-and-ltr-plans/) (delayed from Oct 2025)
- QGIS 4.0 uses **PyQt6 + SIP** for Python bindings (same as our proposal)
- QGIS 3.40 LTR extended to May 2026 for transition period
- [pyqgis4-checker](https://github.com/qgis/pyqgis4-checker) tool available for plugin migration

**Verdict:** PyQt6 is now the *correct* choice for future QGIS plugin compatibility. Our core library (parser, file_ops, monitor, runner) has zero GUI deps by design, so a QGIS plugin would import those modules and provide its own Qt-based UI.

## 3. Graphing & Visualization Options

PyQt6 gives us four paths for future charts/viz:

### 3.1 PyQtGraph (Recommended for our use case)
- [pyqtgraph.org](https://www.pyqtgraph.org/) — scientific/engineering graphics
- Built on Qt's QGraphicsScene — native integration, no embedding hacks
- Supports PyQt6 natively
- Excellent for: real-time simulation progress plots, time-series hydrographs, performance dashboards
- NumPy-backed for speed
- **Dependency:** `pyqtgraph` + `numpy`

### 3.2 Matplotlib (embedded)
- [Matplotlib in PyQt6](https://www.pythonguis.com/tutorials/pyqt6-plotting-matplotlib/)
- FigureCanvasQTAgg embeds matplotlib figures in Qt widgets
- Richer plot types but heavier dependency and slower rendering
- Better for static/publication-quality plots than real-time

### 3.3 Qt Charts / Qt Graphs (Official)
- [PyQt6-Charts](https://pypi.org/project/PyQt6-Charts/) — classic Qt Charts bindings
- [PyQt6-Graphs](https://pypi.org/project/PyQt6-Graphs/) — newer Qt Graphs (Oct 2025)
- Native Qt, no third-party deps beyond PyQt6
- Good for dashboards, but less flexible than PyQtGraph for scientific data
- **License note:** Qt Charts module has its own commercial licensing terms

### 3.4 Recommendation
**PyQtGraph** for engineering data (hydrographs, progress curves, mesh stats). Add matplotlib only if we need publication-quality static exports later. Both can coexist.

## 4. PyQt6 vs PySide6 — Decision

| Factor | PyQt6 | PySide6 |
|--------|-------|---------|
| License | **GPL** or commercial | **LGPL** (free for commercial) |
| Maintainer | Riverbank Computing | The Qt Company |
| QGIS compatibility | **Yes — QGIS 4.0 uses PyQt6** | No (would conflict) |
| API differences | Requires fully-qualified enums | Short + long enum names |
| Community | Larger, more tutorials | Growing, official docs |
| Maturity | More mature Python bindings | Catching up |

**Decision: PyQt6** — QGIS 4.0 alignment is the deciding factor. Licensing is not a concern since we distribute as a compiled exe (not as a library), and our source is in a private repo.

## 5. Risk Assessment

### Low Risk
| Risk | Mitigation |
|------|-----------|
| Learning curve | PyQt6 concepts (signals/slots, layouts) are well-documented. Team already knows Qt from QGIS. |
| Widget mapping | Every Tkinter widget we use has a direct PyQt6 equivalent (see section 7). |
| Threading model | Qt has QThread + signals, cleaner than Tkinter's `root.after()` polling. Multiprocessing stays the same. |
| Testing | Core modules have 115 unit tests with zero GUI deps. GUI tests (if any) need updating but core is unaffected. |

### Medium Risk
| Risk | Mitigation |
|------|-----------|
| PyInstaller bundle size | Tkinter exe ~16 MB. PyQt6 exe will be **~50-80 MB** (Qt libraries). Accept the increase or use `--exclude-module` to trim unused Qt modules. |
| COM thread affinity | COM requires `CoInitialize` on the calling thread. Tkinter uses `root.after()`; PyQt6 uses `QThread` + signals. Same pattern, different API. Test thoroughly. |
| PyInstaller hidden imports | Qt plugins (platforms, styles, imageformats) need correct bundling. Well-documented — use `--collect-all PyQt6`. |

### Low-Medium Risk (deferred)
| Risk | Mitigation |
|------|-----------|
| QGIS plugin reuse | Core library is already GUI-agnostic. A QGIS plugin would write its own Qt UI using QGIS's bundled PyQt6. No conflict. |
| PyQtGraph version compat | Some PySide6 6.9.1 issues [reported](https://github.com/pyqtgraph/pyqtgraph/issues/3323). PyQt6 is the more stable target for PyQtGraph. |

### Non-risks
- **Python version:** PyQt6 supports Python 3.13 (our target)
- **Windows-only:** Qt is cross-platform, but we only target Windows. No risk.
- **Existing core code:** Zero changes needed to parser.py, file_ops.py, monitor.py, runner.py, cli.py, db.py, settings.py

## 6. Migration Scope

### What changes
| Component | Effort | Notes |
|-----------|--------|-------|
| `gui.py` (1,328 lines) | **Full rewrite** | New file, same logic, PyQt6 widgets |
| `pyproject.toml` | Add `PyQt6` dep | New optional group `[gui]` |
| `HECRAS_Parallel_Runner.spec` | Update | New hidden imports, Qt plugin collection |
| `__main__.py` | Minor | `QApplication` instead of `tk.Tk` |

### What stays identical
- `parser.py`, `file_ops.py`, `monitor.py`, `runner.py` — zero changes
- `cli.py` — zero changes
- `db.py`, `settings.py`, `transfer.py`, `version_check.py` — zero changes
- All 115 unit tests — zero changes
- Integration tests — zero changes

## 7. Widget Mapping

| Tkinter | PyQt6 | Notes |
|---------|-------|-------|
| `tk.Tk` | `QMainWindow` | |
| `ttk.Frame` | `QWidget` / `QGroupBox` | |
| `ttk.Label` | `QLabel` | |
| `ttk.Button` | `QPushButton` | |
| `ttk.Entry` | `QLineEdit` | |
| `ttk.Checkbutton` | `QCheckBox` | |
| `ttk.Treeview` | `QTableWidget` / `QTableView` | QTableView + model for plan table |
| `ttk.PanedWindow` | `QSplitter` | |
| `ttk.Notebook` | `QTabWidget` | |
| `ttk.Progressbar` | `QProgressBar` | |
| `scrolledtext.ScrolledText` | `QPlainTextEdit` | |
| `filedialog.askopenfilename` | `QFileDialog.getOpenFileName` | |
| `messagebox.showerror` | `QMessageBox.critical` | |
| `tk.Toplevel` (modal) | `QDialog` | |
| `tk.StringVar` | Direct property / signal | No Variable wrapper needed |
| `tk.BooleanVar` | `QCheckBox.isChecked()` | |
| `root.after(ms, fn)` | `QTimer.singleShot(ms, fn)` | |
| `queue.Queue` + polling | `pyqtSignal` | Thread-safe by design |
| `tk.Canvas` (traffic light) | `QLabel` with stylesheet | Or custom `paintEvent` |

## 8. Architecture Improvements (free with migration)

1. **Signal/slot threading** — Replace `queue.Queue` + `root.after(100, poll)` with `pyqtSignal`. Cleaner, no 100ms polling latency.
2. **Model/View for plan table** — `QAbstractTableModel` + `QTableView` separates data from presentation. Filtering becomes `QSortFilterProxyModel` (built-in).
3. **Stylesheets** — Brand colours, dark mode, consistent spacing via `.qss` file.
4. **Status bar** — `QMainWindow.statusBar()` is built-in.
5. **Dock widgets** — Log panel could be a dockable `QDockWidget` (detach, resize, hide).
6. **Menu bar** — File > Open, Settings, Help > About — standard desktop app conventions.
7. **System tray** — Optional tray icon for worker mode (runs in background).

## 9. Migration Plan

### Phase 1: Scaffold (1-2 days)
- Add `PyQt6` to `pyproject.toml` optional deps `[gui]`
- Create `src/hecras_runner/gui_qt.py` alongside existing `gui.py`
- Implement `QMainWindow` shell: menu bar, splitter, tab widget, status bar
- Project file browser + plan table (QTableView + model)
- Wire up `parse_project()` to populate table
- Verify PyInstaller builds

### Phase 2: Local Execution (1 day)
- Port execution flow: select plans → run_simulations → show results
- Replace Queue polling with pyqtSignal for log messages and progress
- Port completion results display (tree tags → row colours)
- Port plan log popup (QDialog)
- Port checkboxes (parallel, cleanup, debug)

### Phase 3: Network Tab (1 day)
- Port DB connection modal (QDialog with form layout)
- Port worker tree, traffic light indicator
- Port worker mode toggle, distributed execution
- Port batch status polling (QTimer)

### Phase 4: Polish & Switchover (1 day)
- Add QSS stylesheet (clean modern theme)
- Add menu bar (File > Open, Settings, Help > About)
- Update PyInstaller spec for Qt
- Delete old `gui.py`, rename `gui_qt.py` → `gui.py`
- Update `__main__.py` entry point
- Test full workflow end-to-end

### Phase 5: Visualization (future, optional)
- Add `pyqtgraph` dependency
- Simulation progress chart (time vs % complete per plan)
- Hydrograph preview from DSS files
- Worker performance dashboard (distributed mode)

## 10. Estimated Impact

| Metric | Before (Tkinter) | After (PyQt6) |
|--------|------------------|---------------|
| gui.py lines | ~1,328 | ~1,200-1,500 (similar, cleaner) |
| External deps (GUI) | 0 | 1 (`PyQt6`) |
| Exe size | ~16 MB | ~50-80 MB |
| DPI scaling | Poor | Automatic |
| Visual quality | Dated | Modern native |
| Future viz capability | None | PyQtGraph, matplotlib, Qt Charts |
| QGIS plugin path | Blocked (Qt5 conflict) | Clear (both PyQt6) |
| Dark mode | Not possible | Stylesheet swap |

---

## Sources
- [QGIS Qt6 Migration Announcement](https://blog.qgis.org/2025/04/17/qgis-is-moving-to-qt6-and-launching-qgis-4-0/)
- [QGIS 4.0 Release Schedule Update](https://blog.qgis.org/2025/10/07/update-on-qgis-4-0-release-schedule-and-ltr-plans/)
- [PyQt6 vs PySide6 Comparison](https://www.pythonguis.com/faq/pyqt6-vs-pyside6/)
- [PyQt6 vs PySide6 Licensing](https://www.pythonguis.com/faq/pyqt-vs-pyside/)
- [PyQtGraph](https://www.pyqtgraph.org/)
- [Matplotlib in PyQt6](https://www.pythonguis.com/tutorials/pyqt6-plotting-matplotlib/)
- [PyQt6-Charts on PyPI](https://pypi.org/project/PyQt6-Charts/)
- [PyQt6-Graphs on PyPI](https://pypi.org/project/PyQt6-Graphs/)
- [PyQtGraph Qt6 compatibility](https://github.com/pyqtgraph/pyqtgraph)
- [QGIS pyqgis4-checker](https://github.com/qgis/pyqgis4-checker)
- [Packaging PyQt6 with PyInstaller](https://www.pythonguis.com/tutorials/packaging-pyqt6-applications-windows-pyinstaller/)
- [QtPy abstraction layer](https://github.com/spyder-ide/qtpy)
