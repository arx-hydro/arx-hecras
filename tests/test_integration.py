"""Integration tests that run actual HEC-RAS simulations.

These tests require HEC-RAS 6.6 to be installed and are skipped otherwise.
Run with: pytest -m integration
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hecras_runner.parser import parse_project
from hecras_runner.runner import (
    SimulationJob,
    check_hecras_installed,
    find_hecras_exe,
    run_simulations,
)

REPO_ROOT = Path(__file__).parent.parent
PROJECT_DIR = REPO_ROOT / "test_projects"

# Skip entire module if HEC-RAS is not installed
pytestmark = pytest.mark.integration


@pytest.fixture
def integration_project(tmp_path: Path) -> Path:
    """Copy small_project_01 to a temp directory, returning the .prj path.

    The runner creates its own temp copies internally, so this gives double
    isolation — the source tree is never touched.
    """
    src = PROJECT_DIR
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        dest = tmp_path / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    prj = tmp_path / "small_project_01.prj"
    assert prj.exists(), f"small_project_01.prj not found in {tmp_path}"
    return prj


def _skip_if_no_hecras_com() -> None:
    """Skip test if HEC-RAS COM server is not available."""
    if not check_hecras_installed(backend="com", log=lambda msg: None):
        pytest.skip("HEC-RAS 6.6 not installed or COM server unavailable")


def _skip_if_no_hecras_cli() -> None:
    """Skip test if Ras.exe is not available."""
    if not find_hecras_exe(log=lambda msg: None):
        pytest.skip("HEC-RAS Ras.exe not found")


@pytest.mark.integration
class TestFullSimulation:
    """End-to-end tests that run HEC-RAS plans via COM."""

    def test_run_all_plans_parallel(self, integration_project: Path) -> None:
        """Run all 4 plans in parallel and verify success."""
        _skip_if_no_hecras_com()

        project = parse_project(str(integration_project))
        assert len(project.plans) == 4

        # Build jobs from parsed plans (matches CLI/GUI pattern)
        dss_path = str(integration_project.parent / "100yCC_2024.dss")
        jobs = [
            SimulationJob(
                plan_name=plan.title,
                plan_suffix=plan.key[1:],  # "p03" -> "03"
                dss_path=dss_path,
            )
            for plan in project.plans
        ]

        log_messages: list[str] = []
        results = run_simulations(
            project_path=str(integration_project),
            jobs=jobs,
            parallel=True,
            show_ras=False,
            backend="com",
            log=log_messages.append,
        )

        assert len(results) == 4
        for result in results:
            assert result.success, f"{result.plan_name} failed: {result.error_message}"
            assert result.elapsed_seconds > 0
            assert len(result.files_copied) > 0

        # Verify .p##.hdf result files exist in the project directory
        proj_dir = integration_project.parent
        for plan in project.plans:
            hdf = proj_dir / f"small_project_01.{plan.key}.hdf"
            assert hdf.exists(), f"Expected result HDF not found: {hdf}"

    def test_run_single_plan_sequential(self, integration_project: Path) -> None:
        """Smoke test: run 1 plan sequentially via COM."""
        _skip_if_no_hecras_com()

        project = parse_project(str(integration_project))
        plan = project.plans[0]

        dss_path = str(integration_project.parent / "100yCC_2024.dss")
        jobs = [
            SimulationJob(
                plan_name=plan.title,
                plan_suffix=plan.key[1:],
                dss_path=dss_path,
            )
        ]

        results = run_simulations(
            project_path=str(integration_project),
            jobs=jobs,
            parallel=False,
            show_ras=False,
            backend="com",
            log=lambda msg: None,
        )

        assert len(results) == 1
        assert results[0].success, f"Failed: {results[0].error_message}"
        assert results[0].elapsed_seconds > 0


@pytest.mark.integration
class TestCliSimulation:
    """End-to-end tests that run HEC-RAS plans via Ras.exe -c."""

    def test_run_single_plan_cli(self, integration_project: Path) -> None:
        """Run 1 plan via CLI backend and verify HDF completion."""
        _skip_if_no_hecras_cli()

        project = parse_project(str(integration_project))
        plan = project.plans[0]

        dss_path = str(integration_project.parent / "100yCC_2024.dss")
        jobs = [
            SimulationJob(
                plan_name=plan.title,
                plan_suffix=plan.key[1:],
                dss_path=dss_path,
            )
        ]

        log_messages: list[str] = []
        results = run_simulations(
            project_path=str(integration_project),
            jobs=jobs,
            parallel=False,
            backend="cli",
            log=log_messages.append,
        )

        assert len(results) == 1
        assert results[0].success, f"Failed: {results[0].error_message}"
        assert results[0].elapsed_seconds > 0

        # Verify HDF result file exists
        proj_dir = integration_project.parent
        hdf = proj_dir / f"small_project_01.{plan.key}.hdf"
        assert hdf.exists(), f"Expected result HDF not found: {hdf}"
