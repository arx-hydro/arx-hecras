"""Command-line interface for HEC-RAS parallel runner."""

from __future__ import annotations

import argparse
import sys

from hecras_runner.parser import parse_project
from hecras_runner.runner import SimulationJob, check_hecras_installed, run_simulations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hecras-runner",
        description="Run HEC-RAS simulation plans in parallel.",
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
        parser.error("Specify --plans, --all, or --list")
        return 1  # unreachable, parser.error exits

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


if __name__ == "__main__":
    sys.exit(main())
