"""Tests for hecras_runner.file_ops."""

from __future__ import annotations

import os
from pathlib import Path

from hecras_runner.file_ops import (
    _fix_dss_paths_for_temp,
    cleanup_temp_dir,
    copy_project_to_temp,
    copy_results_back,
    update_dss_paths,
)


def _nolog(msg: str) -> None:
    """Suppress log output in tests."""


class TestCopyProjectToTemp:
    def test_creates_temp_dir(self, tmp_project: Path):
        temp_prj = copy_project_to_temp(str(tmp_project), log=_nolog)
        try:
            assert os.path.isfile(temp_prj)
            assert os.path.basename(temp_prj) == "minimal.prj"
            # Verify other files are copied
            temp_dir = os.path.dirname(temp_prj)
            assert os.path.isfile(os.path.join(temp_dir, "minimal.p01"))
            assert os.path.isfile(os.path.join(temp_dir, "minimal.g01"))
            assert os.path.isfile(os.path.join(temp_dir, "minimal.u01"))
        finally:
            cleanup_temp_dir(os.path.dirname(temp_prj), log=_nolog)

    def test_patches_dss_when_provided(self, tmp_project: Path):
        temp_prj = copy_project_to_temp(str(tmp_project), dss_path=r"C:\new\path.dss", log=_nolog)
        try:
            temp_dir = os.path.dirname(temp_prj)
            u_file = os.path.join(temp_dir, "minimal.u01")
            content = Path(u_file).read_text()
            assert r"C:\new\path.dss" in content
            assert "test.dss" not in content
        finally:
            cleanup_temp_dir(os.path.dirname(temp_prj), log=_nolog)

    def test_relative_dss_preserved_when_no_override(self, tmp_project: Path):
        temp_prj = copy_project_to_temp(str(tmp_project), dss_path=None, log=_nolog)
        try:
            temp_dir = os.path.dirname(temp_prj)
            u_file = os.path.join(temp_dir, "minimal.u01")
            content = Path(u_file).read_text()
            assert "DSS File=test.dss" in content  # relative path unchanged
        finally:
            cleanup_temp_dir(os.path.dirname(temp_prj), log=_nolog)

    def test_absolute_dss_fixed_when_file_in_temp(self, tmp_path: Path):
        """Absolute DSS paths are rewritten to relative when the file exists."""
        # Set up a project dir with a .u file containing an absolute DSS path
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        (proj_dir / "test.prj").write_text("Proj Title=Test\n")
        (proj_dir / "test.u01").write_text(
            "Flow Title=flow\nDSS File=C:\\OldMachine\\data\\input.dss\n"
        )
        (proj_dir / "input.dss").write_bytes(b"fake dss")  # file IS in the dir

        temp_prj = copy_project_to_temp(str(proj_dir / "test.prj"), dss_path=None, log=_nolog)
        try:
            temp_dir = os.path.dirname(temp_prj)
            content = (Path(temp_dir) / "test.u01").read_text()
            assert "DSS File=input.dss" in content  # rewritten to relative
            assert "OldMachine" not in content
        finally:
            cleanup_temp_dir(os.path.dirname(temp_prj), log=_nolog)

    def test_absolute_dss_kept_when_file_not_in_temp(self, tmp_path: Path):
        """Absolute DSS paths to external files are left unchanged."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        (proj_dir / "test.prj").write_text("Proj Title=Test\n")
        (proj_dir / "test.u01").write_text(
            "Flow Title=flow\nDSS File=C:\\External\\server\\remote.dss\n"
        )
        # remote.dss is NOT in the project dir

        temp_prj = copy_project_to_temp(str(proj_dir / "test.prj"), dss_path=None, log=_nolog)
        try:
            temp_dir = os.path.dirname(temp_prj)
            content = (Path(temp_dir) / "test.u01").read_text()
            assert r"DSS File=C:\External\server\remote.dss" in content  # unchanged
        finally:
            cleanup_temp_dir(os.path.dirname(temp_prj), log=_nolog)


class TestUpdateDssPaths:
    def test_updates_u_files(self, tmp_path: Path):
        (tmp_path / "test.u01").write_text("DSS File=old.dss\nOther line\n")
        (tmp_path / "test.u02").write_text("DSS File=old.dss\nDSS File=another.dss\n")
        (tmp_path / "test.p01").write_text("DSS File=old.dss\n")  # should NOT be touched

        count = update_dss_paths(str(tmp_path), r"C:\new\path.dss", log=_nolog)
        assert count == 2

        u01 = (tmp_path / "test.u01").read_text()
        assert r"DSS File=C:\new\path.dss" in u01
        assert "old.dss" not in u01

        u02 = (tmp_path / "test.u02").read_text()
        assert u02.count(r"C:\new\path.dss") == 2

        # p01 should be untouched
        p01 = (tmp_path / "test.p01").read_text()
        assert "old.dss" in p01

    def test_no_u_files(self, tmp_path: Path):
        (tmp_path / "test.p01").write_text("DSS File=old.dss\n")
        count = update_dss_paths(str(tmp_path), "new.dss", log=_nolog)
        assert count == 0

    def test_regex_matches_any_two_digit_suffix(self, tmp_path: Path):
        (tmp_path / "project.u15").write_text("DSS File=old.dss\n")
        count = update_dss_paths(str(tmp_path), "new.dss", log=_nolog)
        assert count == 1


class TestFixDssPathsForTemp:
    def test_rewrites_absolute_to_relative(self, tmp_path: Path):
        (tmp_path / "input.dss").write_bytes(b"fake")
        (tmp_path / "test.u01").write_text("DSS File=C:\\Old\\path\\input.dss\nOther line\n")
        count = _fix_dss_paths_for_temp(str(tmp_path), log=_nolog)
        assert count == 1
        content = (tmp_path / "test.u01").read_text()
        assert "DSS File=input.dss\n" in content
        assert "Other line" in content

    def test_leaves_relative_paths_alone(self, tmp_path: Path):
        (tmp_path / "test.u01").write_text("DSS File=local.dss\n")
        count = _fix_dss_paths_for_temp(str(tmp_path), log=_nolog)
        assert count == 0
        assert (tmp_path / "test.u01").read_text() == "DSS File=local.dss\n"

    def test_leaves_external_absolute_paths(self, tmp_path: Path):
        # no matching file in directory
        (tmp_path / "test.u01").write_text("DSS File=C:\\External\\nowhere.dss\n")
        count = _fix_dss_paths_for_temp(str(tmp_path), log=_nolog)
        assert count == 0

    def test_mixed_paths_in_one_file(self, tmp_path: Path):
        (tmp_path / "input.dss").write_bytes(b"fake")
        (tmp_path / "test.u01").write_text("DSS File=C:\\Old\\input.dss\nDSS File=relative.dss\n")
        count = _fix_dss_paths_for_temp(str(tmp_path), log=_nolog)
        assert count == 1
        content = (tmp_path / "test.u01").read_text()
        assert "DSS File=input.dss\n" in content
        assert "DSS File=relative.dss\n" in content

    def test_case_insensitive_match(self, tmp_path: Path):
        (tmp_path / "Input.DSS").write_bytes(b"fake")
        (tmp_path / "test.u01").write_text("DSS File=C:\\Old\\input.dss\n")
        count = _fix_dss_paths_for_temp(str(tmp_path), log=_nolog)
        assert count == 1


class TestCopyResultsBack:
    def test_copies_matching_files(self, tmp_path: Path):
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        main_dir = tmp_path / "main"
        main_dir.mkdir()

        # Create result files
        (temp_dir / "project.p03").write_text("plan result")
        (temp_dir / "project.p03.hdf").write_text("plan hdf")
        (temp_dir / "project.u03").write_text("flow result")
        (temp_dir / "project.b03").write_text("boundary result")
        (temp_dir / "project.x03").write_text("xs result")
        (temp_dir / "project.bco03").write_text("bco result")
        (temp_dir / "project.ic.o03").write_text("ic result")
        (temp_dir / "project.g03.hdf").write_text("geom hdf")
        # Non-matching files
        (temp_dir / "project.prj").write_text("prj")
        (temp_dir / "project.p01").write_text("wrong suffix")

        copied = copy_results_back(str(temp_dir / "project.prj"), str(main_dir), "03", log=_nolog)

        assert "project.p03" in copied
        assert "project.p03.hdf" in copied
        assert "project.u03" in copied
        assert "project.b03" in copied
        assert "project.x03" in copied
        assert "project.bco03" in copied
        assert "project.ic.o03" in copied
        assert "project.g03.hdf" in copied
        assert "project.prj" not in copied
        assert "project.p01" not in copied
        assert len(copied) == 8

    def test_empty_temp_dir(self, tmp_path: Path):
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        copied = copy_results_back(str(temp_dir), str(main_dir), "01", log=_nolog)
        assert copied == []


class TestCleanupTempDir:
    def test_removes_directory(self, tmp_path: Path):
        temp_dir = tmp_path / "to_remove"
        temp_dir.mkdir()
        (temp_dir / "file.txt").write_text("content")
        cleanup_temp_dir(str(temp_dir), log=_nolog)
        assert not temp_dir.exists()

    def test_nonexistent_dir_logs_error(self, tmp_path: Path):
        messages: list[str] = []
        cleanup_temp_dir(str(tmp_path / "nonexistent"), log=messages.append)
        assert any("Error" in m for m in messages)
