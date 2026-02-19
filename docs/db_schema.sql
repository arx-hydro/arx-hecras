-- hecras_runner database schema
-- Target: hydro_arx_dev on RDS (PostgreSQL)
-- Run as: hydro_arx_admin (or superuser)
--
-- Usage:
--   psql -h <rds-host> -U hydro_arx_admin -d hydro_arx_dev -f docs/db_schema.sql

-- ── Schema ──

CREATE SCHEMA IF NOT EXISTS hecras_runner;

-- ── Service account ──

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hecras_runner') THEN
        CREATE ROLE hecras_runner LOGIN PASSWORD 'CHANGE_ME';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA hecras_runner TO hecras_runner;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA hecras_runner TO hecras_runner;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA hecras_runner TO hecras_runner;

-- Auto-grant on future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA hecras_runner
    GRANT ALL PRIVILEGES ON TABLES TO hecras_runner;
ALTER DEFAULT PRIVILEGES IN SCHEMA hecras_runner
    GRANT ALL PRIVILEGES ON SEQUENCES TO hecras_runner;

-- ── Migration tracking ──

CREATE TABLE IF NOT EXISTS hecras_runner.schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    description TEXT NOT NULL DEFAULT ''
);

-- Insert version 0 if table is empty (fresh install)
INSERT INTO hecras_runner.schema_version (version, description)
VALUES (0, 'Initial schema creation')
ON CONFLICT DO NOTHING;

-- ── Migration 001: Core tables ──

-- Workers: each GUI/CLI instance registers itself
CREATE TABLE IF NOT EXISTS hecras_runner.workers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname        TEXT NOT NULL,
    ip_address      INET,
    os_version      TEXT,
    hecras_version  TEXT,
    hecras_path     TEXT,
    max_concurrent  INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'idle'
                    CHECK (status IN ('idle', 'busy', 'offline', 'error')),
    last_heartbeat  TIMESTAMPTZ NOT NULL DEFAULT now(),
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_workers_status
    ON hecras_runner.workers (status);

-- Batches: a group of plans submitted together
CREATE TABLE IF NOT EXISTS hecras_runner.batches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_path    TEXT NOT NULL,
    project_title   TEXT NOT NULL DEFAULT '',
    submitted_by    TEXT NOT NULL DEFAULT '',
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    total_jobs      INTEGER NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Jobs: individual plan executions
CREATE TABLE IF NOT EXISTS hecras_runner.jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES hecras_runner.batches(id) ON DELETE CASCADE,
    plan_name       TEXT NOT NULL,
    plan_suffix     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'assigned', 'running', 'completed', 'failed', 'cancelled')),
    worker_id       UUID REFERENCES hecras_runner.workers(id) ON DELETE SET NULL,
    assigned_at     TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    elapsed_seconds REAL,
    error_message   TEXT,
    exit_code       INTEGER,
    hdf_verified    BOOLEAN,
    progress        REAL DEFAULT 0.0,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_jobs_batch_id
    ON hecras_runner.jobs (batch_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON hecras_runner.jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_worker_id
    ON hecras_runner.jobs (worker_id);

-- Claim next job: partial index for efficient queue polling
CREATE INDEX IF NOT EXISTS idx_jobs_queued
    ON hecras_runner.jobs (batch_id, id) WHERE status = 'queued';

-- Metrics: per-job resource usage snapshots
CREATE TABLE IF NOT EXISTS hecras_runner.metrics (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id          UUID NOT NULL REFERENCES hecras_runner.jobs(id) ON DELETE CASCADE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    cpu_percent     REAL,
    memory_mb       REAL,
    progress        REAL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_metrics_job_id
    ON hecras_runner.metrics (job_id);

-- Record migration version
INSERT INTO hecras_runner.schema_version (version, description)
VALUES (1, 'Core tables: workers, batches, jobs, metrics')
ON CONFLICT DO NOTHING;
