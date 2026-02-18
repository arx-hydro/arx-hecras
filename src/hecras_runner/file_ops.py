"""File operations: temp copy, DSS patching, result copy-back, cleanup."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Callable

_U_FILE_PATTERN = re.compile(r"\.u\d{2}$", re.IGNORECASE)

# Extensions whose suffix indicates result files to copy back.
# Each gets matched as ".{ext}{suffix}" (e.g. ".p03", ".b03").
_RESULT_EXTENSIONS = ("p", "u", "x", "g", "c", "b", "bco", "dss", "ic.o")


def copy_project_to_temp(
    project_path: str,
    dss_path: str | None = None,
    log: Callable[[str], None] = print,
) -> str:
    """Copy the entire project directory to a temp dir.

    Returns the path to the .prj file inside the temp directory.
    If *dss_path* is provided, all DSS File= lines are overwritten with that path.
    Otherwise, DSS paths are automatically fixed so that files already present
    in the temp copy are referenced by filename (relative), while truly external
    DSS files keep their original absolute paths.
    """
    project_path = os.path.abspath(project_path)
    original_folder = os.path.dirname(project_path)
    temp_dir = tempfile.mkdtemp(prefix="HECRAS_")
    log(f"Copying project to temporary folder: {temp_dir}")

    for item in os.listdir(original_folder):
        src = os.path.join(original_folder, item)
        dst = os.path.join(temp_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    if dss_path:
        update_dss_paths(temp_dir, dss_path, log=log)
    else:
        _fix_dss_paths_for_temp(temp_dir, log=log)

    return os.path.join(temp_dir, os.path.basename(project_path))


def update_dss_paths(
    directory: str,
    new_dss_path: str,
    log: Callable[[str], None] = print,
) -> int:
    """Rewrite ``DSS File=`` lines in all ``.u##`` files in *directory*.

    Returns the number of files modified.
    """
    normalized = os.path.normpath(new_dss_path)
    count = 0

    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath):
            continue
        if not _U_FILE_PATTERN.search(filename):
            continue

        try:
            with open(filepath, encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(filepath, encoding="latin-1") as f:
                lines = f.readlines()

        new_lines = []
        modified = False
        for line in lines:
            if line.startswith("DSS File="):
                new_lines.append(f"DSS File={normalized}\n")
                modified = True
            else:
                new_lines.append(line)

        if modified:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            log(f"Updated DSS path in {filename}")
            count += 1

    return count


def _fix_dss_paths_for_temp(
    directory: str,
    log: Callable[[str], None] = print,
) -> int:
    """Rewrite absolute ``DSS File=`` paths to relative when the file exists in *directory*.

    This handles the case where .u## files contain absolute paths (e.g.
    ``C:\\OldMachine\\project\\100yCC_2024.dss``) but the DSS file was copied
    into the temp directory alongside everything else. The filename is extracted
    and if it exists in *directory*, the path is rewritten to just the filename
    so HEC-RAS resolves it relative to the project.

    Paths that are already relative, or whose file is NOT in *directory*
    (truly external DSS files), are left unchanged.

    Returns the number of files modified.
    """
    temp_files_lower = {f.lower() for f in os.listdir(directory)}
    count = 0

    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath):
            continue
        if not _U_FILE_PATTERN.search(filename):
            continue

        try:
            with open(filepath, encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(filepath, encoding="latin-1") as f:
                lines = f.readlines()

        new_lines = []
        modified = False
        for line in lines:
            if line.startswith("DSS File="):
                dss_value = line[len("DSS File=") :].strip()
                # Only fix absolute paths whose file exists in the temp dir
                if os.path.isabs(dss_value):
                    basename = os.path.basename(dss_value)
                    if basename.lower() in temp_files_lower:
                        new_lines.append(f"DSS File={basename}\n")
                        modified = True
                        continue
                new_lines.append(line)
            else:
                new_lines.append(line)

        if modified:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            log(f"Fixed DSS paths in {filename}")
            count += 1

    return count


def copy_results_back(
    temp_path: str,
    main_dir: str,
    plan_suffix: str,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Copy result files from *temp_path* back to *main_dir*.

    Matches files by extension+suffix pattern (e.g. ``.p03``, ``.p03.hdf``).
    Returns a list of copied filenames.
    """
    temp_dir = os.path.dirname(temp_path) if os.path.isfile(temp_path) else temp_path
    copied: list[str] = []

    for filename in os.listdir(temp_dir):
        src = os.path.join(temp_dir, filename)
        if not os.path.isfile(src):
            continue

        lower = filename.lower()
        matched = False

        # Check extension+suffix patterns (e.g. ".p03", ".b03")
        for ext in _RESULT_EXTENSIONS:
            expected = f".{ext}{plan_suffix}".lower()
            if lower.endswith(expected):
                matched = True
                break

        # Check HDF pattern (e.g. ".p03.hdf")
        if not matched:
            for ext in ("p", "u", "g"):
                if lower.endswith(f".{ext}{plan_suffix}.hdf"):
                    matched = True
                    break

        if matched:
            dst = os.path.join(main_dir, filename)
            try:
                shutil.copy2(src, dst)
                log(f"Copied: {filename}")
                copied.append(filename)
            except OSError as e:
                log(f"Error copying {filename}: {e}")

    return copied


def cleanup_temp_dir(
    temp_dir: str,
    log: Callable[[str], None] = print,
) -> None:
    """Remove a temporary directory tree."""
    try:
        shutil.rmtree(temp_dir)
        log(f"Cleaned up: {temp_dir}")
    except OSError as e:
        log(f"Error cleaning up {temp_dir}: {e}")
