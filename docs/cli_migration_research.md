# HEC-RAS CLI Migration Research Report

**Date:** 2026-02-19
**Prepared for:** Arx Engineering — arx-hecras parallel runner refactoring
**Based on:** 10 parallel research agents covering CLI syntax, ras-commander, completion detection, Azure, AWS, Windows network distribution, on-premise server, HEC-RAS 2025, network probing, and existing codebase analysis.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [CLI Syntax (The 5 Unknowns — Resolved)](#2-cli-syntax-the-5-unknowns--resolved)
3. [Use Case 1: Cloud (Azure / AWS)](#3-use-case-1-cloud-azure--aws)
4. [Use Case 2: Colleague Laptops (Corporate Network)](#4-use-case-2-colleague-laptops-corporate-network)
5. [Use Case 3: Dedicated On-Premise Server](#5-use-case-3-dedicated-on-premise-server)
6. [HEC-RAS 2025: The Game Changer](#6-hec-ras-2025-the-game-changer)
7. [ras-commander: Learn, Don't Adopt](#7-ras-commander-learn-dont-adopt)
8. [Architecture Recommendation](#8-architecture-recommendation)
9. [Cost Comparison Matrix](#9-cost-comparison-matrix)
10. [Implementation Roadmap](#10-implementation-roadmap)
11. [Sources](#11-sources)

---

## 1. Executive Summary

Migrating from COM to CLI execution is both necessary and straightforward. The CLI command is confirmed: `Ras.exe -c "project.prj" "plan.pXX"`. This works headless, supports 2D models, and eliminates the `pywin32` dependency.

For **500+ plans at hours each**, the three deployment models are all viable with different trade-offs:

| Deployment | Cost (100 plans x 2hr) | Setup Effort | Best For |
|------------|----------------------|--------------|----------|
| **Cloud (Spot)** | $33-80/run | Medium (2-4 weeks) | Burst capacity, infrequent large batches |
| **Colleague laptops** | $0 (hardware exists) | Low-Medium (1-3 weeks) | Overnight runs, small-medium batches |
| **On-premise server** | ~$15k upfront, ~$1.5k/yr | Medium (hardware procurement) | Sustained daily workloads |

**HEC-RAS 2025** changes everything: new CLI (`ras prepare` + `ras solve`), GPU acceleration (14-35x speedup), Linux support, and a completely new HDF5-based project format. However, it's alpha software with no implicit solver until ~2027. Design for both 6.x and 2025.

---

## 2. CLI Syntax (The 5 Unknowns — Resolved)

### Unknown 1: Exact `Ras.exe` CLI Syntax

**HEC-RAS 6.6 — Full CLI Reference** (confirmed from `Ras.exe -h` output):

```
File Parameters:
  Optional project filename (must have quotes)
  Optional plan filename (must have quotes)

Parameters:
  -c          Run current plan (or specified plan) then exit
  -a          Run ALL plans in the project then exit
  -test       Copy project to [Test] folder, run all plans, then close
  -MaxCores   Upper limit on cores (use with -test)
  -Clean2DTables   Clear 2D property tables in [Test] folder (use with -test)
  -CleanIBTables   Clear BR/Culvert/Weir tables in [Test] folder (use with -test)
  -inProcess       Run pre-process in Ras process memory (faster for small projects)
  -NoPilot         Remove pilot channels from test compute
  -FV1D            Override 1D solver with Finite Volume 1D approach
  -hWndComputeProgress=n   Report progress to Windows handle n
  -hWndComputeMessages=n   Report messages to Windows handle n
  -hideCompute     Hide the compute window during batch computes
  -mouseWheelOff   Disable mouse wheel in plots/tables
  -h / -help       Show help
```

**Key invocation patterns:**
```bash
# Run a specific plan headless:
Ras.exe -c "project.prj" "plan.p01" -hideCompute

# Run ALL plans sequentially:
Ras.exe -a "project.prj" -hideCompute

# Run in test mode (copies to [Test] folder, runs all plans):
Ras.exe -test "project.prj" -MaxCores 8 -Clean2DTables
```

**Notable discoveries:**
- **`-a` flag** runs ALL plans sequentially — useful for validation, but not for parallel execution
- **`-test` flag** has its own temp-directory isolation (appends `[Test]`) — similar to our pattern!
- **`-hideCompute`** hides the compute window — use this for headless server execution
- **`-hWndComputeProgress=n`** and **`-hWndComputeMessages=n`** — progress/message reporting via Windows message handles (could enable real-time progress without .bco polling if we create a message window)
- **`-MaxCores`** — limits core usage per simulation (critical for parallel execution on shared machines)
- **`-inProcess`** — skips launching a separate pre-process executable (faster for small models)
- File parameters **must be in quotes**
- Confirmed by ras-commander source (`RasCmdr.compute_plan()`) and direct `Ras.exe -h` output

**HEC-RAS 2025 (new architecture):**
```bash
ras prepare -p project.ras --plan "PlanName" -o Results/plan.h5
ras solve -r Results/plan.h5
```

- Two-step process: `prepare` ingests data into a single self-contained `.h5`, `solve` computes it
- `solve` writes progress to stdout: `Computing... Progress: 99%`
- The single `.h5` is a perfect unit of work for distributed systems

### Unknown 2: Completion Detection

**Exit codes are unreliable.** Exit code 0 does NOT guarantee simulation success.

**Definitive completion check** (priority order):
1. **HDF verification** — read `Results/Summary/Compute Messages (text)` from `.p##.hdf`, check for `"Complete Process"` string
2. **`.bco` file** — the computation log file, written incrementally during simulation; contains volume accounting summary near end
3. **Exit code** — catches crashes (non-zero), but 0 is necessary-not-sufficient
4. **`.p##.hdf` existence** — file only created on completion (unless `HDF Flush=1`)

**For HEC-RAS 2025:** stdout parsing is sufficient — `ras solve` prints `Progress: 100%` and `Computations completed in Xm Xs`.

### Unknown 3: Error Reporting

| Failure Mode | Detection | Recovery |
|-------------|-----------|----------|
| Clean failure (solver error) | Non-zero exit code | Retry or skip |
| Silent failure (bad results) | Volume accounting error in `.bco` / HDF > threshold | Flag for review |
| Crash (access violation) | Exit codes 157, -1073741571 | Retry; check file locks |
| Hang (infinite loop) | Timeout watchdog | Kill process tree (`taskkill /F /T /PID`) |
| Partial output | No `.p##.hdf` produced | Retry |

**Critical: kill the process tree, not just Ras.exe.** It spawns child processes (`RASGeomPreprocess.exe`, `RasUnsteady.exe`, `RasProcess.exe`).

### Unknown 4: Progress Feedback

**HEC-RAS 6.x:** No stdout output. Monitor the `.bco` file:
- Enable `Write Detailed= 1` in `.p##` plan file before launch
- Poll `.bco` every 0.5-1.0 seconds using `seek()` to read only new content
- Parse simulation time from timestep messages
- Estimate progress: `(current_time - start_time) / (end_time - start_time)`

**HEC-RAS 2025:** stdout provides `Progress: XX%` directly.

### Unknown 5: Adopt ras-commander or Roll Our Own?

**Verdict: Learn from it, do not depend on it.**

| Factor | Assessment |
|--------|-----------|
| CLI execution pattern | Proven, validated — copy the approach |
| Distributed execution | Well-designed worker abstraction — study as reference |
| Maturity | Pre-1.0, solo developer, 90 releases in 17 months, no test suite |
| Dependencies | 15+ packages including geopandas/GDAL — incompatible with our zero-dep core |
| License | MIT — compatible |
| Bus factor | 1 (William Katzenmeyer) |

**What to extract:**
- CLI invocation: `Ras.exe -c` via `subprocess.Popen()` (from `RasCmdr.compute_plan()`)
- `.bco` monitoring: poll pattern with seek (from `RasBco.BcoMonitor`)
- HDF verification: check `"Complete Process"` in compute messages (from `HdfResultsPlan`)
- Worker abstraction: remote worker interface design (from `remote/RasWorker.py`)

---

## 3. Use Case 1: Cloud (Azure / AWS)

### Architecture: Azure Batch / AWS Batch with Spot VMs

Both platforms support the identical pattern:

```
Upload project to object storage (S3 / Blob)
    → Batch service provisions Spot VMs from custom image (HEC-RAS pre-installed)
        → Each VM downloads its plan, runs Ras.exe -c, uploads results
            → Orchestrator collects results, notifies on completion
                → VMs auto-terminate (scale to 0)
```

### Cost Comparison (100 plans x 2 hours each, HEC-RAS 6.6)

| | AWS | Azure |
|---|---|---|
| **Recommended VM** | c5.4xlarge (16 vCPU, 32 GB) | D8s_v5 (8 vCPU, 32 GB) |
| **On-Demand (Windows)** | ~$210 | ~$129 |
| **Spot (Windows)** | ~$80 | ~$33 |
| **Batch service** | Free | Free |
| **Storage** | ~$12/mo (S3) | ~$5/mo (Blob) |
| **Orchestration** | Step Functions (~$0.50) | Built-in Batch |

### Future with HEC-RAS 2025 (Linux + GPU)

| | AWS | Azure |
|---|---|---|
| **GPU VM** | g5.xlarge (A10G, 24 GB) | NC4as_T4_v3 (T4, 16 GB) |
| **Spot cost** | ~$0.35/hr | ~$0.24/hr |
| **100 plans x ~12 min (GPU)** | ~$5-18 | ~$5 |
| **Linux savings** | 30-45% cheaper (no Windows license) | Same |

### Key Facts

- **HEC-RAS is public domain** — zero licensing restrictions on cloud deployment
- **USACE themselves** are building a cloud compute framework on AWS (`USACE/cloudcompute`)
- Existing Docker images: `slawler/ras-docker` (USACE-affiliated)
- **Spot is safe**: HEC-RAS plans are independent and restartable; Batch auto-retries on eviction
- **Cloud is NOT cheaper per-simulation than local hardware** — the value is parallelism (100+ simultaneous)

### When to Use Cloud

- Infrequent but massive batches (200+ plans, several times per year)
- Need results ASAP (all 500 plans finish in 2 hours wall-clock instead of days)
- No upfront capital expenditure desired
- Testing HEC-RAS 2025 on Linux/GPU without buying hardware

---

## 4. Use Case 2: Colleague Laptops (Corporate Network)

### Recommended Approach: Phased

**Phase 1 (zero IT friction): SMB shared drive file queue**
- Central machine writes job files to `\\SERVER\hecras_queue\`
- Worker machines poll/watch the folder, pick up jobs using atomic file rename as lock
- Workers copy project to local disk, run `Ras.exe -c`, write results to `\\SERVER\hecras_results\`
- No firewall changes, no admin rights, no special services

**Phase 2 (low IT friction): HTTP worker service**
- Lightweight FastAPI/Flask worker on each machine (packaged as .exe via PyInstaller)
- Central orchestrator posts jobs via HTTP
- Worker downloads files, runs simulation, uploads results
- Web dashboard shows progress across all machines
- One firewall port exception per machine (or fall back to file queue)

**Phase 3 (nice-to-have): Wake-on-LAN + auto-retry**
- Wake sleeping machines via WoL packets
- Automatic retry on failure
- Result validation
- Teams/Slack notification on completion

### Critical Constraint

**HEC-RAS MUST execute from local disk, not network share.** HDF5 random I/O over SMB is 5-10x slower and unreliable. Every approach must:
1. Copy project files to worker's local `%TEMP%\HECRAS_xxxx\`
2. Run simulation locally
3. Copy results back to network share

This maps directly to our existing `file_ops.py` temp directory isolation pattern.

### Distribution Approaches Ranked

| Rank | Approach | IT Friction | Reliability | Setup Time |
|------|----------|-------------|-------------|------------|
| 1 | HTTP Worker Service | Low (1 firewall port) | High | 2-4 weeks |
| 2 | Shared Drive File Queue | Zero | Medium | 1-2 weeks |
| 3 | Python `multiprocessing.managers` | Zero | Medium | 1-2 weeks |
| 4 | ZeroMQ | Low (1 port) | High | 2-3 weeks |
| 5 | WinRM | Medium-High | High | 2-4 weeks |
| 6 | SSH (OpenSSH) | Medium | High | 2-3 weeks |
| 7 | Dask Distributed | Low | Medium | 2-3 weeks |
| 8 | PSExec | **Do not use** | — | — |

### Network Probe Script

A network probe script has been designed (see `docs/network_probe_design.md`) to test what your corporate network supports before committing to an approach. It checks:
- SMB shares, WinRM, SSH, PowerShell remoting, RDP availability
- Machine discovery (ARP, ping sweep, NetBIOS)
- Current user permissions and domain membership
- HEC-RAS installation on discovered machines

Output: traffic-light report (GREEN/YELLOW/RED) per approach.

### When to Use Colleague Laptops

- Regular overnight batch runs (50-200 plans)
- No budget for server hardware or cloud costs
- Machines already have HEC-RAS installed
- 5-10 available machines provides meaningful parallelism

---

## 5. Use Case 3: Dedicated On-Premise Server

### Recommended Build: Tier 2 ($15,250)

| Component | Specification | Cost |
|-----------|---------------|------|
| CPU | AMD Threadripper PRO 7975WX (32 cores, 4.0 GHz) | $5,500 |
| RAM | 256 GB DDR5-5600 ECC | $1,200 |
| GPU 1 | NVIDIA RTX 4090 (24 GB) | $2,800 |
| GPU 2 | NVIDIA RTX 4090 (24 GB) — optional | $2,800 |
| Boot SSD | 1 TB NVMe Gen4 | $100 |
| Work SSD | 4 TB NVMe Gen4 (sim working space) | $350 |
| Results | 8 TB SATA SSD | $500 |
| PSU | 1600W 80+ Platinum | $400 |
| Case + Cooling | Full tower + 360mm AIO | $450 |
| UPS | 1500VA line-interactive | $300 |
| OS | **Windows 11 Pro for Workstations** | $350 |

**Why Windows 11 Pro, not Server:** HEC-RAS 2025 GPU solver requires Windows 11, not Server. Also $4,850 cheaper in licensing.

### Capacity

| Mode | Concurrent Jobs | Throughput |
|------|----------------|------------|
| CPU only (6.6) | 8 plans (4 cores each) | ~96 plans/day (2hr each) |
| GPU only (2025) | 2 plans (1 per GPU) | ~240 plans/day (12min each) |
| Hybrid | 6 CPU + 2 GPU | ~330 plans/day |

### Job Queue Architecture

**Recommended: SQLite + FastAPI**
- SQLite for persistent job queue (survives reboots)
- FastAPI serves web dashboard + REST API + WebSocket progress
- `ProcessPoolExecutor` manages worker processes
- Engineers submit jobs via browser (`http://hecras-server:8000`)

### 3-Year TCO Comparison

| | On-Premise (Tier 2) | AWS On-Demand | AWS Reserved | AWS Spot |
|---|---|---|---|---|
| Year 1 | $16,750 | $35,160 | $21,000 | $8,320 |
| Year 2 | $1,500 | $35,160 | $21,000 | $8,320 |
| Year 3 | $1,500 | $35,160 | $21,000 | $8,320 |
| **3-Year Total** | **$19,750** | **$105,480** | **$63,000** | **$24,960** |

On-premise pays for itself in **5-6 months** vs cloud on-demand. Cloud Spot is competitive only for infrequent use.

### When to Use On-Premise

- Sustained daily workloads (50+ plans/week consistently)
- Need GPU acceleration for HEC-RAS 2025
- Want predictable costs (no per-run charges)
- Data sensitivity concerns about cloud
- Can justify $15k capex

---

## 6. HEC-RAS 2025: The Game Changer

### What's Confirmed

| Feature | Status |
|---------|--------|
| Complete C#.NET rewrite | Confirmed (5+ years in development) |
| Alpha publicly available | Yes (since Sept 2024, ~90 MB portable zip) |
| GPU solver (NVIDIA CUDA 12.4) | Yes (14-35x speedup confirmed) |
| New CLI (`ras prepare` + `ras solve`) | Confirmed and documented |
| New `.ras` HDF5 project format | Confirmed (breaking change from `.prj` text) |
| Linux headless execution | Design goal, demonstrated |
| COM Controller | **Not present** in 2025 |
| DSS7 only (DSS6 dropped) | Confirmed |
| Docker + S3 integration | Design goal |
| C# API (replacing COM) | In development, no public docs yet |

### What's NOT Ready Yet

| Gap | Expected |
|-----|----------|
| Implicit 2D solver | ~2027 |
| 1D solver | Not in current roadmap |
| Full function parity with 6.x | ~2027-2028 |
| Stable file format | Not yet (still changing in alpha) |
| Linux GPU support | Planned but not shipped |
| Official v1.0 release | Target Fall 2025, likely slipping |

### Impact on Our Architecture

| Component | HEC-RAS 6.x | HEC-RAS 2025 |
|-----------|-------------|--------------|
| `parser.py` | Text files (.prj/.p##/.g##/.u##) | **Rewrite needed** — HDF5-based `.ras` format |
| `runner.py` | COM or `Ras.exe -c` | `ras prepare` + `ras solve` subprocess |
| `file_ops.py` | Copy entire project dir to temp | **Simplified** — `prepare` produces single `.h5` |
| Dependencies | `pywin32` for COM | **None** — subprocess only |
| Distributed compute | Copy project dir to worker | Copy single `.h5` to worker (ideal) |
| Progress monitoring | Poll `.bco` file | Parse stdout (`Progress: XX%`) |

### Strategy: Support Both

HEC-RAS 6.x will remain in production for years (implicit solver gap, 1D gap, model recalibration required). Design a **version-aware runner**:

```python
if hecras_version >= "2025":
    # New CLI: prepare + solve
    run_ras2025(project_ras, plan_name, output_h5)
else:
    # Legacy CLI: Ras.exe -c
    run_ras6x(project_prj, plan_pXX)
```

---

## 7. ras-commander: Learn, Don't Adopt

| Aspect | Assessment |
|--------|-----------|
| **CLI execution** | Validated — `Ras.exe -c` via subprocess is correct |
| **Temp dir isolation** | Same pattern as ours — validates our approach |
| **Remote execution** | Well-designed worker abstraction (PsExec, SSH, WinRM, Docker, AWS, Azure) |
| **HDF reading** | Comprehensive (derived from FEMA's `rashdf`) |
| **Dependencies** | 15+ packages (geopandas, scipy, xarray...) — incompatible with our zero-dep core |
| **Maturity** | 0.89.1, solo developer, no test suite, API unstable |
| **License** | MIT — no restrictions |

**Use it as a reference implementation. Don't add it to our dependency chain.**

---

## 8. Architecture Recommendation

### The Unified Runner

Refactor `runner.py` into a **backend-agnostic execution layer**:

```
SimulationJob (input)
    │
    ├── LocalBackend (this machine)
    │   ├── ras6x_cli()    → Ras.exe -c
    │   ├── ras2025_cli()  → ras prepare + ras solve
    │   └── ras6x_com()    → legacy COM (kept for compatibility)
    │
    ├── NetworkBackend (colleague laptops)
    │   ├── http_worker()  → POST to remote FastAPI worker
    │   └── smb_queue()    → drop job file on shared drive
    │
    └── CloudBackend (Azure / AWS)
        ├── azure_batch()  → submit to Azure Batch
        └── aws_batch()    → submit to AWS Batch
    │
SimulationResult (output)
```

### What Stays the Same

- `parser.py` — unchanged for 6.x (new parser needed for 2025, but later)
- `file_ops.py` — temp dir isolation pattern preserved; extended for network/cloud copy
- `SimulationJob` / `SimulationResult` dataclasses — backend-agnostic already
- GUI / CLI entry points — just select backend

### Monitoring Architecture

```
PRE-LAUNCH:
  • Patch plan: Write Detailed= 1 (6.x only)
  • Record time window from plan file

DURING:
  • 6.x: Poll .bco file every 0.5s, estimate progress from timestep
  • 2025: Parse stdout for Progress: XX%
  • Both: Timeout watchdog, process tree management

POST:
  • Check exit code (non-zero = hard failure)
  • Verify .p##.hdf exists
  • Read HDF compute messages, check "Complete Process"
  • Parse volume accounting error %
  • Extract per-process timing
```

---

## 9. Cost Comparison Matrix

### Per-Run Cost (100 plans x 2 hours each)

| Deployment | HEC-RAS 6.6 (today) | HEC-RAS 2025 GPU (future) |
|------------|---------------------|--------------------------|
| **Colleague laptops (10 machines)** | $0 (20hr wall-clock) | $0 (2hr wall-clock) |
| **On-premise server (Tier 2)** | ~$1 electricity | ~$0.50 electricity |
| **Azure Spot** | ~$33 | ~$5 |
| **AWS Spot** | ~$80 | ~$5-18 |
| **Azure On-Demand** | ~$129 | ~$40 |
| **AWS On-Demand** | ~$210 | ~$50 |

### 3-Year Total Cost of Ownership (weekly batch runs)

| Deployment | Setup Cost | Annual Cost | 3-Year Total |
|------------|-----------|-------------|--------------|
| **Colleague laptops** | ~$2k (software dev) | $0 | ~$2,000 |
| **On-premise server** | ~$15k (hardware) | ~$1.5k | ~$19,500 |
| **Cloud Spot (Azure)** | ~$3k (infra setup) | ~$1.7k (52 runs) | ~$8,100 |
| **Cloud On-Demand** | ~$3k (infra setup) | ~$6.7k (52 runs) | ~$23,100 |

---

## 10. Implementation Roadmap

### Phase 1: CLI Migration (Weeks 1-3)
**Goal:** Replace COM with CLI in `runner.py`

1. Add `run_hecras_cli()` function: `subprocess.Popen("Ras.exe -c ...")`
2. Add `.bco` file monitor thread for progress
3. Add HDF verification (`"Complete Process"` check)
4. Add timeout watchdog with process tree kill
5. Keep COM as fallback (feature flag)
6. Update `check_hecras_installed()` to find `Ras.exe` path
7. Remove `pywin32` as hard dependency (make optional)
8. Test with `small_project_01` (4 plans)

### Phase 2: Local Parallelism Upgrade (Weeks 3-5)
**Goal:** Improve parallel execution on single machine

1. Replace `multiprocessing.Process` + Queue with `concurrent.futures.ProcessPoolExecutor`
2. Add CPU core affinity (pin plans to core groups)
3. Add proper progress reporting to GUI
4. Fix known bugs (queue drain race, suffix bug, exit code propagation)
5. Run 66 unit tests + 2 integration tests

### Phase 3: Network Distribution (Weeks 5-9)
**Goal:** Run plans on colleague laptops

1. Build network probe script (test what's available)
2. Implement SMB file queue (Phase 1 — zero friction)
3. Build HTTP worker service (Phase 2 — better monitoring)
4. Package worker as PyInstaller `.exe`
5. Build simple web dashboard (FastAPI + SQLite)
6. Test with 2-3 machines

### Phase 4: Cloud Integration (Weeks 9-13)
**Goal:** Burst to cloud for large batches

1. Build custom Windows AMI/image with HEC-RAS 6.6
2. Set up Azure Batch (or AWS Batch) with Spot pool
3. Add `CloudBackend` to runner (S3/Blob upload → Batch submit → collect results)
4. Test with 50+ plans
5. Add "Run on Cloud" option to GUI

### Phase 5: HEC-RAS 2025 Support (When Stable)
**Goal:** Add 2025 as an execution target

1. Implement `ras prepare` + `ras solve` backend
2. Build new HDF5-based project parser for `.ras` format
3. Test GPU execution on on-premise server
4. Switch cloud backend to Linux containers + GPU VMs
5. Maintain 6.x compatibility (version-aware dispatch)

---

## 11. Sources

### Official USACE Documentation
- [HEC-RAS 2025 Official Page](https://www.hec.usace.army.mil/software/hec-ras/2025/)
- [Future of HEC-RAS (HEC News Fall 2024)](https://www.hec.usace.army.mil/confluence/hecnews/fall-2024/future-of-hec-ras)
- [HEC-RAS GPU Solver Documentation](https://www.hec.usace.army.mil/confluence/hecras/latest/gpu-solver)
- [HEC-RAS Computer Performance Guide](https://www.hec.usace.army.mil/software/hec-ras/documentation/HEC-RAS_ComputerPerformance.pdf)
- [HEC-RAS Parallelization & CPU Affinity](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/latest/working-with-hec-ras/parallelization-cpu-affinity)
- [HEC-RAS Computation Progress & Volume Accounting](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.6/running-a-model-with-2d-flow-areas/computation-progress-numerical-stability-and-volume-accounting)
- [HEC-RAS File Types](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/working-with-projects)
- [HEC-RAS 2025 Release Notes](https://www.hec.usace.army.mil/confluence/hecras/latest/release-notes)
- [HEC-RAS 2025 Quick Start Guide](https://www.hec.usace.army.mil/confluence/hecras/latest/quick-start-guide)
- [USACE Cloud Compute Home](https://www.hec.usace.army.mil/confluence/cloud-compute)
- [USACE Cloud Compute Architecture](https://www.hec.usace.army.mil/confluence/cloud-compute/cloud-compute-architecture)
- [HEC-RAS Linux Computation Engines](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/latest/working-with-hec-ras/linux-computation-engines)

### Community & Third-Party
- [ras-commander on GitHub](https://github.com/gpt-cmdr/ras-commander) (MIT, v0.89.1)
- [ras-commander on PyPI](https://pypi.org/project/ras-commander/)
- [USACE/cloudcompute on GitHub](https://github.com/USACE/cloudcompute)
- [slawler/ras-docker](https://github.com/slawler/ras-docker) — Docker images for HEC-RAS
- [Dewberry/hecrasio](https://github.com/Dewberry/hecrasio) — HEC-RAS result reading
- [HEC-Commander Benchmarking Study](https://github.com/gpt-cmdr/HEC-Commander/blob/main/Blog/7._Benchmarking_Is_All_You_Need.md)
- [Run HEC-RAS 2025 from Command Prompt (Medium)](https://medium.com/@mohor.gartner/run-simulation-from-command-prompt-hec-ras-2025-alpha-f2fb1aa1d353)
- [Hardware Optimization for HEC-RAS (Cambridge Prisms)](https://www.cambridge.org/core/journals/cambridge-prisms-water/article/optimisation-of-hardware-setups-for-timeefficient-hecras-simulations/07319F2414594E811859A1042D044F7C)

### Cloud Provider Documentation
- [Azure Batch Technical Overview](https://learn.microsoft.com/en-us/azure/batch/batch-technical-overview)
- [Azure Batch Spot VMs](https://learn.microsoft.com/en-us/azure/batch/batch-spot-vms)
- [Azure Batch Python Quickstart](https://learn.microsoft.com/en-us/azure/batch/quick-run-python)
- [AWS Batch User Guide](https://docs.aws.amazon.com/batch/latest/userguide/)
- [AWS Step Functions + Batch Orchestration](https://aws.amazon.com/blogs/compute/orchestrating-high-performance-computing-with-aws-step-functions-and-aws-batch/)
- [AWS EC2 Spot Pricing](https://aws.amazon.com/ec2/spot/pricing/)
- [Azure VM Pricing](https://azure.microsoft.com/en-us/pricing/details/virtual-machines/windows/)

### Project Internal
- `docs/network_probe_design.md` — Network probe script design
- `docs/distributed_execution_research.md` — Windows network distribution detailed analysis
- `docs/hecras_automation_ecosystem.md` — Tool ecosystem survey
- `docs/architecture.md` — Current system architecture
- `docs/codebase_analysis.md` — Known issues and test gaps
