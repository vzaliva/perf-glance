"""CLI entry point for perf-glance."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from perf_glance.app import PerfGlanceApp
from perf_glance.config import load_config


def run_dump_groups(config_path: Path | None, sort_by: str = "cpu") -> None:
    """Run grouping once and dump expanded tree to stdout."""
    from perf_glance.collectors import get_aggregate_cpu_times, read_memory, read_processes
    from perf_glance.dump_groups import dump_group_tree
    from perf_glance.grouping import group_processes
    from perf_glance.grouping.desktop_entries import scan_desktop_entries

    config = load_config(config_path)
    dirs = getattr(config.grouping, "desktop_dirs", []) or []
    exe_to_app = scan_desktop_entries(dirs) if dirs else {}

    cpu_total = get_aggregate_cpu_times()
    processes, _ = read_processes(0.0, cpu_total, None)
    memory = read_memory()
    groups = group_processes(
        processes,
        memory.ram_total_bytes,
        config.grouping,
        exe_to_app,
    )
    dump_group_tree(groups, sys.stdout, sort_by=sort_by)


def run() -> None:
    """Run the perf-glance TUI or dump tool."""
    parser = argparse.ArgumentParser(
        prog="perf-glance",
        description="Terminal-based system utilization monitor for Linux",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Refresh interval (default: 2)",
    )
    parser.add_argument(
        "-n",
        "--iterations",
        type=int,
        default=None,
        metavar="N",
        help="Exit after N refreshes (useful for scripting)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Use alternate config file",
    )
    parser.add_argument(
        "--dump-groups",
        action="store_true",
        help="Dump group tree (fully expanded) to stdout and exit (for testing)",
    )
    parser.add_argument(
        "--dump-sort",
        choices=("cpu", "mem", "count"),
        default="cpu",
        help="Sort order for --dump-groups (default: cpu)",
    )
    args = parser.parse_args()

    if args.dump_groups:
        run_dump_groups(args.config, sort_by=args.dump_sort)
        return

    config = load_config(args.config)
    if args.interval is not None:
        config.display.refresh_interval = max(1, args.interval)

    app = PerfGlanceApp(config=config, iterations=args.iterations)
    app.run()
