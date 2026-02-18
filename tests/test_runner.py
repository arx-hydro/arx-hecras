"""Tests for hecras_runner.runner (COM is mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hecras_runner.runner import (
    SimulationJob,
    SimulationResult,
    check_hecras_installed,
    find_hecras_processes,
    open_parent_instance,
    refresh_parent_instance,
    run_hecras_plan,
    run_simulations,
)


def _nolog(msg: str) -> None:
    pass


class TestSimulationResult:
    def test_defaults(self):
        r = SimulationResult(
            plan_name="plan01", plan_suffix="01", success=True, elapsed_seconds=10.5
        )
        assert r.plan_name == "plan01"
        assert r.plan_suffix == "01"
        assert r.success is True
        assert r.elapsed_seconds == 10.5
        assert r.error_message is None
        assert r.files_copied == []

    def test_with_error(self):
        r = SimulationResult(
            plan_name="plan02",
            plan_suffix="02",
            success=False,
            elapsed_seconds=2.0,
            error_message="COM error",
        )
        assert r.success is False
        assert r.error_message == "COM error"

    def test_files_copied_not_shared(self):
        r1 = SimulationResult(plan_name="a", plan_suffix="01", success=True, elapsed_seconds=1.0)
        r2 = SimulationResult(plan_name="b", plan_suffix="02", success=True, elapsed_seconds=1.0)
        r1.files_copied.append("file.hdf")
        assert r2.files_copied == []


class TestCheckHecrasInstalled:
    def test_returns_true_when_available(self):
        mock_pycom = MagicMock()
        mock_w32_client = MagicMock()

        modules = {"pythoncom": mock_pycom, "win32com.client": mock_w32_client}
        with patch("hecras_runner.runner.importlib.import_module") as mock_import:
            mock_import.side_effect = lambda name: modules[name]
            result = check_hecras_installed(log=_nolog)
        assert result is True

    def test_returns_false_when_not_available(self):
        with patch(
            "hecras_runner.runner.importlib.import_module",
            side_effect=ImportError("no pywin32"),
        ):
            result = check_hecras_installed(log=_nolog)
        assert result is False


class TestRunHecrasPlan:
    @patch("time.sleep")
    def test_calls_com_methods(self, _mock_sleep):
        mock_pycom = MagicMock()
        mock_ras = MagicMock()
        mock_ras.Compute_Complete.return_value = 1  # immediate completion
        mock_w32_client = MagicMock()
        mock_w32_client.Dispatch.return_value = mock_ras

        with (
            patch("hecras_runner.runner.importlib.import_module") as mock_import,
        ):
            modules = {
                "pythoncom": mock_pycom,
                "win32com.client": mock_w32_client,
            }
            mock_import.side_effect = lambda name: modules[name]

            result = run_hecras_plan(r"C:\temp\project.prj", "plan01", show_ras=True, log=_nolog)

        assert isinstance(result, SimulationResult)
        assert result.success is True
        assert result.elapsed_seconds > 0
        mock_pycom.CoInitialize.assert_called_once()
        mock_w32_client.Dispatch.assert_called_once_with("RAS66.HECRASController")
        mock_ras.ShowRas.assert_called_once()
        mock_ras.Project_Open.assert_called_once()
        mock_ras.Plan_SetCurrent.assert_called_once_with("plan01")
        mock_ras.Compute_CurrentPlan.assert_called_once()
        mock_ras.Project_Close.assert_called_once()
        mock_ras.QuitRas.assert_called_once()
        mock_pycom.CoUninitialize.assert_called_once()

    @patch("time.sleep")
    def test_returns_failure_on_exception(self, _mock_sleep):
        with patch(
            "hecras_runner.runner.importlib.import_module",
            side_effect=ImportError("no pywin32"),
        ):
            result = run_hecras_plan(r"C:\temp\project.prj", "plan01", log=_nolog)
        assert isinstance(result, SimulationResult)
        assert result.success is False
        assert result.error_message is not None


class TestRunSimulations:
    def test_orchestration_creates_temp_and_copies_back(self, tmp_project: Path):
        """Verify run_simulations calls file_ops correctly and returns results."""
        jobs = [
            SimulationJob(plan_name="plan01", plan_suffix="01"),
        ]

        mock_result = SimulationResult(
            plan_name="plan01", plan_suffix="01", success=True, elapsed_seconds=5.0
        )
        with patch("hecras_runner.runner.run_hecras_plan") as mock_run:
            mock_run.return_value = mock_result
            messages: list[str] = []
            results = run_simulations(
                str(tmp_project),
                jobs,
                parallel=False,
                cleanup=True,
                log=messages.append,
            )

        # Should have called run_hecras_plan with a temp project path
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        temp_prj = call_args[0][0]
        assert "HECRAS_" in temp_prj
        assert temp_prj.endswith("minimal.prj")

        # Should return results
        assert len(results) == 1
        assert results[0].plan_name == "plan01"
        assert results[0].success is True

        # Temp dir should have been cleaned up
        import os

        assert not os.path.exists(os.path.dirname(temp_prj))

    def test_returns_list_of_results(self, tmp_project: Path):
        """Verify return type is list[SimulationResult]."""
        jobs = [
            SimulationJob(plan_name="plan01", plan_suffix="01"),
            SimulationJob(plan_name="plan02", plan_suffix="02"),
        ]

        mock_results = [
            SimulationResult(plan_name="plan01", plan_suffix="01", success=True, elapsed_seconds=3),
            SimulationResult(
                plan_name="plan02",
                plan_suffix="02",
                success=False,
                elapsed_seconds=1,
                error_message="fail",
            ),
        ]
        call_count = [0]

        def fake_run(*args, **kwargs):
            r = mock_results[call_count[0]]
            call_count[0] += 1
            return r

        with patch("hecras_runner.runner.run_hecras_plan", side_effect=fake_run):
            results = run_simulations(
                str(tmp_project), jobs, parallel=False, cleanup=True, log=_nolog
            )

        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False
        assert results[1].error_message == "fail"

    def test_parallel_spawns_processes(self, tmp_project: Path):
        """Verify parallel mode creates Process objects."""
        jobs = [
            SimulationJob(plan_name="plan01", plan_suffix="01"),
            SimulationJob(plan_name="plan02", plan_suffix="02"),
        ]

        with (
            patch("hecras_runner.runner.Process") as mock_process_cls,
            patch("hecras_runner.runner.Queue") as mock_queue_cls,
        ):
            mock_proc = MagicMock()
            mock_process_cls.return_value = mock_proc
            mock_q = MagicMock()
            mock_q.empty.return_value = True  # no results to drain
            mock_queue_cls.return_value = mock_q

            run_simulations(
                str(tmp_project),
                jobs,
                parallel=True,
                cleanup=True,
                log=_nolog,
            )

        assert mock_process_cls.call_count == 2
        assert mock_proc.start.call_count == 2
        assert mock_proc.join.call_count == 2

    def test_no_cleanup_leaves_temp(self, tmp_project: Path):
        """Verify cleanup=False preserves temp directories."""
        jobs = [SimulationJob(plan_name="plan01", plan_suffix="01")]

        mock_result = SimulationResult(
            plan_name="plan01", plan_suffix="01", success=True, elapsed_seconds=1.0
        )
        with patch("hecras_runner.runner.run_hecras_plan") as mock_run:
            mock_run.return_value = mock_result
            run_simulations(
                str(tmp_project),
                jobs,
                parallel=False,
                cleanup=False,
                log=_nolog,
            )

            temp_prj = mock_run.call_args[0][0]
            import os

            # Temp dir should still exist
            assert os.path.exists(os.path.dirname(temp_prj))

            # Clean up manually
            import shutil

            shutil.rmtree(os.path.dirname(temp_prj))


class TestFindHecrasProcesses:
    def test_returns_pids(self):
        fake_output = '"Ras.exe","1234","Console","1","50,000 K"\n'
        with patch("hecras_runner.runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=fake_output)
            pids = find_hecras_processes()
        assert pids == [1234]

    def test_returns_empty_on_no_match(self):
        with patch("hecras_runner.runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="INFO: No tasks are running...\n")
            pids = find_hecras_processes()
        assert pids == []

    def test_returns_empty_on_error(self):
        with patch(
            "hecras_runner.runner.subprocess.run",
            side_effect=OSError("not found"),
        ):
            pids = find_hecras_processes()
        assert pids == []


class TestParentInstance:
    def test_open_parent_instance(self):
        mock_w32_client = MagicMock()
        mock_ras = MagicMock()
        mock_w32_client.Dispatch.return_value = mock_ras

        with patch("hecras_runner.runner.importlib.import_module") as mock_import:
            mock_import.return_value = mock_w32_client
            result = open_parent_instance(r"C:\project\test.prj", log=_nolog)

        assert result is mock_ras
        mock_ras.ShowRas.assert_called_once()
        mock_ras.Project_Open.assert_called_once_with(r"C:\project\test.prj")

    def test_refresh_parent_instance(self):
        mock_ras = MagicMock()
        refresh_parent_instance(mock_ras, r"C:\project\test.prj", log=_nolog)
        mock_ras.Project_Open.assert_called_once_with(r"C:\project\test.prj")

    def test_refresh_handles_stale_reference(self):
        mock_ras = MagicMock()
        mock_ras.Project_Open.side_effect = Exception("RPC server unavailable")
        messages: list[str] = []
        refresh_parent_instance(mock_ras, r"C:\project\test.prj", log=messages.append)
        assert any("Could not refresh" in m for m in messages)
