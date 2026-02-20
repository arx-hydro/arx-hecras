"""Command-line interface for HEC-RAS parallel runner."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from hecras_runner.parser import parse_project
from hecras_runner.runner import SimulationJob, check_hecras_installed, run_simulations


def _build_run_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add the 'run' subcommand (default behavior)."""
    parser = subparsers.add_parser("run", help="Run HEC-RAS simulations")
    parser.add_argument("project", help="Path to HEC-RAS .prj file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--plans",
        nargs="+",
        metavar="TITLE",
        help="Plan titles to run (e.g. plan01 plan03)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="Run all plans in the project",
    )
    group.add_argument(
        "--list",
        action="store_true",
        dest="list_plans",
        help="List plans in the project and exit",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Run plans sequentially instead of in parallel",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep temporary directories after completion",
    )
    parser.add_argument(
        "--dss",
        metavar="PATH",
        help="Override DSS file path for all plans",
    )
    parser.add_argument(
        "--hide-ras",
        action="store_true",
        help="Don't show HEC-RAS window during computation (COM backend only)",
    )
    parser.add_argument(
        "--use-com",
        action="store_true",
        help="Use COM automation instead of CLI backend",
    )
    parser.add_argument(
        "--max-cores",
        type=int,
        metavar="N",
        help="Limit CPU cores per simulation (CLI backend only)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=7200.0,
        metavar="SECONDS",
        help="Per-plan timeout in seconds (default: 7200)",
    )


def _build_worker_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add the 'worker' subcommand."""
    parser = subparsers.add_parser("worker", help="Run as a distributed worker")
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=1,
        metavar="N",
        help="Max simultaneous simulations (default: 1)",
    )
    parser.add_argument(
        "--max-cores",
        type=int,
        metavar="N",
        help="Limit CPU cores per simulation",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=7200.0,
        metavar="SECONDS",
        help="Per-plan timeout in seconds (default: 7200)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="Seconds between job queue polls (default: 5)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hecras-runner",
        description="Run HEC-RAS simulation plans in parallel.",
    )
    subparsers = parser.add_subparsers(dest="command")
    _build_run_parser(subparsers)
    _build_worker_parser(subparsers)

    # Backward compat: if no subcommand is given but positional args look like
    # the old interface (a .prj path), treat it as the 'run' subcommand.
    # This is handled in main() below.
    return parser


def _run_command(args: argparse.Namespace) -> int:
    """Handle the 'run' subcommand."""
    # Parse project
    try:
        project = parse_project(args.project)
    except (OSError, UnicodeDecodeError) as e:
        print(f"Error: Cannot read project file: {e}", file=sys.stderr)
        return 1

    if not project.plans:
        print("Error: No plans found in project file.", file=sys.stderr)
        return 1

    # --list mode
    if args.list_plans:
        print(f"Project: {project.title}")
        print(f"Plans ({len(project.plans)}):")
        for plan in project.plans:
            current = " (current)" if plan.key == project.current_plan else ""
            geom, flow = plan.geom_ref, plan.flow_ref
            print(f"  {plan.key}: {plan.title}  [geom={geom}, flow={flow}]{current}")
        return 0

    # Determine which plans to run
    if args.run_all:
        selected = project.plans
    elif args.plans:
        title_set = set(args.plans)
        selected = [p for p in project.plans if p.title in title_set]
        missing = title_set - {p.title for p in selected}
        if missing:
            print(f"Error: Plans not found: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
    else:
        print("Error: Specify --plans, --all, or --list", file=sys.stderr)
        return 1

    # Determine backend
    backend = "com" if args.use_com else "cli"

    # Check HEC-RAS installation
    if not check_hecras_installed(backend=backend):
        if backend == "com":
            print(
                "Error: HEC-RAS is not installed or COM server is not accessible.",
                file=sys.stderr,
            )
        else:
            print("Error: HEC-RAS executable (Ras.exe) not found.", file=sys.stderr)
        return 1

    # Build jobs
    dss = args.dss
    jobs = [
        SimulationJob(
            plan_name=plan.title,
            plan_suffix=plan.key[1:],  # "p03" -> "03"
            dss_path=dss,
        )
        for plan in selected
    ]

    run_simulations(
        project_path=args.project,
        jobs=jobs,
        parallel=not args.sequential,
        cleanup=not args.no_cleanup,
        show_ras=not args.hide_ras,
        backend=backend,
        max_cores=args.max_cores,
        timeout_seconds=args.timeout,
    )
    return 0


def _run_worker_job(
    job: dict,
    ras_exe: str,
    args: argparse.Namespace,
    db: object,
    settings: object,
) -> None:
    """Execute a single claimed job — with SMB transfer if share configured."""
    import tempfile

    from hecras_runner.file_ops import cleanup_temp_dir
    from hecras_runner.runner import run_hecras_cli

    job_id = job["job_id"]
    plan_name = job["plan_name"]
    plan_suffix = job["plan_suffix"]
    project_path = job["project_path"]

    db.start_job(job_id)  # type: ignore[attr-defined]

    share_path = settings.network.share_path  # type: ignore[attr-defined]
    use_transfer = bool(share_path)

    if use_transfer:
        from hecras_runner.transfer import (
            TransferManifest,
            results_to_share,
            share_to_local,
        )

        # Load manifest from share
        share_project_dir = os.path.join(share_path, "projects", job_id)
        manifest_file = os.path.join(share_project_dir, "manifest.json")

        import json

        with open(manifest_file, encoding="utf-8") as f:
            mdata = json.load(f)
        manifest = TransferManifest(**mdata)

        local_temp = tempfile.mkdtemp(prefix="HECRAS_")
        temp_prj = share_to_local(manifest, local_temp)
    else:
        from hecras_runner.file_ops import copy_project_to_temp

        temp_prj = copy_project_to_temp(project_path)
        local_temp = os.path.dirname(temp_prj)

    result = run_hecras_cli(
        temp_prj,
        plan_suffix=plan_suffix,
        plan_name=plan_name,
        ras_exe=ras_exe,
        max_cores=args.max_cores,
        timeout_seconds=args.timeout,
    )

    # Upload results to share if applicable
    if use_transfer:
        results_to_share(
            temp_prj,
            manifest.share_results_dir,  # type: ignore[possibly-undefined]
            plan_suffix,
        )

    db.complete_job(  # type: ignore[attr-defined]
        job_id,
        success=result.success,
        elapsed_seconds=result.elapsed_seconds,
        error_message=result.error_message,
        hdf_verified=result.success,
    )
    cleanup_temp_dir(local_temp)

    status = "OK" if result.success else "FAILED"
    print(f"  Job {job_id}: {status} ({result.elapsed_seconds:.1f}s)")


def _worker_command(args: argparse.Namespace) -> int:
    """Handle the 'worker' subcommand — claim and run jobs from the DB queue."""
    from hecras_runner.db import DbClient
    from hecras_runner.runner import find_hecras_exe
    from hecras_runner.settings import load_settings

    settings = load_settings()
    if not settings.db.host:
        print("Error: Database not configured. Run the GUI to set up connection.", file=sys.stderr)
        return 1

    # Check HEC-RAS
    ras_exe = find_hecras_exe()
    if not ras_exe:
        print("Error: HEC-RAS executable (Ras.exe) not found.", file=sys.stderr)
        return 1

    # Connect to DB
    db = DbClient.connect(settings.db)
    if db is None:
        print("Error: Cannot connect to database.", file=sys.stderr)
        return 1

    try:
        # Register as worker
        worker = db.register_worker(
            hecras_path=ras_exe,
            max_concurrent=args.max_concurrent,
        )
        db.start_heartbeat(worker.worker_id)

        # Graceful shutdown on Ctrl+C
        shutdown = False

        def _signal_handler(sig: int, frame: object) -> None:
            nonlocal shutdown
            print("\nShutting down worker...")
            shutdown = True

        signal.signal(signal.SIGINT, _signal_handler)

        print(f"Worker {worker.worker_id} online ({worker.hostname})")
        print(
            f"Polling for jobs every {args.poll_interval}s"
            f" (max concurrent: {args.max_concurrent})"
        )

        while not shutdown:
            job = db.claim_job(worker.worker_id)
            if job is None:
                time.sleep(args.poll_interval)
                continue

            job_id = job["job_id"]
            plan_name = job["plan_name"]
            plan_suffix = job["plan_suffix"]

            print(f"Claimed job {job_id}: {plan_name} (p{plan_suffix})")
            db.start_job(job_id)

            try:
                _run_worker_job(job, ras_exe, args, db, settings)
            except Exception as e:
                db.complete_job(
                    job_id, success=False, elapsed_seconds=0.0, error_message=str(e),
                )
                print(f"  Job {job_id}: ERROR ({e})")

        # Clean shutdown
        db.set_worker_offline(worker.worker_id)
        print("Worker offline.")

    finally:
        db.close()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()

    # Backward compat: if first arg is not a known subcommand but looks like
    # a file path or flag, insert "run" as the subcommand.
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in ("run", "worker", "-h", "--help"):
        argv = ["run", *argv]

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run_command(args)
    elif args.command == "worker":
        return _worker_command(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
