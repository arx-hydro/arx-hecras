"""Tests for hecras_runner.db (all mocked — no real DB needed)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hecras_runner.db import (
    _CURRENT_SCHEMA_VERSION as _SCHEMA_VERSION,
)
from hecras_runner.db import (
    DbClient,
    WorkerInfo,
)
from hecras_runner.settings import DbSettings


def _nolog(msg: str) -> None:
    pass


def _make_mock_pool():
    """Create a mock connection pool with mock connection/cursor."""
    pool = MagicMock()
    conn = MagicMock()
    # Make pool.connection() work as context manager
    pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connection.return_value.__exit__ = MagicMock(return_value=False)
    return pool, conn


class TestDbClientConnect:
    def test_returns_none_when_psycopg_missing(self):
        with patch(
            "hecras_runner.db.DbClient.__init__",
            side_effect=ImportError("no psycopg"),
        ):
            # Import error happens inside connect when trying to import psycopg_pool
            settings = DbSettings(host="localhost")
            result = DbClient.connect(settings, log=_nolog)
        # Since psycopg_pool is not installed in test env, this should return None
        assert result is None

    def test_returns_none_on_connection_error(self):
        mock_pool_cls = MagicMock(side_effect=Exception("Connection refused"))
        with patch.dict("sys.modules", {"psycopg_pool": MagicMock(ConnectionPool=mock_pool_cls)}):
            settings = DbSettings(host="badhost")
            result = DbClient.connect(settings, log=_nolog)
        assert result is None


class TestDbClientWorker:
    def test_register_worker(self):
        pool, conn = _make_mock_pool()
        conn.execute.return_value.fetchone.return_value = ("worker-uuid-123",)
        client = DbClient(pool, log=_nolog)

        with (
            patch("hecras_runner.db.socket.gethostname", return_value="PC-01"),
            patch("hecras_runner.db.socket.gethostbyname", return_value="192.168.1.1"),
            patch("hecras_runner.db.platform.platform", return_value="Windows-11"),
        ):
            info = client.register_worker(hecras_version="6.6", max_concurrent=2)

        assert isinstance(info, WorkerInfo)
        assert info.worker_id == "worker-uuid-123"
        assert info.hostname == "PC-01"
        assert info.ip_address == "192.168.1.1"

    def test_heartbeat(self):
        pool, conn = _make_mock_pool()
        client = DbClient(pool, log=_nolog)

        client.heartbeat("worker-123")

        conn.execute.assert_called()
        sql = conn.execute.call_args[0][0]
        assert "UPDATE" in sql
        assert "last_heartbeat" in sql

    def test_set_worker_offline(self):
        pool, conn = _make_mock_pool()
        client = DbClient(pool, log=_nolog)

        client.set_worker_offline("worker-123")

        conn.execute.assert_called()
        sql = conn.execute.call_args[0][0]
        assert "offline" in sql


class TestDbClientBatch:
    def test_submit_batch(self):
        pool, conn = _make_mock_pool()
        conn.execute.return_value.fetchone.return_value = ("batch-uuid-456",)
        client = DbClient(pool, log=_nolog)

        jobs = [
            {"plan_name": "plan01", "plan_suffix": "01"},
            {"plan_name": "plan02", "plan_suffix": "02"},
        ]
        batch_id = client.submit_batch(
            project_path=r"C:\project\test.prj",
            project_title="Test Project",
            jobs=jobs,
            submitted_by="user@host",
        )

        assert batch_id == "batch-uuid-456"
        # Should have called execute for batch INSERT + 2 job INSERTs + commit
        assert conn.execute.call_count >= 3

    def test_get_batch_status(self):
        pool, conn = _make_mock_pool()

        # First call: batch row
        # Second call: job counts
        conn.execute.return_value.fetchone.side_effect = [
            ("running", 3),
            None,
        ]
        conn.execute.return_value.fetchall.return_value = [
            ("completed", 1),
            ("running", 1),
            ("queued", 1),
        ]
        client = DbClient(pool, log=_nolog)

        status = client.get_batch_status("batch-123")

        assert status["status"] == "running"
        assert status["total"] == 3

    def test_get_batch_status_not_found(self):
        pool, conn = _make_mock_pool()
        conn.execute.return_value.fetchone.return_value = None
        client = DbClient(pool, log=_nolog)

        status = client.get_batch_status("nonexistent")
        assert status["status"] == "not_found"


class TestDbClientJob:
    def test_claim_job(self):
        pool, conn = _make_mock_pool()
        # claim_job calls execute twice (UPDATE returning, then SELECT project_path)
        conn.execute.return_value.fetchone.side_effect = [
            ("job-uuid-789", "batch-uuid-456", "plan01", "01"),
            (r"C:\project\test.prj",),
        ]
        client = DbClient(pool, log=_nolog)

        job = client.claim_job("worker-123")

        assert job is not None
        assert job["job_id"] == "job-uuid-789"
        assert job["plan_name"] == "plan01"
        assert job["plan_suffix"] == "01"
        assert job["project_path"] == r"C:\project\test.prj"

    def test_claim_job_returns_none_when_empty(self):
        pool, conn = _make_mock_pool()
        conn.execute.return_value.fetchone.return_value = None
        client = DbClient(pool, log=_nolog)

        job = client.claim_job("worker-123")
        assert job is None

    def test_start_job(self):
        pool, conn = _make_mock_pool()
        client = DbClient(pool, log=_nolog)

        client.start_job("job-123")

        # Should update job status + batch status
        assert conn.execute.call_count >= 2

    def test_complete_job_success(self):
        pool, conn = _make_mock_pool()
        # For complete_job: UPDATE job, SELECT batch_id, SELECT remaining count
        conn.execute.return_value.fetchone.side_effect = [
            None,  # UPDATE result
            ("batch-123",),  # batch_id
            (0,),  # remaining count (all done)
            (0,),  # failed count
            None,  # UPDATE batch
        ]
        client = DbClient(pool, log=_nolog)

        client.complete_job(
            "job-123",
            success=True,
            elapsed_seconds=5.3,
            hdf_verified=True,
        )

        conn.execute.assert_called()
        conn.commit.assert_called()

    def test_update_progress(self):
        pool, conn = _make_mock_pool()
        client = DbClient(pool, log=_nolog)

        client.update_progress("job-123", 0.75)

        conn.execute.assert_called()
        args = conn.execute.call_args[0]
        assert "progress" in args[0]


class TestDbClientQueries:
    def test_get_active_workers(self):
        pool, conn = _make_mock_pool()
        conn.execute.return_value.fetchall.return_value = [
            ("id1", "PC-01", "192.168.1.1", "idle", "6.6", 2, None),
            ("id2", "PC-02", "192.168.1.2", "busy", "6.6", 1, None),
        ]
        client = DbClient(pool, log=_nolog)

        workers = client.get_active_workers()

        assert len(workers) == 2
        assert workers[0]["hostname"] == "PC-01"
        assert workers[1]["status"] == "busy"

    def test_get_batch_jobs(self):
        pool, conn = _make_mock_pool()
        conn.execute.return_value.fetchall.return_value = [
            ("j1", "plan01", "01", "completed", "w1", 5.0, None, 1.0),
            ("j2", "plan02", "02", "running", "w2", None, None, 0.5),
        ]
        client = DbClient(pool, log=_nolog)

        jobs = client.get_batch_jobs("batch-123")

        assert len(jobs) == 2
        assert jobs[0]["plan_name"] == "plan01"
        assert jobs[0]["progress"] == 1.0
        assert jobs[1]["status"] == "running"


class TestDbClientMigrate:
    def test_migrate_acquires_advisory_lock(self):
        pool, conn = _make_mock_pool()
        # Schema version query returns current version (no migration needed)
        conn.execute.return_value.fetchone.return_value = (_SCHEMA_VERSION,)
        client = DbClient(pool, log=_nolog)

        client.migrate()

        # Should have called pg_advisory_lock and pg_advisory_unlock
        all_sql = [c[0][0] for c in conn.execute.call_args_list if c[0]]
        assert any("advisory_lock" in sql for sql in all_sql)
        assert any("advisory_unlock" in sql for sql in all_sql)


class TestDbClientClose:
    def test_close(self):
        pool, _ = _make_mock_pool()
        client = DbClient(pool, log=_nolog)
        client.close()
        pool.close.assert_called_once()
