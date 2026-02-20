"""PostgreSQL job queue client for distributed HEC-RAS execution.

Optional dependency: ``psycopg[binary]`` + ``psycopg_pool``.
If psycopg is not installed, ``DbClient.connect()`` returns None gracefully.
"""

from __future__ import annotations

import contextlib
import platform
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass

from hecras_runner.settings import DbSettings

# Schema version managed by this code
_CURRENT_SCHEMA_VERSION = 1

_SCHEMA = "hecras_runner"


@dataclass
class WorkerInfo:
    """Registration info returned after worker registers."""

    worker_id: str
    hostname: str
    ip_address: str


class DbClient:
    """PostgreSQL client for the hecras_runner distributed job queue.

    Use the ``connect()`` classmethod to create an instance. Returns None
    if psycopg is not installed or the database is unreachable.
    """

    def __init__(self, pool: object, log: Callable[[str], None] = print) -> None:
        self._pool = pool
        self._log = log
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    @classmethod
    def connect(
        cls,
        settings: DbSettings,
        log: Callable[[str], None] = print,
    ) -> DbClient | None:
        """Create a DbClient with a connection pool. Returns None on failure."""
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:
            log("psycopg not installed — database features unavailable")
            return None

        conninfo = (
            f"host={settings.host} port={settings.port} "
            f"dbname={settings.dbname} user={settings.user} "
            f"password={settings.password}"
        )

        try:
            pool = ConnectionPool(
                conninfo=conninfo,
                min_size=1,
                max_size=3,
                open=True,
            )
            # Quick connectivity check
            with pool.connection() as conn:
                conn.execute("SELECT 1")
            log(f"Connected to {settings.host}:{settings.port}/{settings.dbname}")
            return cls(pool, log=log)
        except Exception as e:
            log(f"Database connection failed: {e}")
            return None

    def close(self) -> None:
        """Close the connection pool and stop heartbeat."""
        self.stop_heartbeat()
        with contextlib.suppress(Exception):
            self._pool.close()  # type: ignore[attr-defined]

    # ── Schema migration ──

    def migrate(self) -> None:
        """Run forward-only schema migrations under an advisory lock."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            # Advisory lock to prevent concurrent migrations
            conn.execute("SELECT pg_advisory_lock(42)")
            try:
                current = self._get_schema_version(conn)
                if current < _CURRENT_SCHEMA_VERSION:
                    self._log(
                        f"Migrating schema from v{current} to v{_CURRENT_SCHEMA_VERSION}"
                    )
                    self._apply_migrations(conn, current)
                    conn.commit()
            finally:
                conn.execute("SELECT pg_advisory_unlock(42)")

    def _get_schema_version(self, conn: object) -> int:
        """Get current schema version, 0 if table doesn't exist."""
        try:
            row = conn.execute(  # type: ignore[attr-defined]
                f"SELECT MAX(version) FROM {_SCHEMA}.schema_version"
            ).fetchone()
            return row[0] if row and row[0] is not None else 0
        except Exception:
            conn.rollback()  # type: ignore[attr-defined]
            return 0

    def _apply_migrations(self, conn: object, from_version: int) -> None:
        """Apply migrations from from_version to _CURRENT_SCHEMA_VERSION."""
        # Migration 0 -> 1 is the initial schema (applied via db_schema.sql)
        # Future migrations go here as elif blocks
        if from_version < 1:
            self._log("Migration 0->1 should be applied via docs/db_schema.sql")

    # ── Worker lifecycle ──

    def register_worker(
        self,
        hecras_version: str = "",
        hecras_path: str = "",
        max_concurrent: int = 1,
    ) -> WorkerInfo:
        """Register this machine as a worker. Returns WorkerInfo."""
        hostname = socket.gethostname()
        try:
            ip_address = socket.gethostbyname(hostname)
        except socket.gaierror:
            ip_address = "127.0.0.1"
        os_version = platform.platform()

        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                f"""
                INSERT INTO {_SCHEMA}.workers
                    (hostname, ip_address, os_version, hecras_version, hecras_path,
                     max_concurrent, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'idle')
                RETURNING id
                """,
                (hostname, ip_address, os_version, hecras_version, hecras_path,
                 max_concurrent),
            ).fetchone()
            conn.commit()

        worker_id = str(row[0])
        self._log(f"Registered as worker {worker_id} ({hostname})")
        return WorkerInfo(worker_id=worker_id, hostname=hostname, ip_address=ip_address)

    def heartbeat(self, worker_id: str) -> None:
        """Update worker heartbeat timestamp."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                f"UPDATE {_SCHEMA}.workers SET last_heartbeat = now() WHERE id = %s",
                (worker_id,),
            )
            conn.commit()

    def start_heartbeat(self, worker_id: str, interval: float = 30.0) -> None:
        """Start a daemon thread that sends heartbeats every *interval* seconds."""
        self._heartbeat_stop.clear()

        def _loop() -> None:
            while not self._heartbeat_stop.wait(interval):
                try:
                    self.heartbeat(worker_id)
                except Exception as e:
                    self._log(f"Heartbeat failed: {e}")

        self._heartbeat_thread = threading.Thread(target=_loop, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread."""
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

    def set_worker_offline(self, worker_id: str) -> None:
        """Mark a worker as offline."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                f"UPDATE {_SCHEMA}.workers SET status = 'offline' WHERE id = %s",
                (worker_id,),
            )
            conn.commit()

    # ── Batch submission (orchestrator side) ──

    def submit_batch(
        self,
        project_path: str,
        project_title: str,
        jobs: list[dict],
        submitted_by: str = "",
    ) -> str:
        """Submit a batch of simulation jobs. Returns the batch_id (UUID string)."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                f"""
                INSERT INTO {_SCHEMA}.batches
                    (project_path, project_title, submitted_by, total_jobs, status)
                VALUES (%s, %s, %s, %s, 'pending')
                RETURNING id
                """,
                (project_path, project_title, submitted_by, len(jobs)),
            ).fetchone()
            batch_id = str(row[0])

            for job in jobs:
                conn.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.jobs
                        (batch_id, plan_name, plan_suffix, status)
                    VALUES (%s, %s, %s, 'queued')
                    """,
                    (batch_id, job["plan_name"], job["plan_suffix"]),
                )

            conn.commit()

        self._log(f"Submitted batch {batch_id} with {len(jobs)} jobs")
        return batch_id

    def get_batch_status(self, batch_id: str) -> dict:
        """Get summary status of a batch."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            batch_row = conn.execute(
                f"SELECT status, total_jobs FROM {_SCHEMA}.batches WHERE id = %s",
                (batch_id,),
            ).fetchone()

            if batch_row is None:
                return {"status": "not_found", "total": 0, "completed": 0, "failed": 0}

            counts = conn.execute(
                f"""
                SELECT status, COUNT(*) FROM {_SCHEMA}.jobs
                WHERE batch_id = %s GROUP BY status
                """,
                (batch_id,),
            ).fetchall()

        status_counts = dict(counts)
        return {
            "status": batch_row[0],
            "total": batch_row[1],
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "running": status_counts.get("running", 0),
            "queued": status_counts.get("queued", 0),
        }

    # ── Job pickup (worker side) ──

    def claim_job(self, worker_id: str) -> dict | None:
        """Claim the next queued job using SELECT ... FOR UPDATE SKIP LOCKED.

        Returns a dict with job details, or None if no jobs available.
        """
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                f"""
                UPDATE {_SCHEMA}.jobs
                SET status = 'assigned', worker_id = %s, assigned_at = now()
                WHERE id = (
                    SELECT id FROM {_SCHEMA}.jobs
                    WHERE status = 'queued'
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, batch_id, plan_name, plan_suffix
                """,
                (worker_id,),
            ).fetchone()
            conn.commit()

        if row is None:
            return None

        # Fetch project_path from batch
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            batch_row = conn.execute(
                f"SELECT project_path FROM {_SCHEMA}.batches WHERE id = %s",
                (str(row[1]),),
            ).fetchone()

        return {
            "job_id": str(row[0]),
            "batch_id": str(row[1]),
            "plan_name": row[2],
            "plan_suffix": row[3],
            "project_path": batch_row[0] if batch_row else "",
        }

    def start_job(self, job_id: str) -> None:
        """Mark a job as running."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                f"""
                UPDATE {_SCHEMA}.jobs
                SET status = 'running', started_at = now()
                WHERE id = %s
                """,
                (job_id,),
            )
            # Update batch status if this is the first running job
            conn.execute(
                f"""
                UPDATE {_SCHEMA}.batches b
                SET status = 'running'
                WHERE b.id = (SELECT batch_id FROM {_SCHEMA}.jobs WHERE id = %s)
                  AND b.status = 'pending'
                """,
                (job_id,),
            )
            conn.commit()

    def complete_job(
        self,
        job_id: str,
        success: bool,
        elapsed_seconds: float,
        error_message: str | None = None,
        exit_code: int | None = None,
        hdf_verified: bool | None = None,
    ) -> None:
        """Mark a job as completed or failed."""
        status = "completed" if success else "failed"
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                f"""
                UPDATE {_SCHEMA}.jobs
                SET status = %s, completed_at = now(), elapsed_seconds = %s,
                    error_message = %s, exit_code = %s, hdf_verified = %s,
                    progress = CASE WHEN %s THEN 1.0 ELSE progress END
                WHERE id = %s
                """,
                (status, elapsed_seconds, error_message, exit_code, hdf_verified,
                 success, job_id),
            )

            # Check if all jobs in batch are done
            batch_row = conn.execute(
                f"""
                SELECT batch_id FROM {_SCHEMA}.jobs WHERE id = %s
                """,
                (job_id,),
            ).fetchone()

            if batch_row:
                batch_id = str(batch_row[0])
                remaining = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM {_SCHEMA}.jobs
                    WHERE batch_id = %s AND status NOT IN ('completed', 'failed')
                    """,
                    (batch_id,),
                ).fetchone()

                if remaining and remaining[0] == 0:
                    # All done — mark batch completed/failed
                    failed = conn.execute(
                        f"""
                        SELECT COUNT(*) FROM {_SCHEMA}.jobs
                        WHERE batch_id = %s AND status = 'failed'
                        """,
                        (batch_id,),
                    ).fetchone()
                    batch_status = "failed" if (failed and failed[0] > 0) else "completed"
                    conn.execute(
                        f"""
                        UPDATE {_SCHEMA}.batches
                        SET status = %s, completed_at = now()
                        WHERE id = %s
                        """,
                        (batch_status, batch_id),
                    )

            conn.commit()

    def update_progress(self, job_id: str, progress: float) -> None:
        """Update job progress (0.0 to 1.0)."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                f"UPDATE {_SCHEMA}.jobs SET progress = %s WHERE id = %s",
                (progress, job_id),
            )
            conn.commit()

    # ── Real-time notifications ──

    def listen_for_jobs(self, callback: Callable[[str], None]) -> threading.Thread:
        """Start a daemon thread that listens for NOTIFY on ``hecras_jobs`` channel.

        The callback receives the notification payload string.
        Returns the thread (already started).
        """
        def _listen() -> None:
            try:
                import psycopg

                # Use a dedicated connection for LISTEN (not from pool)
                conninfo = self._pool.conninfo  # type: ignore[attr-defined]
                with psycopg.connect(conninfo, autocommit=True) as conn:
                    conn.execute("LISTEN hecras_jobs")
                    for notify in conn.notifies():
                        callback(notify.payload)
            except Exception as e:
                self._log(f"LISTEN thread error: {e}")

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        return t

    # ── Queries ──

    def get_active_workers(self) -> list[dict]:
        """Return workers with heartbeat within the last 2 minutes."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                f"""
                SELECT id, hostname, ip_address, status, hecras_version,
                       max_concurrent, last_heartbeat
                FROM {_SCHEMA}.workers
                WHERE last_heartbeat > now() - INTERVAL '2 minutes'
                ORDER BY hostname
                """
            ).fetchall()

        return [
            {
                "id": str(r[0]),
                "hostname": r[1],
                "ip_address": str(r[2]) if r[2] else "",
                "status": r[3],
                "hecras_version": r[4] or "",
                "max_concurrent": r[5],
                "last_heartbeat": r[6],
            }
            for r in rows
        ]

    def get_batch_jobs(self, batch_id: str) -> list[dict]:
        """Return all jobs for a batch."""
        with self._pool.connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                f"""
                SELECT id, plan_name, plan_suffix, status, worker_id,
                       elapsed_seconds, error_message, progress
                FROM {_SCHEMA}.jobs
                WHERE batch_id = %s
                ORDER BY plan_suffix
                """,
                (batch_id,),
            ).fetchall()

        return [
            {
                "id": str(r[0]),
                "plan_name": r[1],
                "plan_suffix": r[2],
                "status": r[3],
                "worker_id": str(r[4]) if r[4] else None,
                "elapsed_seconds": r[5],
                "error_message": r[6],
                "progress": r[7] or 0.0,
            }
            for r in rows
        ]
