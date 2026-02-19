# Distributed HEC-RAS Execution Research

Research into approaches for distributing HEC-RAS simulation jobs across multiple
Windows machines on a corporate network. Target use case: 50-500+ plans run
overnight on colleague laptops/desktops.

## Executive Summary

**Recommended approach: Custom HTTP worker service (Approach 7), with a
file-based queue fallback (Approach 2) for minimal-IT-friction environments.**

The HTTP worker approach provides the best balance of reliability, simplicity,
and IT acceptability. It requires no special Windows features, no message broker
infrastructure, and can be deployed as a single Python executable on each
worker machine.

### Quick Ranking

| Rank | Approach | IT Friction | Setup Effort | Reliability | Verdict |
|------|----------|-------------|--------------|-------------|---------|
| 1 | HTTP worker service | Low | Medium | High | **Best overall** |
| 2 | Shared drive file queue | Very Low | Low | Medium | **Simplest fallback** |
| 3 | Python stdlib managers | Low | Medium | Medium-High | **Zero-dependency option** |
| 4 | ZeroMQ (pyzmq) | Low | Medium | High | **Best for scale** |
| 5 | Dask Distributed | Low | Medium | Medium | Overkill for this use case |
| 6 | Dramatiq + Redis | Medium | High | High | Redis on Windows is painful |
| 7 | WinRM / PowerShell | High | Medium | High | IT will likely block |
| 8 | SSH (OpenSSH) | High | Medium | High | Requires admin/GPO |
| 9 | Celery | Medium | High | Low on Windows | Officially unsupported |
| 10 | PSExec | Very High | Low | High | Security red flag |

---

## Critical HEC-RAS Constraint: Local Disk Execution

Before evaluating distribution approaches, one constraint dominates all design
decisions:

**HEC-RAS must run from local disk, not a network share.**

- HEC-RAS performs heavy random I/O on `.p##.hdf` result files (HDF5 format)
  during computation. HDF5 over SMB is extremely slow and unreliable.
- The existing `arx-hecras` temp-directory isolation pattern already solves this
  for local parallel execution. The same pattern extends naturally to remote
  machines: copy project to remote local disk, run, copy results back.
- Terrain data (`.hdf` files, 50-500 MB) and input DSS files must be included
  in the transfer.
- Typical project transfer size: 100 MB - 1 GB depending on terrain resolution.

**Implication**: Every approach must include a "copy project to worker, run
locally, copy results back" step. Approaches that rely on running directly from
a network share are not viable.

---

## Approach 1: WinRM / PowerShell Remoting

### How It Works

Windows Remote Management (WinRM) is Microsoft's implementation of WS-Management.
PowerShell Remoting (`Invoke-Command`, `Enter-PSSession`) builds on WinRM to
execute commands on remote machines.

```powershell
# From orchestrator
Invoke-Command -ComputerName "LAPTOP-ALICE" -ScriptBlock {
    & "C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe" `
        "C:\temp\project\model.prj"
}
```

### Setup Requirements

- WinRM service must be running on each worker (disabled by default on
  Windows 10/11 client OS; enabled by default on Server)
- Firewall ports 5985 (HTTP) or 5986 (HTTPS) must be open
- In a domain environment, Kerberos authentication works automatically
- In a workgroup, TrustedHosts must be configured and HTTPS certificates deployed
- GPO deployment: `Computer Configuration > Administrative Templates >
  Windows Components > Windows Remote Management > WinRM Service`

### IT Friction: HIGH

- Enabling WinRM on client machines requires either admin rights or a GPO change
- Opening firewall ports requires IT approval
- Corporate security teams may flag WinRM as an attack surface (it is a common
  lateral movement vector)
- Many corporate environments explicitly disable WinRM on client OS via GPO

### Reliability

High once configured. Kerberos authentication in domain environments is robust.
PowerShell Remoting handles error propagation well.

### Verdict

Technically capable but the IT approval process will be a significant barrier in
most corporate environments. Not recommended as the primary approach unless IT
is already permissive about WinRM.

---

## Approach 2: Shared Drive + File-Based Queue

### How It Works

A central shared folder acts as a job queue. The orchestrator writes job files;
worker machines poll the folder and pick up jobs.

```
\\server\hecras-jobs\
    queue/
        job-001.json    # Waiting to be picked up
        job-002.json
    running/
        job-003.json    # Claimed by LAPTOP-ALICE
    done/
        job-004.json    # Completed, results path included
    projects/
        project-001/    # Copied project files
```

**Worker daemon flow:**
1. Poll `queue/` folder every N seconds
2. Atomically rename `queue/job-NNN.json` to `running/job-NNN.json` (rename is
   atomic on SMB, serves as a lock)
3. Copy project from `projects/` to local temp directory
4. Run `Ras.exe` on local copy
5. Copy results back to shared results folder
6. Move job file to `done/` with result metadata

### Setup Requirements

- Shared network folder accessible to all machines (usually already exists in
  engineering firms)
- A simple Python script running on each worker (can be a startup task or
  scheduled task)
- No special Windows features, no firewall changes, no admin rights

### IT Friction: VERY LOW

- Uses existing network infrastructure (SMB shares)
- No new ports, no new services, no GPO changes
- Worker script can run as the logged-in user
- Windows Task Scheduler can launch the worker at logon (no admin required for
  per-user tasks)

### Reliability: MEDIUM

- File-based locking via atomic rename is reliable but not bulletproof
- Worker crash during execution leaves a job in `running/` -- needs a timeout
  and recovery mechanism
- SMB connection drops can cause issues (especially with laptops on WiFi)
- No built-in retry, progress tracking, or heartbeat -- must be implemented

### Design Considerations

- Job files should include a `claimed_by` field and `claimed_at` timestamp
- A watchdog on the orchestrator should reclaim stale jobs (e.g., no heartbeat
  for 30 minutes)
- Workers should write heartbeat files during execution so the orchestrator knows
  they are alive
- Project files should be copied to local disk before execution (not run from
  the share)

### Verdict

**Best "zero-IT-friction" approach.** Simple, uses existing infrastructure,
requires no special permissions. Reliability concerns can be mitigated with
careful implementation. Recommended as a fallback or Phase 1 approach when IT
approval for other methods is pending.

---

## Approach 3: Python Task Queues (Celery, Dramatiq, RQ)

### Celery

**Windows support: DROPPED in 2016 (Celery 4.0).**

Celery removed the `prefork` pool on Windows because Windows does not support
`fork()`, only `spawn()`. It can technically run with `--pool=threads` or
`--pool=gevent`, but this is unsupported and unreliable. Running subprocess-based
HEC-RAS jobs from Celery's thread pool would work in theory but is fragile.

Additionally, Celery requires a broker (RabbitMQ or Redis). Redis has no official
Windows build -- the options are Memurai (commercial, $99/year) or WSL2/Docker.
RabbitMQ runs on Windows but is an Erlang application, adding significant
deployment complexity.

**Verdict: Not recommended.** Too many moving parts, poor Windows support.

### Dramatiq

**Windows support: YES, works well.**

Dramatiq was explicitly designed to work on Windows and uses threading instead
of forking. It supports both RabbitMQ and Redis as brokers.

However, it still requires a broker, which brings the same Redis-on-Windows
challenges. For a use case where the "tasks" are just "run Ras.exe and wait",
Dramatiq adds complexity without proportional benefit.

**Verdict: Viable but broker dependency is a drawback for this use case.**

### RQ (Redis Queue)

Requires Redis. Same broker problem. Also does not officially support Windows.

**Verdict: Not recommended for Windows.**

### Huey

Lightweight alternative that supports Redis, SQLite, or in-memory storage. The
SQLite backend could run on a shared drive, eliminating the need for Redis.
However, Huey's Windows support is not well documented.

**Verdict: Worth investigating if a task queue is desired. SQLite-on-share could
work for small scale.**

### Overall Task Queue Verdict

The broker requirement (Redis/RabbitMQ) is the main obstacle. For an engineering
firm distributing 50-500 jobs to 5-20 laptops, the infrastructure overhead of
running a message broker is disproportionate. A simpler approach (HTTP worker or
file queue) is more appropriate.

---

## Approach 4: SSH (OpenSSH on Windows)

### How It Works

Windows 10/11 includes an OpenSSH server as an optional feature. Python's
Paramiko or Fabric libraries can connect to it for remote command execution.

```python
from fabric import Connection
conn = Connection("alice-laptop", user="engineer", connect_kwargs={"password": "..."})
result = conn.run("C:\\hecras\\Ras.exe C:\\temp\\project\\model.prj")
```

### Setup Requirements

- OpenSSH server must be installed and enabled on each worker (optional Windows
  feature, disabled by default)
- Installation requires admin rights (`Add-WindowsCapability -Online
  -Name OpenSSH.Server~~~~0.0.1.0`)
- Firewall port 22 must be opened
- Service must be set to start automatically

### IT Friction: HIGH

- Enabling the SSH server requires admin rights
- Opening port 22 in corporate firewalls often triggers security review
- Corporate IT may block SSH server installation via policy
- SSH keys or password management across machines adds complexity

### Reliability: HIGH

OpenSSH is well-tested. Paramiko/Fabric provide robust Python APIs. Error
handling and file transfer (via SFTP) are built in.

### Verdict

Technically excellent but the admin requirement for installation is a
showstopper in many corporate environments. If IT is willing to deploy OpenSSH
via GPO, this becomes a strong option with mature tooling.

---

## Approach 5: PSExec / PsTools

### How It Works

PSExec from Microsoft Sysinternals can execute commands on remote machines
without any pre-installed agent. It copies a temporary service (`PSEXESVC`) to
the remote machine, starts it, executes the command, and cleans up.

```
psexec \\LAPTOP-ALICE -u DOMAIN\engineer -p pass cmd /c "Ras.exe model.prj"
```

### Setup Requirements

- Admin share (`ADMIN$` or `C$`) must be accessible on the remote machine
- Remote user must have admin rights on the target
- File and Printer Sharing must be enabled
- No agent installation needed

### IT Friction: VERY HIGH

**PSExec is a red flag for corporate security teams.** It is extensively used
by attackers for lateral movement and ransomware deployment. Many organizations:

- Block PSExec via application whitelisting (AppLocker, WDAC)
- Monitor for PSExec service creation (EventCode 7045) as an indicator of
  compromise
- Have explicit policies against PSExec usage
- SANS recommends treating all PSExec activity as potentially malicious

Additionally, credentials are sent in cleartext when using the `-u` flag, and
the tool creates named pipes that can be intercepted by local attackers.

### Verdict

**Do not use.** Even if technically possible, proposing PSExec will damage your
credibility with IT security. The security concerns are legitimate and
well-documented.

---

## Approach 6: Dask Distributed

### How It Works

Dask is a Python parallel computing framework with a scheduler-worker model.
A central scheduler coordinates work; workers on remote machines connect to it.

```python
from dask.distributed import Client, Worker
import subprocess

def run_hecras(plan_path):
    subprocess.run(["Ras.exe", plan_path], check=True)
    return plan_path

client = Client("scheduler-address:8786")
futures = client.map(run_hecras, plan_paths)
results = client.gather(futures)
```

### Setup Requirements

- Python + Dask installed on each worker machine
- Workers started manually or via script:
  `dask worker scheduler-address:8786`
- Scheduler runs on one machine
- Firewall must allow TCP connections on scheduler port (default 8786) and
  worker ports (random high ports, or configurable)

### Windows-Specific Issues

- Dask changes the event loop policy, which can break `asyncio` subprocess
  management on Windows
- `multiprocessing.spawn` on Windows means workers must guard against
  re-execution with `if __name__ == "__main__"`
- Starting a LocalCluster on Windows spawns new instances of the host
  application, which is problematic for embedded interpreters
- Running external subprocesses (`Ras.exe`) from Dask workers works but requires
  careful configuration (one task per worker, exclusive resources)

### IT Friction: LOW-MEDIUM

- No special Windows features needed
- Firewall port for the scheduler needs to be opened (one port)
- Python must be installed on each worker (or use a bundled executable)

### Reliability: MEDIUM

Dask is designed for data-parallel Python workloads, not long-running subprocess
orchestration. Using it to run `Ras.exe` jobs is feasible but is not the primary
use case. The framework is heavyweight for what amounts to "run N subprocesses
across M machines."

### Verdict

Overkill for this use case. Dask shines for distributed DataFrame operations
and array computing, not for orchestrating external executables. The Windows
event loop issues add friction. Consider only if you already have a Dask
deployment or need tight integration with Python-based post-processing.

---

## Approach 7: Custom HTTP Worker Service (RECOMMENDED)

### How It Works

Each worker machine runs a lightweight HTTP server (FastAPI/Flask). A central
orchestrator posts jobs to available workers. Workers download project files,
execute HEC-RAS locally, and upload results.

**Architecture:**

```
ORCHESTRATOR (your machine)
  |
  |-- POST /job  --> WORKER-1 (Alice's laptop, port 8000)
  |-- POST /job  --> WORKER-2 (Bob's laptop, port 8000)
  |-- POST /job  --> WORKER-3 (Carol's laptop, port 8000)
  |
  |-- GET /status <-- poll workers for job completion
  |-- GET /results <-- download result files
```

**Worker endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /health` | GET | Check if worker is alive and idle |
| `POST /job` | POST | Submit a job (project zip or UNC path) |
| `GET /job/{id}/status` | GET | Check job progress |
| `GET /job/{id}/results` | GET | Download result files |
| `DELETE /job/{id}` | DELETE | Clean up job files |

**Worker flow:**
1. Receive job submission (project archive URL or UNC path)
2. Copy/download project files to local temp directory
3. Execute `Ras.exe` (or COM via the existing `run_hecras_plan()`) on local copy
4. Report completion status
5. Make result files available for download
6. Clean up after orchestrator confirms receipt

### File Transfer Strategy

Two options for transferring project files:

**Option A: SMB share (simpler)**
- Orchestrator places project in `\\server\hecras-jobs\projects\job-001\`
- Worker copies from SMB share to local disk
- Worker copies results back to `\\server\hecras-jobs\results\job-001\`
- Orchestrator picks up results

**Option B: HTTP transfer (more self-contained)**
- Orchestrator serves project as a zip file
- Worker downloads via HTTP, extracts to local disk
- Worker uploads results via HTTP multipart or serves them for download
- Slower for large terrain files but works without shared drives

**Recommendation: Option A** (SMB share). Engineering firms already have shared
drives. HTTP transfer of 500 MB+ terrain files is unnecessarily slow. The worker
HTTP service handles orchestration; file transfer uses the existing network
infrastructure.

### Setup Requirements

- Python installed on each worker, OR a single PyInstaller executable
- Worker script added to Windows Task Scheduler (user-level, no admin)
- Shared network folder for project/result files
- Workers need to be discoverable (static IPs, DNS, or mDNS)

### IT Friction: LOW

- No new Windows features or services
- Firewall exception for one port (e.g., 8000) -- but this is user-level traffic,
  not a system service. Many corporate firewalls allow high-port TCP between
  machines on the same subnet.
- If firewall is strict: fall back to the shared-drive file queue (Approach 2)
  as the communication channel, with the HTTP service running only on localhost
  for monitoring
- No admin rights needed for anything

### Reliability: HIGH

- HTTP is well-understood, debuggable, monitorable
- Workers can report health, progress, and errors in structured JSON
- Orchestrator can implement retry, timeout, and failover logic
- Easy to add a web dashboard for monitoring
- Worker crashes are detectable via health check timeout

### Implementation Sketch

The worker could be implemented as a thin wrapper around the existing
`hecras_runner` package:

```python
# worker.py - runs on each worker machine
from fastapi import FastAPI
import subprocess, shutil, tempfile, os

app = FastAPI()
current_job = None

@app.get("/health")
def health():
    return {"status": "idle" if current_job is None else "busy",
            "hostname": os.environ["COMPUTERNAME"]}

@app.post("/job")
async def submit_job(project_share_path: str, plan_name: str, plan_suffix: str):
    # 1. Copy project from share to local temp
    # 2. Run Ras.exe in subprocess
    # 3. Copy results back to share
    # 4. Return job ID for status polling
    ...

@app.get("/job/{job_id}/status")
def job_status(job_id: str):
    return {"job_id": job_id, "status": "running", "elapsed_seconds": 123}
```

### Verdict

**Recommended primary approach.** Builds naturally on the existing
`arx-hecras` temp-directory pattern. Low IT friction, high reliability, easy to
monitor and debug. The HTTP service is simple enough to bundle as a single
executable via PyInstaller.

---

## Approach 8 (hybrid): Python stdlib `multiprocessing.managers`

### How It Works

Python's standard library includes `multiprocessing.managers.BaseManager`, which
can expose shared objects (queues, dicts) over TCP to remote processes. No
external dependencies required.

```python
# Server (orchestrator)
from multiprocessing.managers import BaseManager
from queue import Queue

job_queue = Queue()
result_queue = Queue()

class JobManager(BaseManager): pass
JobManager.register("get_jobs", callable=lambda: job_queue)
JobManager.register("get_results", callable=lambda: result_queue)

manager = JobManager(address=("0.0.0.0", 5555), authkey=b"secret")
manager.get_server().serve_forever()
```

```python
# Client (worker)
class JobManager(BaseManager): pass
JobManager.register("get_jobs")
JobManager.register("get_results")

manager = JobManager(address=("orchestrator-ip", 5555), authkey=b"secret")
manager.connect()

jobs = manager.get_jobs()
results = manager.get_results()

while True:
    job = jobs.get()  # blocks until a job is available
    result = run_hecras(job)
    results.put(result)
```

### Advantages

- **Zero external dependencies** -- uses only Python standard library
- Cross-platform (Windows client can connect to any server)
- Built-in authentication via `authkey`
- Queue semantics handle work distribution automatically
- Objects are pickled over TCP, so any serializable Python object works

### Disadvantages

- No persistence -- if the server crashes, the queue is lost
- No web dashboard or monitoring (would need to be built separately)
- Less discoverable/debuggable than HTTP
- Firewall must allow the chosen TCP port

### Verdict

**Strong zero-dependency option.** If you want to avoid adding FastAPI/Flask as
a dependency and prefer pure stdlib, this works well. The lack of persistence
and monitoring is acceptable for batch overnight runs where someone will check
results in the morning.

---

## Approach 9 (hybrid): ZeroMQ (pyzmq)

### How It Works

ZeroMQ provides lightweight message-passing sockets. The "ventilator-worker-sink"
pattern maps directly to the HEC-RAS distribution problem.

```
VENTILATOR (orchestrator)
    |
    |-- PUSH socket --> WORKER-1 (PULL socket)
    |-- PUSH socket --> WORKER-2 (PULL socket)
    |-- PUSH socket --> WORKER-3 (PULL socket)
    |
    |-- PULL socket <-- WORKER-1 (PUSH socket, results)
```

### Advantages

- Single dependency (`pyzmq`), no broker infrastructure
- Automatic load balancing (PUSH distributes to available PULL sockets)
- Very fast, low overhead
- Works well on Windows
- Handles worker disconnection/reconnection gracefully

### Disadvantages

- Less familiar than HTTP to most developers
- Custom protocol (not inspectable with standard HTTP tools like curl)
- Must handle file transfer separately (ZMQ messages or SMB share)
- No built-in web dashboard

### Verdict

**Best option for scale (100+ workers).** If the firm grows to many machines or
this becomes a regular workflow, ZeroMQ provides excellent performance and
reliability with minimal infrastructure. For 5-20 machines, the HTTP approach
is simpler and more debuggable.

---

## File Transfer Considerations

### Project Size Breakdown

| Component | Typical Size | Notes |
|-----------|-------------|-------|
| Terrain HDF | 50-500 MB | Can be shared if same terrain |
| Geometry HDF (`.g##.hdf`) | 5-50 MB | Contains 2D mesh |
| Plan/flow/geometry text files | < 1 MB | Tiny |
| Input DSS | 1-50 MB | HEC-HMS hydrographs |
| **Total per job** | **60 MB - 600 MB** | Depends on terrain |

### Transfer Strategy: Shared Terrain Cache

Most plans in a batch share the same terrain and geometry. The worker should
maintain a local terrain cache:

1. First job to a worker: full project copy (600 MB, ~60s on gigabit LAN)
2. Subsequent jobs: only copy plan/flow files + check terrain hash (~1 MB, <1s)

**Implementation:**
- Hash terrain files (SHA-256 of file header, not full file)
- Worker maintains `C:\hecras-cache\terrain\{hash}\` directories
- Job specification includes terrain hash; worker checks cache before copying
- Cache cleanup: LRU eviction when disk usage exceeds threshold

### SMB vs Local: Performance Numbers

| Operation | Local SSD | Gigabit SMB | WiFi SMB |
|-----------|-----------|-------------|----------|
| Copy 500 MB terrain | N/A | ~5s | ~50s |
| HEC-RAS write during sim | Fast | 5-10x slower | Unusable |
| Copy 50 MB results back | N/A | ~0.5s | ~5s |

**Conclusion:** Always copy to local disk before running HEC-RAS. The copy time
is negligible compared to simulation time (minutes to hours per plan).

### Running HEC-RAS on Network Drive

**Do not do this.** Per HEC-RAS official guidance from Kleinschmidt and USACE:

> "Run your model off your local drive (ideally a very fast solid state hard
> drive), as opposed to off a network drive."

HDF5 files perform poorly over SMB due to:
- Random I/O patterns that defeat SMB caching
- Frequent small writes that trigger SMB round-trips
- File locking semantics that differ between local NTFS and SMB

---

## Machine Discovery and Management

### Finding Available Machines

**Option A: Static configuration (simplest)**
- Maintain a `workers.json` file listing machine names/IPs
- Orchestrator checks each machine's health endpoint before assigning jobs
- Workers that do not respond are skipped

**Option B: Network scanning**
- ARP scan of the subnet to find live hosts
- Check for worker service on expected port
- Python libraries: `scapy` for ARP, or simple TCP connect to worker port

**Option C: Worker self-registration**
- Workers announce themselves to the orchestrator on startup
- Orchestrator maintains a registry of available workers
- Workers send periodic heartbeats; removed from registry after timeout

**Recommendation: Option C** (self-registration) for production use, with
Option A as initial implementation. Self-registration handles dynamic
environments (laptops coming and going) without manual configuration.

### Checking Machine Availability

- **CPU utilization**: Workers report CPU usage in health endpoint; skip if busy
- **Disk space**: Workers check local disk before accepting a job
- **HEC-RAS already running**: Check for existing `Ras.exe` processes
- **User activity**: Optionally check if the user is actively using the machine
  (idle time via `GetLastInputInfo` Win32 API) -- only run jobs on truly idle
  machines to avoid impacting colleagues

### Wake-on-LAN

If machines are sleeping, they can be woken remotely:

- Python library: `wakeonlan` (PyPI)
- Requires MAC addresses of target machines (stored in `workers.json`)
- WoL packets are UDP broadcasts to port 7 or 9
- **Requires**: WoL enabled in BIOS/UEFI and network adapter settings
- **Corporate consideration**: IT may have power management policies; WoL
  typically does not require IT approval as it is a standard network feature

```python
from wakeonlan import send_magic_packet
send_magic_packet("AA:BB:CC:DD:EE:FF")  # MAC address of target machine
```

### Power Management Sequence

1. Read `workers.json` for MAC addresses and hostnames
2. Send WoL magic packets to sleeping machines
3. Wait 2-3 minutes for machines to boot
4. Check health endpoints to confirm workers are online
5. Submit jobs to responsive workers
6. After all jobs complete, optionally send shutdown commands

---

## Security and IT Considerations

### What Typically Requires IT Approval

| Action | Admin Required? | IT Approval? |
|--------|----------------|--------------|
| Install Python (user-local) | No | Usually no |
| Run a Python script at logon | No | Usually no |
| Open firewall port (inbound) | Yes | Yes |
| Enable WinRM service | Yes | Yes |
| Enable OpenSSH server | Yes | Yes |
| Install Memurai/Redis | Yes | Likely yes |
| Map a network drive | No | No |
| Create a scheduled task (user) | No | No |
| Run PSExec | No (but flagged) | Likely blocked |
| Wake-on-LAN | No | Usually no |

### Least-Privilege Approach (IT-Friendly Pitch)

Frame the request to IT as follows:

1. **What we want to do**: Run engineering simulations on idle office computers
   overnight to avoid buying dedicated compute hardware.

2. **What we need**:
   - A shared network folder for job files (likely already exists)
   - Permission to run a Python script on participating machines (user-level,
     no admin)
   - One firewall exception for TCP port 8000 between engineering subnet machines
     (if using HTTP approach)

3. **What we are NOT doing**:
   - No system services, no admin rights, no changes to Windows configuration
   - No new software installed system-wide
   - No remote desktop or remote shell access
   - Scripts run as the logged-in user with their existing permissions

4. **Risk mitigation**:
   - Worker script only accepts jobs from known orchestrator IP
   - Authentication token required for all API calls
   - Worker only executes `Ras.exe` (hardcoded, not arbitrary commands)
   - All file operations confined to a designated temp directory
   - Workers can be stopped by the machine user at any time

### If IT Says No to Firewall Exceptions

Fall back to Approach 2 (shared drive file queue). This requires zero IT
involvement -- it uses only existing network share infrastructure and
user-level scheduled tasks.

---

## HEC-RAS Execution Strategy

### COM vs CLI

The existing `arx-hecras` runner uses COM (`RAS66.HECRASController`). For
distributed execution, **CLI is strongly preferred**:

| Factor | COM | CLI (`Ras.exe -c`) |
|--------|-----|---------------------|
| Requires GUI | Yes (ShowRas) | No |
| Requires HEC-RAS window | Yes | No |
| Works headless | No | Yes |
| Works over RDP | Fragile | Yes |
| Works on locked screen | Fragile | Yes |
| Future-proof (HEC-RAS 2025) | Deprecated | Primary method |

**HEC-RAS 6.0+ supports CLI execution via `Ras.exe`** with a project file
argument. The `ras-commander` Python library wraps this:

```python
# Using ras-commander library
from ras_commander import RasCmdr
RasCmdr.compute_plan(plan_name="plan01")
```

Or directly:
```
"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe" "C:\temp\project\model.p01"
```

**Recommendation**: Migrate the worker execution path to CLI (`subprocess.run`
calling `Ras.exe`) rather than COM. COM should remain available in the GUI for
interactive use but distributed workers should use CLI for reliability.

### HEC-RAS 2025 Consideration

HEC-RAS 2025 (expected release Fall 2025) is designed from the ground up for
headless Linux/Docker execution. It will include:

- Native CLI execution (no COM dependency)
- Docker container support
- Cloud/S3 integration
- Public API for programmatic access
- Improved multi-core parallelism (explicit solver)

The distributed execution architecture designed here should be forward-compatible
with HEC-RAS 2025. The worker pattern (receive job, run executable, return
results) is execution-engine agnostic.

---

## Recommended Implementation Plan

### Phase 1: Proof of Concept (1-2 weeks)

**Shared drive file queue (Approach 2)** with manual worker startup.

- Orchestrator: Python script that writes job JSON files to shared folder
- Worker: Python script that polls shared folder, copies project locally,
  runs `Ras.exe` via subprocess, copies results back
- Manual: Start worker script on each machine before leaving for the night
- No IT approval needed, no firewall changes

**Deliverables:**
- `worker.py` -- standalone script, runs on any machine with Python + HEC-RAS
- `orchestrator.py` -- submits jobs, monitors progress via shared folder
- `workers.json` -- list of participating machines

### Phase 2: HTTP Worker Service (2-4 weeks)

**HTTP worker (Approach 7)** with worker self-registration.

- Worker: FastAPI service bundled as PyInstaller exe
- Orchestrator: Web dashboard showing worker status and job progress
- File transfer via SMB share with terrain caching
- Worker auto-starts via Windows Task Scheduler

**IT approval needed:** One firewall port exception on engineering subnet.

### Phase 3: Production Hardening (2-4 weeks)

- Wake-on-LAN integration for sleeping machines
- Automatic job retry on worker failure
- Result validation (check HDF5 files are complete)
- Email/Teams notification on batch completion
- Resource monitoring (don't overload machines that users are still using)

### Future: HEC-RAS 2025 Migration

- Replace `Ras.exe` 6.6 invocation with HEC-RAS 2025 CLI
- Evaluate Docker-based workers (if IT permits containers)
- Consider cloud burst for large batches (AWS/Azure HEC-RAS containers)

---

## References

- [WinRM Installation and Configuration - Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/winrm/installation-and-configuration-for-windows-remote-management)
- [Enable WinRM via GPO - Windows OS Hub](https://woshub.com/enable-winrm-management-gpo/)
- [Running Celery 5 on Windows - Simple Thread](https://www.simplethread.com/running-celery-5-on-windows/)
- [Dramatiq - Celery Alternative](https://www.pedaldrivenprogramming.com/2018/07/dramatiq-celery-alternative/)
- [Choosing The Right Python Task Queue](https://judoscale.com/blog/choose-python-task-queue)
- [PsExec - Microsoft Sysinternals](https://learn.microsoft.com/en-us/sysinternals/downloads/psexec)
- [Detecting PsExec Lateral Movements - Hack The Box](https://www.hackthebox.com/blog/how-to-detect-psexec-and-lateral-movements)
- [PSExec Deep-Dive - SANS](https://www.sans.org/blog/protecting-privileged-domain-accounts-psexec-deep-dive)
- [Dask Distributed - Subprocess Issues on Windows](https://github.com/dask/distributed/issues/7492)
- [Dask Distributed - Running N Subprocesses on N Workers](https://github.com/dask/distributed/issues/992)
- [Distributed Computing in Python with multiprocessing - Eli Bendersky](https://eli.thegreenplace.net/2012/01/24/distributed-computing-in-python-with-multiprocessing)
- [Python multiprocessing.managers Documentation](https://docs.python.org/3/library/multiprocessing.html)
- [ZeroMQ Patterns and Use Cases](https://medium.com/@prajwal.chin/zmq-patterns-and-use-cases-unleashing-the-power-of-zeromq-in-python-9c0304cd3dea)
- [pyzmq - Python ZeroMQ Bindings](https://zeromq.org/languages/python/)
- [OpenSSH Server Configuration - Microsoft Learn](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration)
- [Manage OpenSSH with Group Policy - Microsoft Learn](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-group-policy)
- [Fabric - Python SSH Library](https://www.fabfile.org/)
- [Paramiko - Python SSH Library](https://www.paramiko.org/)
- [Optimizing Your Computer for Fast HEC-RAS Modeling - Kleinschmidt](https://therassolution.kleinschmidtgroup.com/ras-post/optimizing-your-computer-for-fast-hec-ras-modeling/)
- [HEC-RAS Parallelization CPU Affinity - USACE](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/latest/working-with-hec-ras/parallelization-cpu-affinity)
- [Future of HEC-RAS - USACE HEC News](https://www.hec.usace.army.mil/confluence/hecnews/fall-2024/future-of-hec-ras)
- [HEC-RAS 2025 - USACE](https://www.hec.usace.army.mil/software/hec-ras/2025/)
- [ras-commander - PyPI](https://pypi.org/project/ras-commander/)
- [ras-commander - GitHub](https://github.com/gpt-cmdr/ras-commander)
- [Redis on Windows - Every Practical Option in 2025](https://medium.com/@shin71958/how-to-run-redis-on-windows-every-practical-option-in-2025-01496a84d54d)
- [Memurai - Redis Alternative for Windows](https://www.memurai.com/redis-api-compatible)
- [wakeonlan - PyPI](https://pypi.org/project/wakeonlan/)
- [SMB Performance Troubleshooting - Microsoft Learn](https://learn.microsoft.com/en-us/troubleshoot/windows-server/networking/slow-smb-file-transfer)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
