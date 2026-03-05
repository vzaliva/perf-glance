"""Process list collector — macOS (psutil)."""

from __future__ import annotations

import re
import time

import psutil

from perf_glance.collectors.linux.processes import ProcessInfo

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


def read_processes(
    previous_cpu_total: float,
    current_cpu_total: float,
    previous_per_pid: dict[int, tuple[int, int]] | None,
) -> tuple[list[ProcessInfo], dict[int, tuple[int, int]]]:
    """Read process list with CPU% via psutil."""
    pids = _list_pids()
    current_per_pid: dict[int, tuple[int, int]] = {}
    processes: list[ProcessInfo] = []

    cpu_delta = current_cpu_total - previous_cpu_total

    for pid in pids:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                name = proc.name()
                ppid = proc.ppid()
                try:
                    raw_exe = proc.exe()
                except (psutil.AccessDenied, OSError):
                    raw_exe = ""
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
                    mem = proc.memory_info()
                    rss_bytes = mem.rss
                except (psutil.AccessDenied, OSError):
                    rss_bytes = 0
                try:
                    cpu_times = proc.cpu_times()
                    total_time = int((cpu_times.user + cpu_times.system) * 100)
                except (psutil.AccessDenied, OSError):
                    total_time = 0
                try:
                    starttime_ticks = int(proc.create_time() * 100)
                except (psutil.AccessDenied, OSError):
                    starttime_ticks = 0
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue

        exe = _effective_exe(raw_exe) or name
        if "/" in exe:
            exe = exe.split("/")[-1]

        current_per_pid[pid] = (total_time, total_time)

        cpu_pct = 0.0
        if previous_per_pid and pid in previous_per_pid and cpu_delta > 0:
            prev_total = previous_per_pid[pid][0]
            process_delta = total_time - prev_total
            cpu_pct = 100.0 * process_delta / cpu_delta
            cpu_pct = min(100.0, max(0.0, cpu_pct))

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
                exe_path=raw_exe,
            )
        )

    return processes, current_per_pid


def get_aggregate_cpu_times() -> float:
    """Return total CPU-seconds across all cores (analogous to Linux ticks sum)."""
    cpu_count = psutil.cpu_count() or 1
    return time.monotonic() * cpu_count
