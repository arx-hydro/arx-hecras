"""SMB file transfer for distributed HEC-RAS execution.

Zero external deps — uses stdlib only (shutil, os, json, hashlib).
Handles project distribution to a central SMB share and result collection.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

# Extensions that belong to a specific plan (suffix-matched)
_RESULT_EXTENSIONS = ("p", "u", "x", "g", "c", "b", "bco", "dss", "ic.o")


@dataclass
class TransferManifest:
    """Describes files transferred to a share for a job."""

    job_id: str
    project_name: str
    plan_suffix: str
    share_project_dir: str
    share_results_dir: str
    terrain_hash: str = ""
    files: list[str] = field(default_factory=list)


def project_to_share(
    project_path: str,
    share_base: str,
    job_id: str,
    plan_suffix: str,
    log: Callable[[str], None] = print,
) -> TransferManifest:
    """Copy a project to the SMB share for a specific job.

    Layout::

        {share_base}/projects/{job_id}/   — project files + manifest.json
        {share_base}/results/{job_id}/    — (created empty, filled by worker)
    """
    project_path = os.path.abspath(project_path)
    project_dir = os.path.dirname(project_path)
    project_name = os.path.splitext(os.path.basename(project_path))[0]

    share_project_dir = os.path.join(share_base, "projects", job_id)
    share_results_dir = os.path.join(share_base, "results", job_id)

    os.makedirs(share_project_dir, exist_ok=True)
    os.makedirs(share_results_dir, exist_ok=True)

    files_copied: list[str] = []

    for item in os.listdir(project_dir):
        src = os.path.join(project_dir, item)
        dst = os.path.join(share_project_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            files_copied.append(f"{item}/")
        else:
            shutil.copy2(src, dst)
            files_copied.append(item)

    terrain_hash = compute_terrain_hash(project_dir)

    manifest = TransferManifest(
        job_id=job_id,
        project_name=project_name,
        plan_suffix=plan_suffix,
        share_project_dir=share_project_dir,
        share_results_dir=share_results_dir,
        terrain_hash=terrain_hash,
        files=files_copied,
    )

    # Write manifest
    manifest_path = os.path.join(share_project_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, indent=2)

    log(f"Uploaded {len(files_copied)} items to {share_project_dir}")
    return manifest


def share_to_local(
    manifest: TransferManifest,
    local_temp_dir: str,
    log: Callable[[str], None] = print,
    terrain_cache_dir: str | None = None,
) -> str:
    """Copy project from share to a local temp directory.

    Returns the path to the .prj file in the local copy.
    If *terrain_cache_dir* is provided, attempts to use cached terrain data.
    """
    os.makedirs(local_temp_dir, exist_ok=True)
    share_dir = manifest.share_project_dir

    # Check terrain cache
    terrain_cached = False
    if terrain_cache_dir and manifest.terrain_hash:
        cache_path = os.path.join(terrain_cache_dir, manifest.terrain_hash)
        if os.path.isdir(cache_path):
            log("Using cached terrain data")
            terrain_cached = True

    for item in os.listdir(share_dir):
        if item == "manifest.json":
            continue

        src = os.path.join(share_dir, item)
        dst = os.path.join(local_temp_dir, item)

        if os.path.isdir(src):
            # Skip terrain copy if cached
            if terrain_cached and item.lower() == "terrain":
                # Symlink or copy from cache
                cache_terrain = os.path.join(terrain_cache_dir, manifest.terrain_hash)
                shutil.copytree(cache_terrain, dst, dirs_exist_ok=True)
                continue
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    # Update terrain cache
    if terrain_cache_dir and manifest.terrain_hash and not terrain_cached:
        terrain_src = os.path.join(local_temp_dir, "Terrain")
        if os.path.isdir(terrain_src):
            cache_path = os.path.join(terrain_cache_dir, manifest.terrain_hash)
            os.makedirs(cache_path, exist_ok=True)
            shutil.copytree(terrain_src, cache_path, dirs_exist_ok=True)
            log(f"Cached terrain data ({manifest.terrain_hash[:12]}...)")

    prj_path = os.path.join(local_temp_dir, f"{manifest.project_name}.prj")
    log(f"Downloaded project to {local_temp_dir}")
    return prj_path


def results_to_share(
    local_prj: str,
    share_results_dir: str,
    plan_suffix: str,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Copy result files from a local run to the share results directory.

    Uses the same extension+suffix matching as file_ops.copy_results_back().
    Returns a list of copied filenames.
    """
    local_dir = os.path.dirname(local_prj) if os.path.isfile(local_prj) else local_prj
    os.makedirs(share_results_dir, exist_ok=True)
    copied: list[str] = []

    for filename in os.listdir(local_dir):
        src = os.path.join(local_dir, filename)
        if not os.path.isfile(src):
            continue

        if is_result_file(filename, plan_suffix):
            dst = os.path.join(share_results_dir, filename)
            shutil.copy2(src, dst)
            copied.append(filename)

    log(f"Uploaded {len(copied)} result files to share")
    return copied


def results_from_share(
    share_results_dir: str,
    main_dir: str,
    plan_suffix: str,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Copy result files from the share back to the submitter's project dir.

    Returns a list of copied filenames.
    """
    if not os.path.isdir(share_results_dir):
        log(f"Results directory not found: {share_results_dir}")
        return []

    copied: list[str] = []
    for filename in os.listdir(share_results_dir):
        src = os.path.join(share_results_dir, filename)
        if not os.path.isfile(src):
            continue

        if is_result_file(filename, plan_suffix):
            dst = os.path.join(main_dir, filename)
            shutil.copy2(src, dst)
            copied.append(filename)

    log(f"Downloaded {len(copied)} result files from share")
    return copied


def is_result_file(filename: str, plan_suffix: str) -> bool:
    """Check if a filename matches result extension+suffix patterns."""
    lower = filename.lower()

    for ext in _RESULT_EXTENSIONS:
        if lower.endswith(f".{ext}{plan_suffix}".lower()):
            return True

    # HDF patterns (e.g. ".p03.hdf")
    return any(lower.endswith(f".{ext}{plan_suffix}.hdf") for ext in ("p", "u", "g"))


def verify_transfer(
    source: str,
    dest: str,
    log: Callable[[str], None] = print,
) -> bool:
    """Verify a file was transferred correctly via size comparison.

    Fast check that catches SMB truncation issues.
    """
    try:
        src_size = os.path.getsize(source)
        dst_size = os.path.getsize(dest)
        if src_size != dst_size:
            log(f"Size mismatch: {source} ({src_size}) vs {dest} ({dst_size})")
            return False
        return True
    except OSError as e:
        log(f"Verify failed: {e}")
        return False


def compute_terrain_hash(project_dir: str) -> str:
    """Compute a fast hash of terrain directory contents.

    Uses filenames + sizes + first 4KB of each file for speed.
    Returns empty string if no Terrain directory found.
    """
    terrain_dir = os.path.join(project_dir, "Terrain")
    if not os.path.isdir(terrain_dir):
        return ""

    h = hashlib.sha256()
    for root, _dirs, files in os.walk(terrain_dir):
        for filename in sorted(files):
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, terrain_dir)
            try:
                size = os.path.getsize(filepath)
                h.update(f"{rel_path}:{size}:".encode())
                with open(filepath, "rb") as f:
                    h.update(f.read(4096))
            except OSError:
                continue

    return h.hexdigest()[:24]


def cleanup_share_job(
    share_base: str,
    job_id: str,
    log: Callable[[str], None] = print,
    retries: int = 3,
    delay: float = 1.0,
) -> None:
    """Remove job directories from the share."""
    for subdir in ("projects", "results"):
        path = os.path.join(share_base, subdir, job_id)
        if not os.path.isdir(path):
            continue
        for attempt in range(retries):
            try:
                shutil.rmtree(path)
                log(f"Cleaned up {path}")
                break
            except OSError:
                if attempt < retries - 1:
                    time.sleep(delay)
                else:
                    log(f"Could not clean up {path}")
