"""Tests for hecras_runner.cli."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hecras_runner.cli import build_parser, main


class TestBuildParser:
    def test_required_project_arg(self):
        parser = build_parser()
        args = parser.parse_args(["project.prj", "--all"])
        assert args.project == "project.prj"
        assert args.run_all is True

    def test_plans_arg(self):
        parser = build_parser()
        args = parser.parse_args(["project.prj", "--plans", "plan01", "plan03"])
        assert args.plans == ["plan01", "plan03"]

    def test_list_arg(self):
        parser = build_parser()
        args = parser.parse_args(["project.prj", "--list"])
        assert args.list_plans is True

    def test_sequential_and_no_cleanup(self):
        parser = build_parser()
        args = parser.parse_args(["project.prj", "--all", "--sequential", "--no-cleanup"])
        assert args.sequential is True
        assert args.no_cleanup is True

    def test_dss_override(self):
        parser = build_parser()
        args = parser.parse_args(["project.prj", "--all", "--dss", r"C:\path\file.dss"])
        assert args.dss == r"C:\path\file.dss"


class TestMainListMode:
    def test_list_plans(self, prtest1_prj: Path, capsys):
        result = main([str(prtest1_prj), "--list"])
        assert result == 0
        output = capsys.readouterr().out
        assert "PRtest1" in output
        assert "plan01" in output
        assert "plan02" in output
        assert "plan03" in output
        assert "plan04" in output
        assert "(current)" in output

    def test_list_synthetic(self, synthetic_prj: Path, capsys):
        result = main([str(synthetic_prj), "--list"])
        assert result == 0
        output = capsys.readouterr().out
        assert "Minimal" in output
        assert "Test Plan" in output


class TestMainErrors:
    def test_missing_file(self, capsys):
        result = main([r"C:\nonexistent\project.prj", "--list"])
        assert result == 1

    def test_plan_not_found(self, prtest1_prj: Path, capsys):
        result = main([str(prtest1_prj), "--plans", "nonexistent_plan"])
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err

    @patch("hecras_runner.cli.check_hecras_installed", return_value=False)
    def test_hecras_not_installed(self, _mock, prtest1_prj: Path, capsys):
        result = main([str(prtest1_prj), "--all"])
        assert result == 1
        err = capsys.readouterr().err
        assert "not installed" in err


class TestMainRunMode:
    @patch("hecras_runner.cli.run_simulations")
    @patch("hecras_runner.cli.check_hecras_installed", return_value=True)
    def test_all_plans(self, _mock_check, mock_run, prtest1_prj: Path):
        result = main([str(prtest1_prj), "--all"])
        assert result == 0
        mock_run.assert_called_once()
        kwargs = mock_run.call_args[1]
        assert len(kwargs["jobs"]) == 4
        assert kwargs["parallel"] is True
        assert kwargs["cleanup"] is True

    @patch("hecras_runner.cli.run_simulations")
    @patch("hecras_runner.cli.check_hecras_installed", return_value=True)
    def test_selected_plans(self, _mock_check, mock_run, prtest1_prj: Path):
        result = main([str(prtest1_prj), "--plans", "plan01", "plan03"])
        assert result == 0
        jobs = mock_run.call_args[1]["jobs"]
        assert len(jobs) == 2
        assert jobs[0].plan_name == "plan01"
        assert jobs[0].plan_suffix == "01"
        assert jobs[1].plan_name == "plan03"
        assert jobs[1].plan_suffix == "03"

    @patch("hecras_runner.cli.run_simulations")
    @patch("hecras_runner.cli.check_hecras_installed", return_value=True)
    def test_sequential_mode(self, _mock_check, mock_run, prtest1_prj: Path):
        result = main([str(prtest1_prj), "--all", "--sequential"])
        assert result == 0
        assert mock_run.call_args[1]["parallel"] is False

    @patch("hecras_runner.cli.run_simulations")
    @patch("hecras_runner.cli.check_hecras_installed", return_value=True)
    def test_dss_override(self, _mock_check, mock_run, prtest1_prj: Path):
        result = main([str(prtest1_prj), "--all", "--dss", r"C:\new\file.dss"])
        assert result == 0
        jobs = mock_run.call_args[1]["jobs"]
        assert all(j.dss_path == r"C:\new\file.dss" for j in jobs)
