"""CLI entry point for perf-glance."""

from __future__ import annotations

import argparse
from pathlib import Path

from perf_glance.app import PerfGlanceApp
from perf_glance.config import load_config


def run() -> None:
    """Run the perf-glance TUI."""
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
    args = parser.parse_args()

    config = load_config(args.config)
    if args.interval is not None:
        config.display.refresh_interval = max(1, args.interval)

    app = PerfGlanceApp(config=config, iterations=args.iterations)
    app.run()
