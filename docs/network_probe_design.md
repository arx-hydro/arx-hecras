# Network Probe Design — Distributed HEC-RAS Capability Discovery

> Design document for a Python script that probes a corporate Windows network to
> discover what distribution mechanisms are available for farming out HEC-RAS
> simulation jobs to colleague machines.

## Motivation

The current `arx-hecras` runner parallelises plans across CPU cores on a single
machine via `multiprocessing.Process`. For large projects with many plans or
expensive 2D meshes, we want to distribute jobs to idle colleague machines. But
corporate IT environments vary wildly: some have WinRM enabled, some lock
everything down, some have PowerShell remoting but no SSH. Before building a
distributed runner, we need to know what the network actually supports.

The `ras-commander` library already has SSH, WinRM, and network-share remote
execution backends (see `docs/hecras_automation_ecosystem.md`). This probe will
tell us which of those backends are viable in our specific environment.

---

## 1. Probe Categories and Checks

### 1.1 Local Machine Info (no network access needed)

| # | Check | Method | Privilege | Risk |
|---|-------|--------|-----------|------|
| L1 | Current username and domain | `os.environ['USERDOMAIN']`, `os.environ['USERNAME']` | Standard | None |
| L2 | Is user a local admin? | `ctypes.windll.shell32.IsUserAnAdmin()` | Standard | None |
| L3 | Domain membership | `wmi.WMI().Win32_ComputerSystem()[0].PartOfDomain` or `socket.getfqdn()` | Standard | None |
| L4 | Local IP address(es) | `socket.getaddrinfo(socket.gethostname(), None)` | Standard | None |
| L5 | Subnet mask | `ipaddress` module parsing from `ipconfig` output | Standard | None |
| L6 | Python version and path | `sys.version`, `sys.executable` | Standard | None |
| L7 | HEC-RAS installation | Registry scan `HKLM\SOFTWARE\HEC\HEC-RAS\*` via `winreg` | Standard | None |
| L8 | HEC-RAS COM registration | `win32com.client.Dispatch("RAS66.HECRASController")` | Standard | None |
| L9 | Available RAM and CPU cores | `os.cpu_count()`, `psutil.virtual_memory()` (or WMI fallback) | Standard | None |
| L10 | Windows Firewall profile | `netsh advfirewall show currentprofile` (parse output) | Standard | None |
| L11 | Local WinRM service status | `sc query winrm` (parse output) | Standard | None |
| L12 | Local OpenSSH server status | `sc query sshd` (parse output) | Standard | None |
| L13 | PowerShell available | `shutil.which('powershell.exe')` or `shutil.which('pwsh.exe')` | Standard | None |

### 1.2 Network Discovery

| # | Check | Method | Privilege | Risk |
|---|-------|--------|-----------|------|
| N1 | ICMP ping sweep of local subnet | `subprocess` calling `ping -n 1 -w 500 <ip>` for each IP in /24 | Standard | **Low**: may appear as port scan to IDS; rate-limited and ICMP only |
| N2 | Concurrent ping sweep | `concurrent.futures.ThreadPoolExecutor` (32-64 workers) | Standard | Same as N1 |
| N3 | ARP table (already-known hosts) | `arp -a` parsed output — faster than ping sweep, zero traffic | Standard | None |
| N4 | NetBIOS name resolution | `nbtstat -A <ip>` for each responding host | Standard | **Low**: NetBIOS traffic |
| N5 | Reverse DNS lookup | `socket.gethostbyaddr(ip)` for each responding host | Standard | None |
| N6 | mDNS discovery | Send mDNS query for `_workstation._tcp.local` | Standard | **Low**: unusual traffic pattern |
| N7 | Active Directory query | `ldap3` library or `dsquery computer` via subprocess | Standard (domain-joined) | None if domain-joined |

**Discovery strategy (ordered by noise level):**
1. Start with ARP table (zero traffic, instant)
2. Then reverse DNS for known IPs (minimal traffic)
3. Then ICMP ping sweep for remainder of /24 (moderate traffic)
4. NetBIOS only for hosts that responded to ping
5. AD query if domain-joined (most reliable, least intrusive)

### 1.3 Port Scanning (per discovered host)

| # | Check | Port(s) | Method | Privilege | Risk |
|---|-------|---------|--------|-----------|------|
| P1 | SMB | 445 | TCP connect with 2s timeout | Standard | **Low** |
| P2 | WinRM HTTP | 5985 | TCP connect with 2s timeout | Standard | **Low** |
| P3 | WinRM HTTPS | 5986 | TCP connect with 2s timeout | Standard | **Low** |
| P4 | SSH | 22 | TCP connect with 2s timeout | Standard | **Low** |
| P5 | RDP | 3389 | TCP connect with 2s timeout | Standard | **Low** |
| P6 | WMI/DCOM | 135 | TCP connect with 2s timeout | Standard | **Low** |
| P7 | HTTP (common agent ports) | 8080, 8443 | TCP connect with 2s timeout | Standard | **Low** |

Implementation: `socket.create_connection((ip, port), timeout=2)` in a
`ThreadPoolExecutor`. This is a standard TCP handshake, not a SYN scan. It uses
the OS network stack normally and is the least suspicious form of port check.

### 1.4 SMB / File Sharing (per host with port 445 open)

| # | Check | Method | Privilege | Risk |
|---|-------|--------|-----------|------|
| S1 | List available shares | `net view \\hostname` via subprocess | Standard | **Low** |
| S2 | Enumerate shares (detailed) | `smbclient` library `listShares()` or `win32net.NetShareEnum()` | Standard | **Low** |
| S3 | Test read access per share | Attempt `os.listdir('\\\\hostname\\share')` | Standard | **Low**: read-only |
| S4 | Test write access | Create + delete a small temp file in share | Standard | **Medium**: creates a file (briefly) |
| S5 | Check for existing HEC-RAS shares | Look for shares containing HEC-RAS keywords or project files | Standard | **Low**: read-only |
| S6 | Measure throughput | Time a 10 MB file copy to/from share | Standard | **Medium**: generates network traffic |

**Note on S4**: Write test creates a file named `.arx_probe_write_test_<uuid>`
and immediately deletes it. This is the only destructive check in the entire
probe. It should be opt-in (disabled by default).

### 1.5 WinRM (per host with port 5985/5986 open)

| # | Check | Method | Privilege | Risk |
|---|-------|--------|-----------|------|
| W1 | HTTP endpoint test | `urllib.request.urlopen('http://host:5985/wsman')` — check for HTTP 401 (expected) vs connection refused | Standard | None |
| W2 | Authenticate with current creds | `pywinrm` library `Session(host, auth='kerberos')` or `auth='ntlm'` | Standard (domain creds) | **Low**: failed auth is logged on remote |
| W3 | Execute test command | `session.run_cmd('hostname')` | Standard (if W2 succeeds) | **Low**: read-only command |
| W4 | Check remote HEC-RAS | `session.run_cmd('reg query "HKLM\\SOFTWARE\\HEC\\HEC-RAS"')` | Standard | **Low** |
| W5 | Check remote Python | `session.run_cmd('where python')` | Standard | **Low** |
| W6 | Check remote CPU/RAM | `session.run_cmd('wmic cpu get NumberOfCores && wmic os get TotalVisibleMemorySize')` | Standard | **Low** |

### 1.6 SSH (per host with port 22 open)

| # | Check | Method | Privilege | Risk |
|---|-------|--------|-----------|------|
| H1 | Banner grab | Read first bytes after TCP connect (identify OpenSSH version) | Standard | None |
| H2 | Attempt key-based auth | `paramiko.SSHClient.connect(host, look_for_keys=True)` | Standard | **Low**: failed auth logged |
| H3 | Attempt password auth | Interactive — skip in automated mode | Standard | **Medium**: password prompt |
| H4 | Execute test command | `client.exec_command('hostname')` | Standard (if H2 succeeds) | **Low** |
| H5 | Check remote HEC-RAS | `client.exec_command('reg query ...')` | Standard | **Low** |

### 1.7 PowerShell Remoting (per host with WinRM open)

| # | Check | Method | Privilege | Risk |
|---|-------|--------|-----------|------|
| R1 | Test-WSMan | `subprocess: powershell -Command "Test-WSMan -ComputerName host"` | Standard | **Low** |
| R2 | Invoke-Command | `subprocess: powershell -Command "Invoke-Command -ComputerName host -ScriptBlock { hostname }"` | Standard (domain creds) | **Low** |
| R3 | Check remote capabilities | `Invoke-Command { Get-CimInstance Win32_Processor; Get-CimInstance Win32_OperatingSystem }` | Standard | **Low** |

### 1.8 General Network / Domain Info

| # | Check | Method | Privilege | Risk |
|---|-------|--------|-----------|------|
| G1 | Domain controller discovery | `nltest /dsgetdc:` via subprocess | Standard | None |
| G2 | DNS server | `ipconfig /all` parsed | Standard | None |
| G3 | Network speed estimate | Time ICMP round-trip to each host | Standard | None |
| G4 | Group Policy check (WinRM) | `gpresult /r /scope:computer` — look for WinRM policies | **Admin** | None |
| G5 | Firewall outbound rules | `netsh advfirewall firewall show rule name=all dir=out` | **Admin** | None |

---

## 2. Python Libraries

### Standard Library (no pip install)

| Module | Used For |
|--------|----------|
| `socket` | TCP port checks, hostname resolution, IP detection |
| `subprocess` | Calling `ping`, `arp`, `nbtstat`, `net view`, `sc query`, `powershell`, `netsh` |
| `concurrent.futures` | ThreadPoolExecutor for parallel ping sweep and port checks |
| `ipaddress` | Subnet calculation, IP iteration |
| `ctypes` | Admin check (`IsUserAnAdmin`), Windows API calls |
| `winreg` | Registry access for HEC-RAS detection |
| `os`, `sys`, `platform` | Environment info |
| `json` | Machine-readable output |
| `textwrap`, `shutil` | Terminal formatting |
| `time`, `datetime` | Timing and timestamps |
| `pathlib` | Path handling |
| `uuid` | Unique temp file names for write tests |
| `urllib.request` | WinRM HTTP endpoint check |
| `logging` | Structured logging throughout |

### Optional pip installs

| Package | PyPI | Used For | Fallback |
|---------|------|----------|----------|
| `pywinrm` | `pip install pywinrm` | WinRM session auth and command execution | Fall back to `powershell Invoke-Command` subprocess |
| `paramiko` | `pip install paramiko` | SSH connections | Just report port open, skip auth test |
| `psutil` | `pip install psutil` | Local CPU/RAM detection | WMI via subprocess or `wmic` command |
| `wmi` | `pip install wmi` | Local/remote WMI queries | `wmic` subprocess fallback |
| `pywin32` | `pip install pywin32` | COM check, `win32net.NetShareEnum()` | Already a project dependency; `net view` subprocess fallback |
| `ldap3` | `pip install ldap3` | Active Directory host enumeration | `dsquery computer` subprocess fallback |
| `smbprotocol` | `pip install smbprotocol` | Programmatic SMB share enumeration | `net view` subprocess fallback |

**Design principle**: Every check has a stdlib/subprocess fallback. Optional
libraries improve the experience (progress, detail, reliability) but nothing is
strictly required beyond the standard library and `pywin32` (already in the
project's deps).

---

## 3. Privilege Requirements

### Standard User (everything in the default run)

All checks in categories L, N, P, S (except S4 write test), W, H, R, and most
of G run fine as a standard domain user. The key insight is that **TCP port
checks, SMB share listing, WinRM authentication with current domain credentials,
and subprocess calls to `ping`/`arp`/`nbtstat`/`net view` all work without
elevation.**

### Local Administrator (optional enhanced mode)

| Check | Why Admin Needed |
|-------|-----------------|
| G4 — Group Policy dump | `gpresult /scope:computer` requires elevation |
| G5 — Firewall rule listing | `netsh advfirewall ... show rule` requires elevation |
| Raw socket ping | `socket.SOCK_RAW` requires admin on Windows (not used; we use subprocess `ping`) |
| Service start/stop | We never start/stop services, only query status |

The script should detect whether it is running elevated and skip admin-only
checks with a note in the output, rather than failing or requesting UAC.

---

## 4. Security Alert Risk Assessment

### Will NOT trigger alerts

- Reading local environment variables, registry, service status
- DNS lookups and ARP table queries
- Individual TCP connections to specific ports (looks like normal network activity)

### MAY trigger alerts (low probability)

| Activity | Why | Mitigation |
|----------|-----|------------|
| ICMP ping sweep of /24 | Sequential pings across a subnet look like reconnaissance | Rate-limit to 5/sec; use ARP table + AD query first |
| Port scan of multiple ports per host | 7 ports per host is minimal, but some IDS flag any multi-port scan | Scan only hosts that responded to ping; use 2s timeout (slow) |
| WinRM/SSH auth failures | Failed authentication attempts are logged on the remote machine's Security event log | Try current domain creds first; do not brute-force |
| NetBIOS name queries | `nbtstat` generates NetBIOS traffic that some networks flag | Only for hosts that responded to ping |

### WILL trigger alerts (not included in default run)

| Activity | Notes |
|----------|-------|
| SYN scanning (raw sockets) | NOT used. We do full TCP connect instead. |
| Credential spraying | NOT done. We only use the current user's existing Kerberos/NTLM token. |
| SMB write test | Opt-in only, creates a tiny temp file and deletes it immediately. |

### Recommendations for the user

1. Notify IT before running the ping sweep portion (checks N1-N2)
2. Run during business hours when colleague machines are on
3. Start with `--local-only` mode to gather local info without any network traffic
4. Use `--host <ip>` mode to probe a single known colleague machine first

---

## 5. Script Structure

```
src/network_probe/
    __init__.py
    __main__.py          # Entry point: python -m network_probe
    cli.py               # argparse CLI
    local_checks.py      # Category L checks
    discovery.py         # Category N checks (ping, ARP, DNS, AD)
    port_scan.py         # Category P checks
    smb_checks.py        # Category S checks
    winrm_checks.py      # Category W checks
    ssh_checks.py        # Category H checks
    ps_remoting.py       # Category R checks
    network_info.py      # Category G checks
    report.py            # Traffic-light report generation
    models.py            # Dataclasses for results
```

Alternatively, if we want to keep this as a single-file utility for easy
distribution (copy to colleague machines without pip install), it can be one
`network_probe.py` file of roughly 800-1200 lines, with classes for each
category.

### Key Dataclasses

```python
@dataclass
class HostInfo:
    ip: str
    hostname: str | None
    source: str               # "arp", "ping", "dns", "ad"
    online: bool
    ports: dict[int, bool]    # port -> open?
    smb_shares: list[str]
    smb_writable: list[str]
    winrm_available: bool
    winrm_authenticated: bool
    ssh_available: bool
    ssh_banner: str | None
    rdp_available: bool
    hecras_installed: bool | None   # None = couldn't check
    cpu_cores: int | None
    ram_gb: float | None
    os_version: str | None

@dataclass
class ProbeResult:
    timestamp: str
    local: LocalMachineInfo
    hosts: list[HostInfo]
    subnet: str
    domain: str | None
    recommendations: list[Recommendation]

@dataclass
class Recommendation:
    approach: str              # "smb_share", "winrm", "ssh", "ps_remoting"
    rating: str                # "green", "yellow", "red"
    summary: str
    details: list[str]
    hosts_supporting: list[str]
```

### CLI Interface

```
python -m network_probe                    # Full probe (all categories)
python -m network_probe --local-only       # Local machine info only (zero network traffic)
python -m network_probe --host 10.0.1.50   # Probe a single host
python -m network_probe --subnet 10.0.1.0/24  # Override auto-detected subnet
python -m network_probe --skip smb,ssh     # Skip specific categories
python -m network_probe --write-test       # Enable SMB write test (opt-in)
python -m network_probe --json             # Machine-readable JSON output
python -m network_probe --output report.json  # Save to file
python -m network_probe --quiet            # Minimal console output
python -m network_probe --verbose          # Show each check as it runs
```

---

## 6. Output Format

### Console Output (default)

```
===============================================================
  Network Capability Probe for Distributed HEC-RAS Computing
  2026-02-19 14:30:00 | Duration: 2m 34s
===============================================================

LOCAL MACHINE
  Hostname:       ENGWS-042
  User:           ARXENG\d.kennewell
  Domain:         ARXENG (domain-joined)
  Admin:          No (standard user)
  IP:             10.0.1.42/24
  CPU:            12 cores (AMD Ryzen 9)
  RAM:            32 GB
  Python:         3.13.1 at C:\dave\code\arx-hecras\.venv\Scripts\python.exe
  HEC-RAS:        6.6 at C:\Program Files (x86)\HEC\HEC-RAS\6.6
  HEC-RAS COM:    RAS66.HECRASController OK
  WinRM service:  Running
  SSH service:    Not installed
  Firewall:       Domain profile active

NETWORK DISCOVERY
  Subnet:         10.0.1.0/24
  Method:         ARP table + ICMP ping sweep
  Hosts found:    7 of 254 probed

HOST DETAILS
  10.0.1.10  dc01.arxeng.local          [DC] ports: 445 5985 3389
  10.0.1.20  engws-015.arxeng.local           ports: 445 5985 3389
  10.0.1.21  engws-016.arxeng.local           ports: 445 5985 22 3389
  10.0.1.30  engws-027.arxeng.local           ports: 445 3389
  10.0.1.31  engws-028.arxeng.local           ports: 445 5985 3389
  10.0.1.40  engws-039.arxeng.local           ports: 445 3389
  10.0.1.50  printer-2f.arxeng.local          ports: 9100

DISTRIBUTION APPROACH ASSESSMENT
  ---------------------------------------------------------------
  Approach              Rating    Hosts    Notes
  ---------------------------------------------------------------
  SMB network shares    GREEN     5/6      All workstations have 445 open.
                                           Admin$ and C$ accessible with
                                           domain creds. This is the simplest
                                           approach: copy project to \\host\share,
                                           run via WinRM/PsExec.

  WinRM                 GREEN     4/6      Port 5985 open on 4 hosts.
                                           Kerberos auth succeeded on all 4.
                                           Can execute 'hostname' remotely.
                                           Ready for remote HEC-RAS execution.

  SSH (OpenSSH)         YELLOW    1/6      Only engws-016 has port 22 open.
                                           Banner: OpenSSH_for_Windows_8.6.
                                           Key auth not tested (no keys deployed).
                                           Not viable for fleet-wide distribution.

  PowerShell Remoting   GREEN     4/6      Test-WSMan succeeded on same 4 hosts
                                           as WinRM (same transport). Invoke-Command
                                           works. Best for orchestration scripts.

  RDP                   YELLOW    5/6      Port 3389 open but RDP is interactive-only.
                                           Not useful for automated job distribution.
                                           Confirms machines are general-purpose
                                           workstations (good sign).

  ---------------------------------------------------------------

RECOMMENDATION
  Best approach: WinRM + SMB network shares

  1. Use SMB shares to copy HEC-RAS project files to remote machines
  2. Use WinRM (or PowerShell Remoting) to launch HEC-RAS CLI on remote machines
  3. Use SMB shares to copy results back

  This matches the approach used by ras-commander's WinRM backend and
  the HEC-Commander notebook suite's network share execution model.

  4 colleague machines available for distributed computing:
    engws-015  (WinRM + SMB)
    engws-016  (WinRM + SMB + SSH)
    engws-027  (SMB only — WinRM not enabled, request IT to enable)
    engws-028  (WinRM + SMB)

  Next steps:
    - Verify HEC-RAS is installed on remote machines (requires WinRM)
    - Set up a shared folder for project staging
    - Test with a small simulation before scaling up
```

### JSON Output (--json)

The `ProbeResult` dataclass serialised via `dataclasses.asdict()` +
`json.dumps(indent=2)`. Includes all raw data from every check for programmatic
consumption by the distributed runner.

---

## 7. Estimated Runtime

| Phase | Hosts | Est. Time | Parallelism |
|-------|-------|-----------|-------------|
| Local machine checks | 1 | 2-5 seconds | Sequential |
| ARP table parse | N/A | <1 second | N/A |
| ICMP ping sweep (/24) | 254 | 15-30 seconds | 32 threads, 500ms timeout |
| Reverse DNS | ~10 | 2-5 seconds | 16 threads |
| Port scan (7 ports x ~10 hosts) | ~10 | 5-15 seconds | 32 threads, 2s timeout |
| SMB share enumeration | ~6 | 5-10 seconds | Sequential per host |
| WinRM auth test | ~4 | 5-10 seconds | Sequential per host |
| SSH banner grab | ~1 | 1-2 seconds | Sequential |
| PS remoting test | ~4 | 5-15 seconds | Sequential (subprocess) |
| **Total** | | **~1-2 minutes** | |

With `--local-only`: under 5 seconds.
With `--host <single-ip>`: under 15 seconds.
Full /24 sweep: 1-2 minutes typical corporate network.

If the subnet is larger (/16 corporate), the ping sweep dominates. We should
cap at /24 by default and require `--subnet` for larger ranges.

---

## 8. Error Handling Strategy

- Every individual check is wrapped in try/except and produces a result even on
  failure (with `error_message` field)
- Network timeouts are 2 seconds per connection attempt (configurable via `--timeout`)
- The script never raises to the user; all errors become "red" ratings with
  explanatory messages
- If an optional library is missing, the check is skipped with a note:
  `"pywinrm not installed — skipping WinRM authentication test (pip install pywinrm)"`
- Ctrl+C at any point produces a partial report from checks completed so far

---

## 9. Integration with arx-hecras

This probe is designed as a standalone utility but with clear integration points:

1. **JSON output** can be consumed by a future `distributed_runner.py` module
   to automatically select distribution strategy
2. **HostInfo dataclass** maps directly to what `runner.py` needs to build
   `SimulationJob` targets
3. **ras-commander compatibility**: The probe's WinRM/SSH/SMB checks align
   exactly with ras-commander's `RasCmdr` remote execution backends, so if we
   later adopt ras-commander, this probe tells us which backend to configure
4. The temp-directory isolation pattern in `file_ops.py` translates directly to
   the SMB approach: copy to `\\remote\share\HECRAS_xxxx\` instead of local
   `%TEMP%\HECRAS_xxxx\`

---

## 10. Future Extensions

- **Scheduled re-probe**: Run periodically to track which machines are online
  during business hours vs. available overnight for batch jobs
- **Hardware census**: With WinRM access, collect GPU info (relevant for
  HEC-RAS 2025's GPU acceleration), disk speed, and available disk space
- **Agent deployment probe**: Check if Python/HEC-RAS are already installed on
  remote machines, and whether we can install them via WinRM
- **Benchmark mode**: Run a tiny HEC-RAS simulation on each remote machine to
  measure actual compute throughput, not just connectivity
- **QGIS plugin integration**: Surface the probe results in the QGIS plugin
  for one-click distributed execution setup
