"""Process list collector from psutil (Linux)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import psutil

from perf_glance.psutil_linux import process_snapshot


@dataclass
class ProcessInfo:
    """Info for a single process."""

    pid: int
    ppid: int
    name: str
    exe: str
    cpu_pct: float
    rss_bytes: int
    cmdline: str
    uid: int = 0
    starttime_ticks: int = 0
    exe_path: str = ""  # full resolved exe path (populated on macOS; empty on Linux)


_VERSION_EXE_RE = re.compile(r"^\d+(\.\d+)+$")


def _effective_exe(raw_exe: str) -> str:
    """Return a clean exe name from a full path, applying version-number stripping."""
    if not raw_exe:
        return ""
    from pathlib import Path
    p = Path(raw_exe)
    name = p.name
    if _VERSION_EXE_RE.match(name):
        grandparent = p.parent.parent.name
        if grandparent and not _VERSION_EXE_RE.match(grandparent):
            return grandparent
    return name


def _list_pids() -> list[int]:
    return psutil.pids()


def _snapshot_pid(pid: int) -> dict[str, object]:
    return process_snapshot(psutil.Process(pid))


def _to_int(value: object, default: int = 0) -> int:
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def read_processes(
    previous_cpu_total: float,
    current_cpu_total: float,
    previous_per_pid: dict[int, tuple[int, int]] | None,
) -> tuple[list[ProcessInfo], dict[int, tuple[int, int]]]:
    """Read process list with CPU% (requires delta from previous read).

    previous_cpu_total: sum of all CPU times (aggregate)
    current_cpu_total: same from current read
    previous_per_pid: dict of pid -> (utime+stime, utime+stime+cutime+cstime) from last read

    Returns (list of ProcessInfo, current per_pid for next call).
    """
    pids = _list_pids()
    current_per_pid: dict[int, tuple[int, int]] = {}
    processes: list[ProcessInfo] = []

    cpu_delta = current_cpu_total - previous_cpu_total

    for pid in pids:
        try:
            snap = _snapshot_pid(pid)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            continue

        name = _to_str(snap.get("name"))
        ppid = _to_int(snap.get("ppid"))
        cmdline = _to_str(snap.get("cmdline"))
        exe_path = _to_str(snap.get("exe_path"))
        exe = _effective_exe(exe_path)
        if not exe:
            # Prefer the longer of comm and cmdline basename to handle 15-char comm truncation
            # without regressing on symlink-named binaries (e.g. /sbin/init -> systemd)
            raw_cmdline_name = cmdline.split()[0].split("/")[-1] if cmdline else ""
            # Strip trailing punctuation that some daemons append (e.g. "avahi-daemon:")
            cmdline_name = raw_cmdline_name.rstrip(":,;")
            exe = cmdline_name if len(cmdline_name) > len(name) else name
        if "/" in exe:
            exe = exe.split("/")[-1]

        uid = _to_int(snap.get("uid"))
        total_time = _to_int(snap.get("total_time_ticks"))
        rss_bytes = _to_int(snap.get("rss_bytes"))
        starttime_ticks = _to_int(snap.get("starttime_ticks"))
        current_per_pid[pid] = (total_time, total_time)

        cpu_pct = 0.0
        if previous_per_pid and pid in previous_per_pid and cpu_delta > 0:
            prev_total = previous_per_pid[pid][0]
            process_delta = total_time - prev_total
            # process_delta/cpu_delta = fraction of total system CPU (aggregate already sums all cores)
            cpu_pct = 100.0 * process_delta / cpu_delta
            cpu_pct = min(100.0, max(0.0, cpu_pct))  # clamp 0-100

        processes.append(
            ProcessInfo(
                pid=pid,
                ppid=ppid,
                name=name,
                exe=exe,
                cpu_pct=cpu_pct,
                rss_bytes=rss_bytes,
                cmdline=cmdline,
                uid=uid,
                starttime_ticks=starttime_ticks,
                exe_path=exe_path,
            )
        )

    return processes, current_per_pid


def get_aggregate_cpu_times() -> float:
    """Return aggregate CPU time in pseudo-ticks (centiseconds)."""
    try:
        return float(sum(psutil.cpu_times()) * 100.0)
    except Exception:
        return 0.0
