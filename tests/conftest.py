"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
PROJECT_PRJ = REPO_ROOT / "test_projects" / "small_project_01.prj"
SYNTHETIC_PRJ = TESTS_DIR / "synthetic" / "minimal.prj"


@pytest.fixture(scope="session")
def qapp():
    """Shared QApplication instance for tests that need Qt."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def prtest1_prj() -> Path:
    """Path to the small_project_01 project file."""
    assert PROJECT_PRJ.exists(), f"Test project not found: {PROJECT_PRJ}"
    return PROJECT_PRJ


@pytest.fixture
def synthetic_prj() -> Path:
    """Path to the minimal synthetic project file."""
    assert SYNTHETIC_PRJ.exists(), f"Synthetic project not found: {SYNTHETIC_PRJ}"
    return SYNTHETIC_PRJ


@pytest.fixture
def tmp_project(tmp_path: Path, synthetic_prj: Path) -> Path:
    """Copy the synthetic project to a temp directory and return the .prj path."""
    import shutil

    src_dir = synthetic_prj.parent
    for f in src_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, tmp_path / f.name)
    return tmp_path / "minimal.prj"
