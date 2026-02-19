"""Network Capability Probe for Distributed HEC-RAS Computing.

Single-file utility. Runs with stdlib + pywin32 (already a project dependency).
Optional: pywinrm, paramiko, psutil for enhanced checks.

Usage:
    python network_probe.py                     # Full probe
    python network_probe.py --local-only        # Local machine info only
    python network_probe.py --host 10.0.1.50    # Probe a single host
    python network_probe.py --json              # JSON output
    python network_probe.py --json -o report.json  # Save JSON to file
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import datetime
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import winreg
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class LocalMachineInfo:
    hostname: str = ""
    username: str = ""
    domain: str = ""
    is_domain_joined: bool = False
    is_admin: bool = False
    ip_addresses: list[str] = field(default_factory=list)
    subnet: str = ""
    cpu_cores: int = 0
    ram_gb: float = 0.0
    os_version: str = ""
    python_version: str = ""
    python_path: str = ""
    hecras_path: str = ""
    hecras_version: str = ""
    hecras_com_ok: bool = False
    winrm_service: str = ""  # Running / Stopped / Not installed
    ssh_service: str = ""
    powershell_path: str = ""
    firewall_profile: str = ""


@dataclass
class HostInfo:
    ip: str = ""
    hostname: str | None = None
    source: str = ""  # arp, ping, dns
    online: bool = False
    ports: dict[int, bool] = field(default_factory=dict)
    smb_shares: list[str] = field(default_factory=list)
    winrm_http_ok: bool = False
    ssh_banner: str | None = None
    rdp_open: bool = False
    logged_in_user: str | None = None
    sessions: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    approach: str
    rating: str  # GREEN, YELLOW, RED
    hosts_supporting: list[str] = field(default_factory=list)
    summary: str = ""
    details: list[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    timestamp: str = ""
    duration_seconds: float = 0.0
    local: LocalMachineInfo = field(default_factory=LocalMachineInfo)
    hosts: list[HostInfo] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)


# ── Local Machine Checks ────────────────────────────────────────────

def check_local_machine() -> LocalMachineInfo:
    info = LocalMachineInfo()
    info.hostname = socket.gethostname()
    info.username = os.environ.get("USERNAME", "unknown")
    info.domain = os.environ.get("USERDOMAIN", "")
    info.os_version = platform.platform()
    info.python_version = sys.version.split()[0]
    info.python_path = sys.executable
    info.cpu_cores = os.cpu_count() or 0

    # Domain membership
    try:
        fqdn = socket.getfqdn()
        info.is_domain_joined = "." in fqdn and fqdn != info.hostname
    except Exception:
        pass

    # Admin check
    try:
        info.is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        pass

    # IP addresses and subnet
    try:
        addrs = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        info.ip_addresses = sorted({a[4][0] for a in addrs if not a[4][0].startswith("127.")})
    except Exception:
        pass

    # Subnet from ipconfig
    if info.ip_addresses:
        try:
            result = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.splitlines()
            for i, line in enumerate(lines):
                for ip in info.ip_addresses:
                    if ip in line:
                        # Look for subnet mask in next few lines
                        for j in range(i + 1, min(i + 5, len(lines))):
                            if "Subnet Mask" in lines[j] or "subnet" in lines[j].lower():
                                mask = lines[j].split(":")[-1].strip()
                                if mask:
                                    try:
                                        net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
                                        info.subnet = str(net)
                                    except Exception:
                                        pass
                                break
        except Exception:
            pass

    # RAM via wmic
    try:
        result = subprocess.run(
            ["wmic", "os", "get", "TotalVisibleMemorySize", "/value"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if "TotalVisibleMemorySize=" in line:
                kb = int(line.split("=")[1].strip())
                info.ram_gb = round(kb / 1024 / 1024, 1)
    except Exception:
        pass

    # HEC-RAS installation from registry
    try:
        reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\HEC\HEC-RAS")
        i = 0
        versions = []
        while True:
            try:
                subkey_name = winreg.EnumKey(reg_key, i)
                versions.append(subkey_name)
                i += 1
            except OSError:
                break
        if versions:
            latest = sorted(versions)[-1]
            info.hecras_version = latest
            try:
                ver_key = winreg.OpenKey(reg_key, latest)
                info.hecras_path, _ = winreg.QueryValueEx(ver_key, "InstallDir")
                winreg.CloseKey(ver_key)
            except Exception:
                pass
        winreg.CloseKey(reg_key)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # HEC-RAS COM check (quick — just try Dispatch and quit)
    try:
        import importlib
        win32com_client = importlib.import_module("win32com.client")
        ras = win32com_client.Dispatch("RAS66.HECRASController")
        ras.QuitRas()
        info.hecras_com_ok = True
        del ras
    except Exception:
        info.hecras_com_ok = False

    # Service checks
    for svc_name, attr in [("winrm", "winrm_service"), ("sshd", "ssh_service")]:
        try:
            result = subprocess.run(
                ["sc", "query", svc_name], capture_output=True, text=True, timeout=5
            )
            if "RUNNING" in result.stdout:
                setattr(info, attr, "Running")
            elif "STOPPED" in result.stdout:
                setattr(info, attr, "Stopped")
            else:
                setattr(info, attr, "Not installed")
        except Exception:
            setattr(info, attr, "Unknown")

    # PowerShell
    info.powershell_path = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or ""

    # Firewall profile
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "show", "currentprofile"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "Profile" in line and "Settings" in line:
                info.firewall_profile = line.strip().replace(" Settings:", "")
                break
    except Exception:
        pass

    return info


# ── Network Discovery ────────────────────────────────────────────────

def parse_arp_table() -> dict[str, str]:
    """Parse ARP table. Returns {ip: mac}."""
    hosts = {}
    try:
        result = subprocess.run(
            ["arp", "-a"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    ip = ipaddress.IPv4Address(parts[0])
                    if not ip.is_loopback and not ip.is_multicast:
                        hosts[str(ip)] = parts[1]
                except ValueError:
                    continue
    except Exception:
        pass
    return hosts


def ping_host(ip: str, timeout_ms: int = 500) -> bool:
    """Ping a single host. Returns True if reachable."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), str(ip)],
            capture_output=True, text=True, timeout=3
        )
        return "TTL=" in result.stdout or "ttl=" in result.stdout
    except Exception:
        return False


def resolve_hostname(ip: str) -> str | None:
    """Reverse DNS lookup."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except Exception:
        return None


def discover_hosts(subnet: str, known_ips: set[str] | None = None) -> list[HostInfo]:
    """Discover hosts on the subnet via ARP + ping sweep + reverse DNS."""
    hosts: dict[str, HostInfo] = {}

    # Phase 1: ARP table (zero traffic)
    print("  [1/3] Reading ARP table...", end=" ", flush=True)
    arp_hosts = parse_arp_table()
    for ip, mac in arp_hosts.items():
        try:
            if ipaddress.IPv4Address(ip) in ipaddress.IPv4Network(subnet, strict=False):
                hosts[ip] = HostInfo(ip=ip, source="arp", online=True)
        except ValueError:
            continue
    print(f"{len(hosts)} hosts from ARP")

    # Phase 2: Ping sweep for rest of subnet
    print("  [2/3] Ping sweep...", end=" ", flush=True)
    try:
        network = ipaddress.IPv4Network(subnet, strict=False)
        ips_to_ping = [str(ip) for ip in network.hosts() if str(ip) not in hosts]
    except ValueError:
        ips_to_ping = []

    if ips_to_ping:
        ping_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            future_to_ip = {pool.submit(ping_host, ip): ip for ip in ips_to_ping}
            for future in concurrent.futures.as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    if future.result():
                        hosts[ip] = HostInfo(ip=ip, source="ping", online=True)
                        ping_count += 1
                except Exception:
                    pass
        print(f"+{ping_count} from ping ({len(ips_to_ping)} probed)")
    else:
        print("skipped (no additional IPs)")

    # Phase 3: Reverse DNS for all discovered hosts
    print("  [3/3] Reverse DNS...", end=" ", flush=True)
    resolved = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        future_to_ip = {pool.submit(resolve_hostname, ip): ip for ip in hosts}
        for future in concurrent.futures.as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                hostname = future.result()
                if hostname:
                    hosts[ip].hostname = hostname
                    resolved += 1
            except Exception:
                pass
    print(f"{resolved} resolved")

    return sorted(hosts.values(), key=lambda h: ipaddress.IPv4Address(h.ip))


# ── Port Scanning ────────────────────────────────────────────────────

PORTS_TO_CHECK = {
    445: "SMB",
    5985: "WinRM-HTTP",
    5986: "WinRM-HTTPS",
    22: "SSH",
    3389: "RDP",
    135: "WMI/DCOM",
}


def check_port(ip: str, port: int, timeout: float = 2.0) -> bool:
    """TCP connect check. Returns True if port is open."""
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.close()
        return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def scan_host_ports(host: HostInfo) -> None:
    """Scan all target ports on a host."""
    for port in PORTS_TO_CHECK:
        host.ports[port] = check_port(host.ip, port)
    host.rdp_open = host.ports.get(3389, False)


def scan_all_ports(hosts: list[HostInfo]) -> None:
    """Scan ports on all hosts in parallel."""
    print(f"  Scanning {len(PORTS_TO_CHECK)} ports on {len(hosts)} hosts...", end=" ", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        futures = [pool.submit(scan_host_ports, h) for h in hosts]
        concurrent.futures.wait(futures)
    total_open = sum(sum(1 for v in h.ports.values() if v) for h in hosts)
    print(f"{total_open} open ports found")


# ── SMB Checks ───────────────────────────────────────────────────────

def check_smb_shares(host: HostInfo) -> None:
    """Enumerate SMB shares on a host via 'net view'."""
    if not host.ports.get(445, False):
        return
    try:
        result = subprocess.run(
            ["net", "view", f"\\\\{host.ip}"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # Share lines typically start with the share name followed by spaces and "Disk"
                parts = line.split()
                if len(parts) >= 2 and parts[-1] in ("Disk", "IPC"):
                    host.smb_shares.append(parts[0])
    except Exception as e:
        host.errors.append(f"SMB enum: {e}")


# ── WinRM Checks ─────────────────────────────────────────────────────

def check_winrm_http(host: HostInfo) -> None:
    """Check if WinRM HTTP endpoint responds."""
    if not host.ports.get(5985, False):
        return
    try:
        urlopen(f"http://{host.ip}:5985/wsman", timeout=3)
        host.winrm_http_ok = True  # 200 = unusual but OK
    except URLError as e:
        # HTTP 401/403 = WinRM is running (expected, needs auth)
        if hasattr(e, "code") and e.code in (401, 403):
            host.winrm_http_ok = True
        else:
            host.winrm_http_ok = False
    except Exception:
        host.winrm_http_ok = False


# ── SSH Checks ────────────────────────────────────────────────────────

def check_ssh_banner(host: HostInfo) -> None:
    """Grab SSH banner if port 22 is open."""
    if not host.ports.get(22, False):
        return
    try:
        sock = socket.create_connection((host.ip, 22), timeout=3)
        banner = sock.recv(256).decode("utf-8", errors="replace").strip()
        sock.close()
        host.ssh_banner = banner
    except Exception:
        pass


# ── User Detection ───────────────────────────────────────────────────

def check_nbtstat(host: HostInfo) -> None:
    """Check NetBIOS name table for logged-in user via nbtstat -A.

    The <03> UNIQUE suffix in the NetBIOS name table indicates a messenger
    service registration, which is typically the logged-in username (distinct
    from the computer name which also appears as <00> UNIQUE).
    """
    try:
        result = subprocess.run(
            ["nbtstat", "-A", host.ip],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        computer_name = None
        for line in result.stdout.splitlines():
            line_stripped = line.strip()
            if "<00>" in line_stripped and "UNIQUE" in line_stripped:
                name = line_stripped.split("<")[0].strip()
                if computer_name is None:
                    computer_name = name
            elif "<03>" in line_stripped and "UNIQUE" in line_stripped:
                name = line_stripped.split("<")[0].strip()
                if name and computer_name and name.upper() != computer_name.upper():
                    host.logged_in_user = name
                    return
    except Exception as e:
        host.errors.append(f"nbtstat: {e}")


def check_query_user(host: HostInfo) -> None:
    """Check for logged-in sessions via 'query user /server:<host>'.

    Uses the Remote Desktop Services API. Requires RDP (3389) or
    Remote Desktop Services to be accessible.

    Output format:
     USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME
    >john.smith            console             1  Active      none   2/19/2026 8:30
    """
    try:
        result = subprocess.run(
            ["query", "user", f"/server:{host.ip}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        lines = result.stdout.splitlines()
        for line in lines:
            # Skip header and empty lines
            if not line.strip() or "USERNAME" in line.upper():
                continue
            # Active session may have '>' prefix
            clean = line.lstrip(">").lstrip()
            parts = clean.split()
            if len(parts) < 3:
                continue
            username = parts[0]
            # Find state — look for Active/Disc keywords
            state = "unknown"
            session_name = ""
            for i, p in enumerate(parts[1:], 1):
                if p.lower() in ("active", "disc", "disconnected"):
                    state = p.lower()
                    # Session name is everything between username and the ID before state
                    if i >= 3:
                        session_name = parts[1]
                    break
            session_info = {
                "username": username,
                "session": session_name,
                "state": state,
            }
            host.sessions.append(session_info)
            # Prefer active session user
            if not host.logged_in_user and state == "active":
                host.logged_in_user = username
            elif not host.logged_in_user:
                host.logged_in_user = username
    except Exception as e:
        host.errors.append(f"query user: {e}")


# ── PowerShell Remoting ──────────────────────────────────────────────

def check_ps_remoting(host: HostInfo, ps_path: str) -> bool:
    """Test PowerShell remoting via Test-WSMan."""
    if not host.ports.get(5985, False) or not ps_path:
        return False
    try:
        result = subprocess.run(
            [ps_path, "-NoProfile", "-Command",
             f"Test-WSMan -ComputerName {host.ip} -ErrorAction Stop"],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0 and "wsmid" in result.stdout.lower()
    except Exception:
        return False


# ── Recommendations ──────────────────────────────────────────────────

def generate_recommendations(hosts: list[HostInfo]) -> list[Recommendation]:
    """Generate traffic-light recommendations based on probe results."""
    workstations = [h for h in hosts if any(h.ports.get(p, False) for p in [445, 5985, 22, 3389])]
    recs = []

    # SMB
    smb_hosts = [h for h in workstations if h.ports.get(445, False)]
    if len(smb_hosts) >= 3:
        rating = "GREEN"
        summary = f"All {len(smb_hosts)} workstations have SMB (445) open."
    elif smb_hosts:
        rating = "YELLOW"
        summary = f"Only {len(smb_hosts)} host(s) have SMB open."
    else:
        rating = "RED"
        summary = "No hosts with SMB access found."
    recs.append(Recommendation(
        approach="SMB Network Shares",
        rating=rating,
        hosts_supporting=[h.hostname or h.ip for h in smb_hosts],
        summary=summary,
        details=[
            "Copy project files to \\\\host\\share, run locally, copy results back.",
            "Zero IT friction — uses existing Windows file sharing.",
            "Simplest Phase 1 approach for distributed HEC-RAS.",
        ]
    ))

    # WinRM
    winrm_hosts = [h for h in workstations if h.winrm_http_ok]
    if len(winrm_hosts) >= 3:
        rating = "GREEN"
        summary = f"WinRM HTTP endpoint responding on {len(winrm_hosts)} hosts."
    elif winrm_hosts:
        rating = "YELLOW"
        summary = f"WinRM available on {len(winrm_hosts)} host(s) only."
    else:
        # Check if port is open but endpoint not responding
        port_open = [h for h in workstations if h.ports.get(5985, False)]
        if port_open:
            rating = "YELLOW"
            summary = f"Port 5985 open on {len(port_open)} hosts but WinRM endpoint not responding."
        else:
            rating = "RED"
            summary = "No WinRM access. Ask IT to enable via GPO."
    recs.append(Recommendation(
        approach="WinRM / PowerShell Remoting",
        rating=rating,
        hosts_supporting=[h.hostname or h.ip for h in winrm_hosts],
        summary=summary,
        details=[
            "Execute Ras.exe remotely via Invoke-Command or pywinrm.",
            "Requires WinRM service + firewall rule on target machines.",
            "Best combined with SMB for file transfer.",
        ]
    ))

    # SSH
    ssh_hosts = [h for h in workstations if h.ports.get(22, False)]
    if len(ssh_hosts) >= 3:
        rating = "GREEN"
        summary = f"SSH (port 22) open on {len(ssh_hosts)} hosts."
    elif ssh_hosts:
        rating = "YELLOW"
        summary = f"SSH available on only {len(ssh_hosts)} host(s)."
    else:
        rating = "RED"
        summary = "No SSH access. OpenSSH Server not enabled on any host."
    recs.append(Recommendation(
        approach="SSH (OpenSSH)",
        rating=rating,
        hosts_supporting=[h.hostname or h.ip for h in ssh_hosts],
        summary=summary,
        details=[
            "Windows 10/11 has built-in OpenSSH Server (optional feature).",
            "Requires admin to enable or GPO deployment.",
            f"Banners: {', '.join(h.ssh_banner for h in ssh_hosts if h.ssh_banner) or 'N/A'}",
        ]
    ))

    # HTTP Worker (potential — no ports to check yet, just assess feasibility)
    recs.append(Recommendation(
        approach="HTTP Worker Service (custom)",
        rating="YELLOW",
        hosts_supporting=[h.hostname or h.ip for h in smb_hosts],
        summary="Not deployed yet — requires installing worker .exe on each machine.",
        details=[
            "Lightweight FastAPI worker packaged as PyInstaller .exe.",
            "One firewall port exception per machine.",
            "Falls back to SMB file queue if firewall blocked.",
            "Recommended Phase 2 approach after SMB file queue is proven.",
        ]
    ))

    # RDP
    rdp_hosts = [h for h in workstations if h.rdp_open]
    recs.append(Recommendation(
        approach="RDP (Remote Desktop)",
        rating="YELLOW" if rdp_hosts else "RED",
        hosts_supporting=[h.hostname or h.ip for h in rdp_hosts],
        summary=f"RDP open on {len(rdp_hosts)} hosts. Interactive only — not for automation."
            if rdp_hosts else "No RDP access detected.",
        details=[
            "RDP confirms machines are general-purpose workstations.",
            "Not suitable for automated job distribution (interactive sessions only).",
            "Useful for manual troubleshooting of remote workers.",
        ]
    ))

    return recs


# ── Report Formatting ────────────────────────────────────────────────

RATING_SYMBOLS = {"GREEN": "[OK]", "YELLOW": "[??]", "RED": "[XX]"}
RATING_COLORS = {"GREEN": "\033[92m", "YELLOW": "\033[93m", "RED": "\033[91m"}
RESET = "\033[0m"


def format_console_report(result: ProbeResult) -> str:
    """Format the probe result as a console report."""
    lines = []
    w = 65

    lines.append("=" * w)
    lines.append("  Network Capability Probe for Distributed HEC-RAS Computing")
    lines.append(f"  {result.timestamp} | Duration: {result.duration_seconds:.1f}s")
    lines.append("=" * w)

    # Local machine
    loc = result.local
    lines.append("")
    lines.append("LOCAL MACHINE")
    lines.append(f"  Hostname:       {loc.hostname}")
    lines.append(f"  User:           {loc.domain}\\{loc.username}")
    lines.append(f"  Domain joined:  {'Yes' if loc.is_domain_joined else 'No'}")
    lines.append(f"  Admin:          {'Yes' if loc.is_admin else 'No (standard user)'}")
    lines.append(f"  IP:             {', '.join(loc.ip_addresses) or 'unknown'}")
    lines.append(f"  Subnet:         {loc.subnet or 'unknown'}")
    lines.append(f"  CPU cores:      {loc.cpu_cores}")
    lines.append(f"  RAM:            {loc.ram_gb} GB")
    lines.append(f"  OS:             {loc.os_version}")
    lines.append(f"  Python:         {loc.python_version} at {loc.python_path}")
    if loc.hecras_path:
        lines.append(f"  HEC-RAS:        {loc.hecras_version} at {loc.hecras_path}")
    else:
        lines.append("  HEC-RAS:        Not found in registry")
    lines.append(f"  HEC-RAS COM:    {'OK' if loc.hecras_com_ok else 'Not available'}")
    lines.append(f"  WinRM service:  {loc.winrm_service}")
    lines.append(f"  SSH service:    {loc.ssh_service}")
    lines.append(f"  PowerShell:     {loc.powershell_path or 'Not found'}")
    lines.append(f"  Firewall:       {loc.firewall_profile or 'Unknown'}")

    if not result.hosts:
        lines.append("")
        lines.append("(No network scan performed — use without --local-only to scan)")
        return "\n".join(lines)

    # Network discovery
    lines.append("")
    lines.append("NETWORK DISCOVERY")
    lines.append(f"  Subnet:         {loc.subnet or 'auto-detected'}")
    lines.append(f"  Hosts found:    {len(result.hosts)}")

    # Host details
    lines.append("")
    lines.append("HOST DETAILS")
    for h in result.hosts:
        open_ports = [f"{p}({PORTS_TO_CHECK.get(p, '?')})"
                      for p, v in sorted(h.ports.items()) if v]
        name = h.hostname or "unknown"
        user_str = f"  user: {h.logged_in_user}" if h.logged_in_user else ""
        shares = f"  shares: {', '.join(h.smb_shares)}" if h.smb_shares else ""
        lines.append(f"  {h.ip:<16} {name:<25} {('user: ' + h.logged_in_user) if h.logged_in_user else '(no user)':<25} ports: {' '.join(open_ports)}{shares}")

    # Recommendations
    lines.append("")
    lines.append("DISTRIBUTION APPROACH ASSESSMENT")
    lines.append("-" * w)
    for rec in result.recommendations:
        sym = RATING_SYMBOLS.get(rec.rating, "[??]")
        lines.append(f"  {sym} {rec.approach:<30} ({len(rec.hosts_supporting)} hosts)")
        lines.append(f"      {rec.summary}")
        for detail in rec.details:
            lines.append(f"      - {detail}")
        lines.append("")

    # Best approach
    lines.append("-" * w)
    green_recs = [r for r in result.recommendations if r.rating == "GREEN"]
    if green_recs:
        best = green_recs[0]
        lines.append(f"  RECOMMENDED: {best.approach}")
        lines.append(f"  {best.summary}")
        if best.hosts_supporting:
            lines.append(f"  Available hosts: {', '.join(best.hosts_supporting[:10])}")
    else:
        yellow_recs = [r for r in result.recommendations if r.rating == "YELLOW"]
        if yellow_recs:
            best = yellow_recs[0]
            lines.append(f"  BEST AVAILABLE (limited): {best.approach}")
            lines.append(f"  {best.summary}")
        else:
            lines.append("  No viable distribution approaches detected.")
            lines.append("  Consider: SMB file queue (requires shared folder) or cloud execution.")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────

def run_probe(
    local_only: bool = False,
    target_host: str | None = None,
    subnet_override: str | None = None,
) -> ProbeResult:
    """Run the full network probe and return results."""
    start = time.time()
    result = ProbeResult(
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Phase 1: Local machine
    print("\n[Phase 1] Local machine checks...")
    result.local = check_local_machine()
    print(f"  Done. {result.local.hostname} / {result.local.domain}\\{result.local.username}")

    if local_only:
        result.duration_seconds = round(time.time() - start, 1)
        return result

    # Determine subnet
    subnet = subnet_override
    if not subnet and target_host:
        subnet = f"{target_host}/32"
    if not subnet:
        subnet = result.local.subnet
    if not subnet and result.local.ip_addresses:
        # Assume /24
        ip = result.local.ip_addresses[0]
        subnet = str(ipaddress.IPv4Network(f"{ip}/24", strict=False))
    if not subnet:
        print("  ERROR: Could not determine subnet. Use --subnet or --host.")
        result.duration_seconds = round(time.time() - start, 1)
        return result

    # Phase 2: Network discovery
    print(f"\n[Phase 2] Network discovery ({subnet})...")
    if target_host:
        # Single host mode
        host = HostInfo(ip=target_host, online=ping_host(target_host), source="manual")
        host.hostname = resolve_hostname(target_host)
        result.hosts = [host] if host.online else []
        if not host.online:
            print(f"  {target_host} is not responding to ping.")
            # Still try port scan — host may block ICMP
            host.online = True
            result.hosts = [host]
            print(f"  Proceeding with port scan anyway (host may block ICMP).")
    else:
        result.hosts = discover_hosts(subnet)

    if not result.hosts:
        print("  No hosts discovered.")
        result.duration_seconds = round(time.time() - start, 1)
        return result

    # Filter out our own IP
    my_ips = set(result.local.ip_addresses)
    result.hosts = [h for h in result.hosts if h.ip not in my_ips]
    print(f"  {len(result.hosts)} remote hosts to probe (excluding self)")

    # Phase 3: Port scanning
    print(f"\n[Phase 3] Port scanning...")
    scan_all_ports(result.hosts)

    # Phase 4: Service checks
    print("\n[Phase 4] Service checks...")
    for h in result.hosts:
        check_smb_shares(h)
        check_winrm_http(h)
        check_ssh_banner(h)

    smb_count = sum(1 for h in result.hosts if h.smb_shares)
    winrm_count = sum(1 for h in result.hosts if h.winrm_http_ok)
    ssh_count = sum(1 for h in result.hosts if h.ssh_banner)
    print(f"  SMB shares: {smb_count} hosts | WinRM: {winrm_count} hosts | SSH: {ssh_count} hosts")

    # Phase 4b: User detection
    print("\n[Phase 4b] User detection...")
    print("  [1/2] NetBIOS name table (nbtstat)...", end=" ", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(check_nbtstat, h) for h in result.hosts
                   if h.ports.get(445, False)]
        concurrent.futures.wait(futures)
    nbt_count = sum(1 for h in result.hosts if h.logged_in_user)
    print(f"{nbt_count} users found")

    print("  [2/2] Query user sessions...", end=" ", flush=True)
    # Only try query user on hosts where nbtstat didn't find a user and RDP is open
    candidates = [h for h in result.hosts
                  if not h.logged_in_user and h.ports.get(3389, False)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(check_query_user, h) for h in candidates]
        concurrent.futures.wait(futures)
    qu_count = sum(1 for h in candidates if h.logged_in_user)
    total_users = sum(1 for h in result.hosts if h.logged_in_user)
    print(f"+{qu_count} from query user ({total_users} total)")

    # Phase 5: Recommendations
    print(f"\n[Phase 5] Generating recommendations...")
    result.recommendations = generate_recommendations(result.hosts)

    result.duration_seconds = round(time.time() - start, 1)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Network Capability Probe for Distributed HEC-RAS Computing"
    )
    parser.add_argument("--local-only", action="store_true",
                        help="Only check local machine (zero network traffic)")
    parser.add_argument("--host", type=str, default=None,
                        help="Probe a single host instead of subnet sweep")
    parser.add_argument("--subnet", type=str, default=None,
                        help="Override auto-detected subnet (e.g., 10.0.1.0/24)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON instead of console report")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Save output to file")
    args = parser.parse_args()

    result = run_probe(
        local_only=args.local_only,
        target_host=args.host,
        subnet_override=args.subnet,
    )

    if args.json:
        output = json.dumps(asdict(result), indent=2)
    else:
        output = format_console_report(result)

    print("\n" + output)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
