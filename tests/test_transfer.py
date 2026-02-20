"""Tests for hecras_runner.transfer (all use tmp_path — no actual SMB)."""

from __future__ import annotations

import json
from pathlib import Path

from hecras_runner.transfer import (
    _is_result_file,
    cleanup_share_job,
    compute_terrain_hash,
    project_to_share,
    results_from_share,
    results_to_share,
    share_to_local,
    verify_transfer,
)


def _nolog(msg: str) -> None:
    pass


def _make_project(tmp_path: Path, name: str = "test_project") -> Path:
    """Create a minimal HEC-RAS project in tmp_path and return .prj path."""
    prj = tmp_path / f"{name}.prj"
    prj.write_text("Proj Title=Test\nCurrent Plan=p01\nPlan File=p01\n")
    plan = tmp_path / f"{name}.p01"
    plan.write_text("Plan Title=plan01\nGeom File=g01\nFlow File=u01\n")
    geom = tmp_path / f"{name}.g01"
    geom.write_text("Geom Title=geom01\n")
    flow = tmp_path / f"{name}.u01"
    flow.write_text("Flow Title=flow01\nDSS File=input.dss\n")
    dss = tmp_path / "input.dss"
    dss.write_bytes(b"\x00" * 100)
    # Terrain directory
    terrain = tmp_path / "Terrain"
    terrain.mkdir()
    (terrain / "source.tif").write_bytes(b"\x01" * 500)
    return prj


class TestProjectToShare:
    def test_copies_files_and_creates_manifest(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        prj = _make_project(project_dir, "myproject")

        share = tmp_path / "share"
        share.mkdir()

        manifest = project_to_share(
            str(prj), str(share), "job-001", "01", log=_nolog
        )

        assert manifest.job_id == "job-001"
        assert manifest.plan_suffix == "01"
        assert (Path(manifest.share_project_dir) / "myproject.prj").exists()
        assert (Path(manifest.share_project_dir) / "manifest.json").exists()
        assert Path(manifest.share_results_dir).is_dir()
        assert len(manifest.files) > 0

        # Verify manifest JSON
        manifest_data = json.loads(
            (Path(manifest.share_project_dir) / "manifest.json").read_text()
        )
        assert manifest_data["job_id"] == "job-001"

    def test_copies_terrain_directory(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        prj = _make_project(project_dir)
        share = tmp_path / "share"

        manifest = project_to_share(str(prj), str(share), "job-002", "01", log=_nolog)
        assert "Terrain/" in manifest.files
        assert (Path(manifest.share_project_dir) / "Terrain" / "source.tif").exists()


class TestShareToLocal:
    def test_downloads_project(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        prj = _make_project(project_dir, "myproject")
        share = tmp_path / "share"

        manifest = project_to_share(str(prj), str(share), "job-001", "01", log=_nolog)

        local = tmp_path / "local"
        local_prj = share_to_local(manifest, str(local), log=_nolog)

        assert local_prj.endswith("myproject.prj")
        assert (local / "myproject.prj").exists()
        assert (local / "myproject.p01").exists()
        assert (local / "Terrain" / "source.tif").exists()


class TestResultsToShare:
    def test_copies_result_files(self, tmp_path: Path):
        local = tmp_path / "local"
        local.mkdir()
        (local / "test.p01").write_text("plan data")
        (local / "test.p01.hdf").write_bytes(b"\x00" * 100)
        (local / "test.bco01").write_text("bco data")
        (local / "test.g01").write_text("geom data")
        (local / "test.prj").write_text("project")  # should NOT be copied

        results_dir = tmp_path / "results"
        copied = results_to_share(
            str(local / "test.prj"), str(results_dir), "01", log=_nolog
        )

        assert "test.p01" in copied
        assert "test.p01.hdf" in copied
        assert "test.bco01" in copied
        assert "test.g01" in copied
        assert "test.prj" not in copied


class TestResultsFromShare:
    def test_copies_back_to_main(self, tmp_path: Path):
        share_results = tmp_path / "share_results"
        share_results.mkdir()
        (share_results / "test.p02.hdf").write_bytes(b"\x00" * 50)
        (share_results / "test.p02").write_text("plan")

        main = tmp_path / "main"
        main.mkdir()

        copied = results_from_share(str(share_results), str(main), "02", log=_nolog)

        assert "test.p02.hdf" in copied
        assert "test.p02" in copied
        assert (main / "test.p02.hdf").exists()

    def test_missing_directory(self, tmp_path: Path):
        copied = results_from_share(
            str(tmp_path / "nonexistent"), str(tmp_path), "01", log=_nolog
        )
        assert copied == []


class TestIsResultFile:
    def test_plan_file(self):
        assert _is_result_file("test.p01", "01") is True

    def test_hdf_file(self):
        assert _is_result_file("test.p01.hdf", "01") is True

    def test_bco_file(self):
        assert _is_result_file("test.bco01", "01") is True

    def test_non_result_file(self):
        assert _is_result_file("test.prj", "01") is False
        assert _is_result_file("test.rasmap", "01") is False

    def test_wrong_suffix(self):
        assert _is_result_file("test.p02", "01") is False
        assert _is_result_file("test.p01", "02") is False


class TestVerifyTransfer:
    def test_matching_sizes(self, tmp_path: Path):
        src = tmp_path / "src.bin"
        dst = tmp_path / "dst.bin"
        data = b"\x00" * 1000
        src.write_bytes(data)
        dst.write_bytes(data)
        assert verify_transfer(str(src), str(dst), log=_nolog) is True

    def test_mismatched_sizes(self, tmp_path: Path):
        src = tmp_path / "src.bin"
        dst = tmp_path / "dst.bin"
        src.write_bytes(b"\x00" * 1000)
        dst.write_bytes(b"\x00" * 500)
        assert verify_transfer(str(src), str(dst), log=_nolog) is False

    def test_missing_file(self, tmp_path: Path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"\x00" * 100)
        assert verify_transfer(str(src), str(tmp_path / "missing"), log=_nolog) is False


class TestComputeTerrainHash:
    def test_returns_hash_for_terrain_dir(self, tmp_path: Path):
        terrain = tmp_path / "Terrain"
        terrain.mkdir()
        (terrain / "source.tif").write_bytes(b"\x01" * 500)
        (terrain / "source.tif.aux.xml").write_text("<aux/>")

        h = compute_terrain_hash(str(tmp_path))
        assert len(h) == 24
        assert h.isalnum()

    def test_returns_empty_without_terrain(self, tmp_path: Path):
        assert compute_terrain_hash(str(tmp_path)) == ""

    def test_different_content_different_hash(self, tmp_path: Path):
        terrain = tmp_path / "Terrain"
        terrain.mkdir()
        (terrain / "source.tif").write_bytes(b"\x01" * 500)
        h1 = compute_terrain_hash(str(tmp_path))

        (terrain / "source.tif").write_bytes(b"\x02" * 500)
        h2 = compute_terrain_hash(str(tmp_path))

        assert h1 != h2


class TestCleanupShareJob:
    def test_removes_job_directories(self, tmp_path: Path):
        share = tmp_path / "share"
        proj = share / "projects" / "job-001"
        results = share / "results" / "job-001"
        proj.mkdir(parents=True)
        results.mkdir(parents=True)
        (proj / "test.prj").write_text("data")
        (results / "test.p01.hdf").write_bytes(b"\x00")

        cleanup_share_job(str(share), "job-001", log=_nolog)

        assert not proj.exists()
        assert not results.exists()

    def test_handles_missing_directories(self, tmp_path: Path):
        # Should not raise
        cleanup_share_job(str(tmp_path), "nonexistent", log=_nolog)
