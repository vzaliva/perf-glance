"""Cgroup helpers built on psutil process snapshots."""

from __future__ import annotations

import psutil

from perf_glance.psutil_linux import process_snapshot


def process_meta(pid: int) -> dict[str, object]:
    """Return a small per-process metadata dict.

    WORKAROUND: includes `cgroup_unit` injected by psutil_linux.process_snapshot()
    via /proc/<pid>/cgroup, because psutil does not expose cgroups on Linux.
    """
    try:
        snap = process_snapshot(psutil.Process(pid))
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
        return {}
    return {
        "pid": pid,
        "name": snap.get("name", ""),
        "uid": snap.get("uid", 0),
        "cgroup_unit": snap.get("cgroup_unit"),
    }


def get_cgroup_unit(pid: int) -> str | None:
    """Return systemd cgroup unit name if available."""
    meta = process_meta(pid)
    unit = meta.get("cgroup_unit")
    return str(unit) if isinstance(unit, str) and unit else None
