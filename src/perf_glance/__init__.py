"""perf-glance: terminal-based system utilization monitor for Linux."""

__version__ = "0.1.0"


def main() -> None:
    """Entry point for the perf-glance CLI."""
    from perf_glance.__main__ import run

    run()
