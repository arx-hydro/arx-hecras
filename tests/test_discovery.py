"""Tests for hecras_runner.discovery (HEC-RAS discovery functions)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hecras_runner.discovery import (
    check_hecras_installed,
    find_hecras_exe,
    find_hecras_processes,
    open_parent_instance,
    refresh_parent_instance,
)


def _nolog(msg: str) -> None:
    pass


class TestCheckHecrasInstalled:
    def test_com_returns_true_when_available(self):
        mock_pycom = MagicMock()
        mock_w32_client = MagicMock()

        modules = {"pythoncom": mock_pycom, "win32com.client": mock_w32_client}
        with patch("hecras_runner.discovery.importlib.import_module") as mock_import:
            mock_import.side_effect = lambda name: modules[name]
            result = check_hecras_installed(backend="com", log=_nolog)
        assert result is True

    def test_com_returns_false_when_not_available(self):
        with patch(
            "hecras_runner.discovery.importlib.import_module",
            side_effect=ImportError("no pywin32"),
        ):
            result = check_hecras_installed(backend="com", log=_nolog)
        assert result is False

    def test_cli_returns_true_when_exe_found(self):
        with patch("hecras_runner.discovery.find_hecras_exe", return_value=r"C:\HEC\Ras.exe"):
            result = check_hecras_installed(backend="cli", log=_nolog)
        assert result is True

    def test_cli_returns_false_when_exe_not_found(self):
        with patch("hecras_runner.discovery.find_hecras_exe", return_value=None):
            result = check_hecras_installed(backend="cli", log=_nolog)
        assert result is False

    def test_default_backend_is_cli(self):
        with patch("hecras_runner.discovery.find_hecras_exe", return_value=r"C:\HEC\Ras.exe"):
            result = check_hecras_installed(log=_nolog)
        assert result is True


class TestFindHecrasExe:
    def test_registry_found(self):
        """find_hecras_exe returns path from registry when available."""
        mock_winreg = MagicMock()
        mock_reg_key = MagicMock()
        mock_ver_key = MagicMock()

        mock_winreg.OpenKey.side_effect = [mock_reg_key, mock_ver_key]
        mock_winreg.EnumKey.side_effect = ["6.6", OSError()]
        mock_winreg.QueryValueEx.return_value = (r"C:\Program Files\HEC\HEC-RAS\6.6", 1)
        mock_winreg.HKEY_LOCAL_MACHINE = 0x80000002

        with (
            patch.dict("sys.modules", {"winreg": mock_winreg}),
            patch("hecras_runner.discovery.os.path.isfile", return_value=True),
        ):
            result = find_hecras_exe(log=_nolog)
        assert result == r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe"

    def test_path_fallback(self):
        """find_hecras_exe falls back to shutil.which."""
        # Make registry fail, but shutil.which succeeds
        with (
            patch("hecras_runner.discovery.shutil.which", return_value=r"C:\HEC\Ras.exe"),
        ):
            # Force registry to fail by making winreg import fail
            import sys

            saved = sys.modules.get("winreg")
            sys.modules["winreg"] = None  # type: ignore[assignment]
            try:
                result = find_hecras_exe(log=_nolog)
            finally:
                if saved is not None:
                    sys.modules["winreg"] = saved
                else:
                    sys.modules.pop("winreg", None)
        assert result == r"C:\HEC\Ras.exe"

    def test_common_path_fallback(self):
        """find_hecras_exe checks common install paths."""
        with (
            patch("hecras_runner.discovery.shutil.which", return_value=None),
            patch(
                "hecras_runner.discovery.os.path.isfile",
                side_effect=lambda p: p == r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe",
            ),
        ):
            import sys

            saved = sys.modules.get("winreg")
            sys.modules["winreg"] = None  # type: ignore[assignment]
            try:
                result = find_hecras_exe(log=_nolog)
            finally:
                if saved is not None:
                    sys.modules["winreg"] = saved
                else:
                    sys.modules.pop("winreg", None)
        assert result == r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe"

    def test_not_found(self):
        """find_hecras_exe returns None when nothing found."""
        with (
            patch("hecras_runner.discovery.shutil.which", return_value=None),
            patch("hecras_runner.discovery.os.path.isfile", return_value=False),
        ):
            import sys

            saved = sys.modules.get("winreg")
            sys.modules["winreg"] = None  # type: ignore[assignment]
            try:
                result = find_hecras_exe(log=_nolog)
            finally:
                if saved is not None:
                    sys.modules["winreg"] = saved
                else:
                    sys.modules.pop("winreg", None)
        assert result is None


class TestFindHecrasProcesses:
    def test_returns_pids(self):
        fake_output = '"Ras.exe","1234","Console","1","50,000 K"\n'
        with patch("hecras_runner.discovery.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=fake_output)
            pids = find_hecras_processes()
        assert pids == [1234]

    def test_returns_empty_on_no_match(self):
        with patch("hecras_runner.discovery.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="INFO: No tasks are running...\n")
            pids = find_hecras_processes()
        assert pids == []

    def test_returns_empty_on_error(self):
        with patch(
            "hecras_runner.discovery.subprocess.run",
            side_effect=OSError("not found"),
        ):
            pids = find_hecras_processes()
        assert pids == []


class TestParentInstance:
    def test_open_parent_instance(self):
        mock_w32_client = MagicMock()
        mock_ras = MagicMock()
        mock_w32_client.Dispatch.return_value = mock_ras

        with patch("hecras_runner.discovery.importlib.import_module") as mock_import:
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
