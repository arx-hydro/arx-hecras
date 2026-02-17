# HEC-RAS Automation Ecosystem — Research Summary

> Summarised from *HEC-RAS Automation Ecosystem Research Report*, PINI Group Engineering, February 2026.

## Two Approaches

| Approach | How It Works | 2D? | Platform | Future-Proof? |
|----------|-------------|-----|----------|---------------|
| **COM Controller** (Legacy) | Windows COM API (`HECRASController`) | No | Windows only | Uncertain |
| **File/HDF/CLI** (Modern) | Parse text files + HDF5 reading + CLI execution | Yes | Cross-platform* | Yes |

\* Cross-platform for data access; Windows required for simulation execution.

**Key finding:** The COM Controller has ZERO methods for 2D models and will not be extended. HEC-RAS 2025 is a ground-up C# rewrite with GPU acceleration and Linux/cloud targets. The COM controller was built for the old VB.NET codebase and its continuation is uncertain.

## Tier 1: Primary Contenders

### ras-commander (gpt-cmdr)

- **GitHub:** github.com/gpt-cmdr/ras-commander
- **PyPI:** `pip install ras-commander` (v0.88+)
- **Author:** William Mark Katzenmeyer, P.E., C.F.M.

The most comprehensive single library. Core capabilities:
- Project initialisation: load .prj, auto-discover plans/geometries/flows into DataFrames
- Plan execution: single, sequential, or parallel via command-line (not COM)
- Plan manipulation: clone plans, modify geometry/flow refs, computational settings
- HDF data extraction: 15+ specialised classes (mesh, cross-section, structures, pipes, pumps)
- Smart execution skip: detects current results, avoids unnecessary re-runs
- Remote execution: SSH, WinRM, Docker, AWS EC2, Azure backends
- MCP server integration (ras-commander-mcp)

**Key API classes:** RasPrj, RasCmdr, RasPlan, RasGeo, RasUnsteady, RasExamples, HdfResultsMesh, HdfResultsXsec, HdfResultsPlan, HdfMesh, HdfXsec, HdfStruc, HdfPipe, HdfPump, HdfBndry, HdfInfiltration.

**Limitations:** Bus factor ~1, pre-1.0 API, heavy dependency tree (h5py, numpy, pandas, scipy, xarray, geopandas, matplotlib, shapely, rasterstats, rtree). DSS support limited.

### rashdf (FEMA-FFRD)

- **GitHub:** github.com/fema-ffrd/rashdf (~11 stars)
- **PyPI:** `pip install rashdf` (v0.2.1)
- **Backing:** FEMA Future of Flood Risk Data (FFRD) initiative

Read-only Python library for HEC-RAS HDF5 output files. Exports geometry as GeoDataFrames, results as xarray DataArrays. Supports S3-hosted files. Functionality now incorporated into ras-commander.

**Limitation:** Read-only. Cannot modify models or run simulations.

### HEC-Commander (Notebook Suite)

- **GitHub:** github.com/gpt-cmdr/HEC-Commander

Jupyter notebook suite. Three components: RAS-Commander (parallel HEC-RAS execution across networked machines), HMS-Commander (HEC-HMS calibration), DSS-Commander (interactive Bokeh plots). Predecessor to ras-commander library. Still the only open-source tool for multi-machine parallel execution via Windows network shares.

## Tier 2: Specialist Tools

### DSS File Access

| Tool | Approach | DSS Version | Active? | Notes |
|------|----------|-------------|---------|-------|
| **hecdss** (USACE official) | ctypes/C | v7 | Yes (Nov 2025) | Recommended for new work |
| pydsstools | Cython/C | v6+v7 | Low (2021) | Most battle-tested, 93 stars |
| pyhecdss (CA DWR) | SWIG | v6 only | Deprecated | DSS v6 EOL Jul 2024 |
| pandss | Multi-engine | v6+v7 | Moderate | Unified API over others |

### Geometry File Parsing

- **parserasgeo** (github.com/mikebannis/parserasgeo): Parses/edits .g01 geometry files (cross-sections, bridges, culverts, Manning's n). Unrecognised lines round-tripped safely. Ideal for Monte Carlo / sensitivity analysis.

### Auto-Calibration

- **raspy-cal** (github.com/quantum-dan/raspy-cal): Genetic algorithm calibration of Manning's n. Peer-reviewed (Water, 2021). Steady-state only. COM-based (Windows).

## Tier 3: Legacy and Niche

| Tool | Interface | 1D/2D | Status | Notes |
|------|-----------|-------|--------|-------|
| rascontrol | COM wrapper | 1D | Low activity | Use with parserasgeo |
| PyRAS | COM + parser | 1D | Dead (2015) | Skip |
| raspy | COM | 1D steady | Low | Basis for raspy-cal |
| pyHMT2D | HDF5 + VTK | 2D only | Academic | Penn State |
| HaD-to-Py | HDF5 + DSS | Both | Academic | UC Davis calibration |
| PyRASFile | File parsing | 1D | Niche | Flow profile batches |

## Master Comparison Matrix

| Tool | Interface | 1D | 2D | Edit Geo | Run | Results | X-Plat | Active |
|------|-----------|----|----|----------|-----|---------|--------|--------|
| ras-commander | File/HDF/CLI | Yes | Yes | Plans | Yes | HDF | Partial | High |
| rashdf | HDF5 | Yes | Yes | No | No | HDF | Yes | Med |
| HEC-Commander | File/DSS/CLI | Yes | Yes | Plans | Yes | DSS | No | Med |
| parserasgeo | File parse | Yes | No | Yes | No | No | Yes | Low |
| hecdss | ctypes/C | - | - | No | No | DSS | Yes | Med |
| COM Controller | COM/ActiveX | Yes | No | Ltd | Yes | COM | No | Stable |

## Recommended Stack for Heavy Automation

| Layer | Tool | Purpose |
|-------|------|---------|
| Core API | ras-commander | Project mgmt, plan execution, file manipulation, HDF extraction |
| DSS I/O | hecdss (USACE) | Boundary conditions, flow time series |
| Geometry edit | parserasgeo | Cross-section modification, Monte Carlo |
| Raster processing | rasterio / GDAL | Terrain, depth/WSE/velocity grids |
| Data analysis | pandas + xarray | Time series, structured results |
| Spatial analysis | geopandas | Geospatial operations on mesh/XS data |

## Key Gaps Requiring Original Work

- **Unsteady auto-calibration:** raspy-cal is steady-state only. No mature unsteady calibrator exists.
- **2D geometry creation:** No tool creates meshes/breaklines/flow areas programmatically.
- **Integrated HMS-to-RAS pipeline:** HEC-Commander does this via notebooks but not as a reusable API.
- **Cloud/HPC execution:** ras-commander has SSH/Docker/AWS backends but lightly tested.
- **Results validation framework:** No comprehensive automated model QA/QC framework exists.

## Key Sources

- github.com/gpt-cmdr/ras-commander
- github.com/fema-ffrd/rashdf
- github.com/gpt-cmdr/HEC-Commander
- github.com/HydrologicEngineeringCenter/hec-dss-python
- github.com/mikebannis/parserasgeo
- github.com/quantum-dan/raspy-cal
- ras-commander.readthedocs.io
- Goodell, C.R. (2014) *Breaking the HEC-RAS Code*
- Leon & Goodell (2016) Env. Modelling & Software, 84, 339-348
- Raspy-Cal: MDPI Water 13(21), 3061 (2021)
