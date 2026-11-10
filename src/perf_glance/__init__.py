"""perf-glance: terminal-based system utilization monitor for Linux."""

from __future__ import annotations

import json
from importlib import metadata

try:
    __version__ = metadata.version("perf-glance")
except metadata.PackageNotFoundError:  # running from an uninstalled tree
    __version__ = "0+unknown"


def version_string() -> str:
    """Version plus git commit when installed from a git URL (PEP 610)."""
    try:
        raw = metadata.distribution("perf-glance").read_text("direct_url.json")
        commit = (json.loads(raw).get("vcs_info") or {}).get("commit_id") if raw else None
    except (metadata.PackageNotFoundError, ValueError):
        commit = None
    return f"{__version__} ({commit[:12]})" if commit else __version__


def main() -> None:
    """Entry point for the perf-glance CLI."""
    from perf_glance.__main__ import run

    run()
