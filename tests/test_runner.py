"""Tests for hecras_runner.runner (COM is mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hecras_runner.runner import (
    ProgressMessage,
    SimulationJob,
    SimulationResult,
    kill_process_tree,
    parse_sim_dates,
    run_hecras_cli,
    run_hecras_plan,
    run_simulations,
    set_current_plan,
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


class TestProgressMessage:
    def test_fields(self):
        msg = ProgressMessage(
            plan_suffix="01",
            fraction=0.5,
            timestamp="01Jan2024  12:00:00",
            elapsed_seconds=10.0,
        )
        assert msg.plan_suffix == "01"
        assert msg.fraction == 0.5
        assert msg.timestamp == "01Jan2024  12:00:00"
        assert msg.elapsed_seconds == 10.0

    def test_equality(self):
        a = ProgressMessage("01", 0.5, "ts", 1.0)
        b = ProgressMessage("01", 0.5, "ts", 1.0)
        assert a == b


class TestParsSimDates:
    def test_parses_dates(self, tmp_path: Path):
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\nSimulation Date=01JAN2024,0000,02JAN2024,1200\n")
        start, end = parse_sim_dates(str(plan))
        assert start == "01JAN2024,0000"
        assert end == "02JAN2024,1200"

    def test_missing_line(self, tmp_path: Path):
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\n")
        start, end = parse_sim_dates(str(plan))
        assert start == ""
        assert end == ""

    def test_nonexistent_file(self):
        start, end = parse_sim_dates(r"C:\nonexistent\fake.p01")
        assert start == ""
        assert end == ""


class TestSetCurrentPlan:
    def test_sets_current_plan(self, tmp_path: Path):
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\nCurrent Plan=p01\nPlan File=p01\nPlan File=p02\n")
        set_current_plan(str(prj), "p02")
        content = prj.read_text()
        assert "Current Plan=p02\n" in content
        assert "Current Plan=p01" not in content

    def test_preserves_other_lines(self, tmp_path: Path):
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\nCurrent Plan=p01\nGeom File=g02\n")
        set_current_plan(str(prj), "p03")
        content = prj.read_text()
        assert "Proj Title=test\n" in content
        assert "Geom File=g02\n" in content

    def test_inserts_if_missing(self, tmp_path: Path):
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\nPlan File=p01\n")
        set_current_plan(str(prj), "p01")
        content = prj.read_text()
        assert "Current Plan=p01\n" in content

    def test_nonexistent_file(self):
        # Should not raise
        set_current_plan(r"C:\nonexistent\fake.prj", "p01")


class TestKillProcessTree:
    def test_calls_taskkill(self):
        with patch("hecras_runner.runner.subprocess.run") as mock_run:
            kill_process_tree(1234, log=_nolog)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["taskkill", "/F", "/T", "/PID", "1234"]

    def test_handles_error(self):
        with patch(
            "hecras_runner.runner.subprocess.run",
            side_effect=OSError("not found"),
        ):
            messages: list[str] = []
            kill_process_tree(1234, log=messages.append)
        assert any("Failed" in m for m in messages)


class TestRunHecrasCli:
    def test_returns_failure_when_no_exe(self):
        with patch("hecras_runner.runner.find_hecras_exe", return_value=None):
            result = run_hecras_cli(
                r"C:\temp\project.prj",
                plan_suffix="01",
                plan_name="plan01",
                log=_nolog,
            )
        assert result.success is False

    def test_popen_oserror(self, tmp_path: Path):
        """Verify clean failure when Popen raises OSError."""
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\n")
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\n")

        with patch(
            "hecras_runner.runner.subprocess.Popen",
            side_effect=OSError("Access denied"),
        ):
            result = run_hecras_cli(
                str(prj),
                plan_suffix="01",
                plan_name="test_plan",
                ras_exe=r"C:\HEC\Ras.exe",
                log=_nolog,
            )

        assert result.success is False
        assert "Failed to start" in result.error_message

    def test_successful_run(self, tmp_path: Path):
        """Mock a successful CLI run with HDF completion."""
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\n")
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\nSimulation Date=01JAN2024,0000,02JAN2024,1200\n")
        hdf = tmp_path / "test.p01.hdf"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.pid = 9999
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""

        # HDF is created during proc.wait() (simulating HEC-RAS writing it)
        def create_hdf(timeout=None):
            hdf.write_bytes(b"\x00" * 50 + b"Finished Successfully" + b"\x00" * 50)

        mock_proc.wait.side_effect = create_hdf

        with patch("hecras_runner.runner.subprocess.Popen", return_value=mock_proc):
            result = run_hecras_cli(
                str(prj),
                plan_suffix="01",
                plan_name="test_plan",
                ras_exe=r"C:\HEC\Ras.exe",
                log=_nolog,
            )

        assert result.success is True
        assert result.plan_name == "test_plan"
        assert result.plan_suffix == "01"
        assert result.elapsed_seconds > 0

    def test_hdf_check_fails(self, tmp_path: Path):
        """Mock a run where exit code is 0 but HDF has no completion marker."""
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\n")
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\n")
        hdf = tmp_path / "test.p01.hdf"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.pid = 9999
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""

        # HDF created during wait but with no success marker
        def create_hdf(timeout=None):
            hdf.write_bytes(b"\x00" * 100)

        mock_proc.wait.side_effect = create_hdf

        with patch("hecras_runner.runner.subprocess.Popen", return_value=mock_proc):
            result = run_hecras_cli(
                str(prj),
                plan_suffix="01",
                plan_name="test_plan",
                ras_exe=r"C:\HEC\Ras.exe",
                log=_nolog,
            )

        assert result.success is False
        assert "HDF completion check failed" in result.error_message

    def test_timeout_kills_process(self, tmp_path: Path):
        """Mock a run that times out."""
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\n")
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\n")

        import subprocess as sp

        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.wait.side_effect = [sp.TimeoutExpired(cmd="Ras.exe", timeout=1), None]

        with (
            patch("hecras_runner.runner.subprocess.Popen", return_value=mock_proc),
            patch("hecras_runner.runner.kill_process_tree") as mock_kill,
        ):
            result = run_hecras_cli(
                str(prj),
                plan_suffix="01",
                plan_name="test_plan",
                ras_exe=r"C:\HEC\Ras.exe",
                timeout_seconds=1.0,
                log=_nolog,
            )

        assert result.success is False
        assert "Timeout" in result.error_message
        mock_kill.assert_called_once_with(9999, log=_nolog)

    def test_max_cores_flag(self, tmp_path: Path):
        """Verify -MaxCores is added to the command."""
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\n")
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\n")
        hdf = tmp_path / "test.p01.hdf"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.pid = 9999
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""

        def create_hdf(timeout=None):
            hdf.write_bytes(b"Finished Successfully")

        mock_proc.wait.side_effect = create_hdf

        with patch("hecras_runner.runner.subprocess.Popen", return_value=mock_proc) as mock_popen:
            run_hecras_cli(
                str(prj),
                plan_suffix="01",
                ras_exe=r"C:\HEC\Ras.exe",
                max_cores=4,
                log=_nolog,
            )

        cmd = mock_popen.call_args[0][0]
        assert "-MaxCores" in cmd
        assert "4" in cmd

    def test_result_queue(self, tmp_path: Path):
        """Verify result is put on queue when provided."""
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\n")
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\n")
        hdf = tmp_path / "test.p01.hdf"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.pid = 9999
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""

        def create_hdf(timeout=None):
            hdf.write_bytes(b"Finished Successfully")

        mock_proc.wait.side_effect = create_hdf

        mock_queue = MagicMock()

        with patch("hecras_runner.runner.subprocess.Popen", return_value=mock_proc):
            run_hecras_cli(
                str(prj),
                plan_suffix="01",
                ras_exe=r"C:\HEC\Ras.exe",
                result_queue=mock_queue,
                log=_nolog,
            )

        mock_queue.put.assert_called_once()
        queued_result = mock_queue.put.call_args[0][0]
        assert queued_result.success is True

    def test_progress_queue_patches_write_detailed(self, tmp_path: Path):
        """Verify progress_queue triggers patch_write_detailed."""
        prj = tmp_path / "test.prj"
        prj.write_text("Proj Title=test\n")
        plan = tmp_path / "test.p01"
        plan.write_text("Plan Title=test\nWrite Detailed= 0 \n")
        hdf = tmp_path / "test.p01.hdf"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.pid = 9999
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""

        def create_hdf(timeout=None):
            hdf.write_bytes(b"Finished Successfully")

        mock_proc.wait.side_effect = create_hdf

        mock_queue = MagicMock()

        with patch("hecras_runner.runner.subprocess.Popen", return_value=mock_proc):
            run_hecras_cli(
                str(prj),
                plan_suffix="01",
                ras_exe=r"C:\HEC\Ras.exe",
                progress_queue=mock_queue,
                log=_nolog,
            )

        # Write Detailed should have been patched to 1
        assert "Write Detailed= 1" in plan.read_text()


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

    @patch("time.sleep")
    def test_plan_suffix_kwarg(self, _mock_sleep):
        """Verify plan_suffix kwarg is used instead of hardcoded empty string."""
        mock_pycom = MagicMock()
        mock_ras = MagicMock()
        mock_ras.Compute_Complete.return_value = 1
        mock_w32_client = MagicMock()
        mock_w32_client.Dispatch.return_value = mock_ras

        with patch("hecras_runner.runner.importlib.import_module") as mock_import:
            modules = {"pythoncom": mock_pycom, "win32com.client": mock_w32_client}
            mock_import.side_effect = lambda name: modules[name]
            result = run_hecras_plan(r"C:\temp\project.prj", "plan01", plan_suffix="03", log=_nolog)

        assert result.plan_suffix == "03"

    @patch("time.sleep")
    def test_absorbs_extra_kwargs(self, _mock_sleep):
        """Verify **_kwargs absorbs extra dispatch kwargs without error."""
        with patch(
            "hecras_runner.runner.importlib.import_module",
            side_effect=ImportError("no pywin32"),
        ):
            result = run_hecras_plan(
                r"C:\temp\project.prj",
                "plan01",
                log=_nolog,
                max_cores=4,  # extra kwarg from dispatch
                timeout_seconds=100,  # extra kwarg from dispatch
            )
        assert isinstance(result, SimulationResult)


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
                backend="com",
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
                str(tmp_project), jobs, parallel=False, cleanup=True, backend="com", log=_nolog
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

        mock_result = SimulationResult(
            plan_name="plan01", plan_suffix="01", success=True, elapsed_seconds=1.0
        )

        with (
            patch("hecras_runner.runner.Process") as mock_process_cls,
            patch("hecras_runner.runner.Queue") as mock_queue_cls,
        ):
            mock_proc = MagicMock()
            mock_process_cls.return_value = mock_proc
            mock_q = MagicMock()
            mock_q.get.return_value = mock_result
            mock_queue_cls.return_value = mock_q

            run_simulations(
                str(tmp_project),
                jobs,
                parallel=True,
                cleanup=True,
                backend="com",
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
                backend="com",
                log=_nolog,
            )

            temp_prj = mock_run.call_args[0][0]
            import os

            # Temp dir should still exist
            assert os.path.exists(os.path.dirname(temp_prj))

            # Clean up manually
            import shutil

            shutil.rmtree(os.path.dirname(temp_prj))

    def test_cli_backend_dispatch(self, tmp_project: Path):
        """Verify backend='cli' dispatches to run_hecras_cli."""
        jobs = [SimulationJob(plan_name="plan01", plan_suffix="01")]

        mock_result = SimulationResult(
            plan_name="plan01", plan_suffix="01", success=True, elapsed_seconds=5.0
        )
        with (
            patch("hecras_runner.runner.run_hecras_cli") as mock_cli,
            patch("hecras_runner.runner.find_hecras_exe", return_value=r"C:\HEC\Ras.exe"),
        ):
            mock_cli.return_value = mock_result
            results = run_simulations(
                str(tmp_project),
                jobs,
                parallel=False,
                cleanup=True,
                backend="cli",
                log=_nolog,
            )

        mock_cli.assert_called_once()
        assert len(results) == 1
        assert results[0].success is True

    def test_default_backend_is_cli(self, tmp_project: Path):
        """Verify default backend is 'cli'."""
        jobs = [SimulationJob(plan_name="plan01", plan_suffix="01")]

        mock_result = SimulationResult(
            plan_name="plan01", plan_suffix="01", success=True, elapsed_seconds=5.0
        )
        with (
            patch("hecras_runner.runner.run_hecras_cli") as mock_cli,
            patch("hecras_runner.runner.find_hecras_exe", return_value=r"C:\HEC\Ras.exe"),
        ):
            mock_cli.return_value = mock_result
            run_simulations(
                str(tmp_project),
                jobs,
                parallel=False,
                cleanup=True,
                log=_nolog,
            )

        # Should have called CLI runner, not COM runner
        mock_cli.assert_called_once()
