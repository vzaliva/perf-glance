"""Linux psutil helpers with compatibility workarounds.

This module centralizes Linux process reads via psutil and exposes a
stable dictionary payload used by collectors/UI code.
"""

from __future__ import annotations

from pathlib import Path
import re

import psutil

_CGROUP_UNIT_RE = re.compile(r"^[a-z0-9@_.-]+\.(service|scope|slice)$")


def _read_cgroup_unit_from_proc(pid: int) -> str | None:
    """Best-effort systemd unit from /proc/<pid>/cgroup.

    WORKAROUND: psutil currently does not expose cgroup membership on Linux.
    """
    path = Path(f"/proc/{pid}/cgroup")
    try:
        content = path.read_text()
    except OSError:
        return None

    for line in content.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 3:
            continue
        cpath = parts[2]
        if not cpath.startswith("/"):
            continue
        segments = [s for s in cpath.split("/") if s]
        for seg in reversed(segments):
            seg_l = seg.lower()
            if _CGROUP_UNIT_RE.match(seg_l):
                return seg
            if seg_l.endswith(".service") or seg_l.endswith(".scope"):
                return seg
    return None


def process_snapshot(proc: psutil.Process) -> dict[str, object]:
    """Return normalized per-process fields from psutil.

    Includes a `cgroup_unit` field filled via /proc workaround.
    """
    with proc.oneshot():
        pid = proc.pid
        try:
            name = proc.name()
        except (psutil.AccessDenied, OSError):
            name = ""
        try:
            ppid = proc.ppid()
        except (psutil.AccessDenied, OSError):
            ppid = 0
        try:
            exe_path = proc.exe()
        except (psutil.AccessDenied, OSError):
            exe_path = ""
        try:
            cmdline_list = proc.cmdline()
            cmdline = " ".join(cmdline_list)
        except (psutil.AccessDenied, OSError):
            cmdline = ""
        try:
            uid = proc.uids().real
        except (psutil.AccessDenied, AttributeError):
            uid = 0
        try:
            rss_bytes = proc.memory_info().rss
        except (psutil.AccessDenied, OSError):
            rss_bytes = 0
        try:
            cpu_times = proc.cpu_times()
            total_time_ticks = int((cpu_times.user + cpu_times.system) * 100)
        except (psutil.AccessDenied, OSError):
            total_time_ticks = 0
        try:
            starttime_ticks = int(proc.create_time() * 100)
        except (psutil.AccessDenied, OSError):
            starttime_ticks = 0
        try:
            cwd = proc.cwd()
        except (psutil.AccessDenied, OSError):
            cwd = ""
        try:
            status = proc.status()
        except (psutil.AccessDenied, OSError):
            status = ""
        try:
            num_threads = proc.num_threads()
        except (psutil.AccessDenied, OSError):
            num_threads = 0

    return {
        "pid": pid,
        "name": name,
        "ppid": ppid,
        "exe_path": exe_path,
        "cmdline": cmdline,
        "uid": uid,
        "rss_bytes": rss_bytes,
        "total_time_ticks": total_time_ticks,
        "starttime_ticks": starttime_ticks,
        "cwd": cwd,
        "status": status,
        "num_threads": num_threads,
        # WORKAROUND: no native cgroup API in psutil on Linux.
        "cgroup_unit": _read_cgroup_unit_from_proc(pid),
    }
