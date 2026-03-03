"""Process list collector from /proc."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


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


def _page_size() -> int:
    """Return system page size in bytes."""
    try:
        return os.sysconf("SC_PAGESIZE")
    except (AttributeError, ValueError):
        return 4096


def _parse_proc_stat(pid: int) -> tuple[str, int, int, int, int] | None:
    """Parse /proc/<pid>/stat. Returns (comm, ppid, utime, stime, rss_bytes) or None. comm may have spaces in parens."""
    path = Path(f"/proc/{pid}/stat")
    if not path.exists():
        return None
    try:
        data = path.read_text()
    except OSError:
        return None
    # Format: pid (comm) state ppid pgrp session ... utime stime ... vsize rss
    # comm can contain spaces/parens; must extract rest after ") " to get correct field indices
    match = re.match(r"(\d+)\s+\((.+)\)\s+\S+\s+(\d+)\s+", data)
    if not match:
        return None
    comm = match.group(2)
    ppid = int(match.group(3))
    # Everything after ") state ppid " - split gives: pgrp, session, tty, tpgid, flags, minflt,
    # cminflt, majflt, cmajflt, utime, stime, cutime, cstime, priority, nice, num_threads,
    # itrealvalue, starttime, vsize, rss (indices 0-19)
    rest = data[match.end() :].split()
    if len(rest) < 20:
        return None
    try:
        utime = int(rest[9])
        stime = int(rest[10])
        rss_pages = int(rest[19])  # rss in pages, NOT vsize (rest[18] which would be terabytes)
    except (IndexError, ValueError):
        return None
    rss_bytes = rss_pages * _page_size()
    return (comm, ppid, utime, stime, rss_bytes)


def _read_status(pid: int) -> dict[str, str]:
    """Read /proc/<pid>/status as key: value."""
    path = Path(f"/proc/{pid}/status")
    result: dict[str, str] = {}
    if not path.exists():
        return result
    try:
        for line in path.read_text().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip()
    except OSError:
        pass
    return result


def _read_cmdline(pid: int) -> str:
    """Read /proc/<pid>/cmdline, null bytes become spaces."""
    path = Path(f"/proc/{pid}/cmdline")
    if not path.exists():
        return ""
    try:
        data = path.read_bytes()
        return data.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _read_exe(pid: int) -> str:
    """Read resolved exe path for process."""
    try:
        path = Path(f"/proc/{pid}/exe")
        if not path.exists():
            return ""
        return path.resolve().name
    except (OSError, PermissionError, RuntimeError):
        return ""


def _list_pids() -> list[int]:
    """List all numeric PIDs in /proc."""
    pids: list[int] = []
    proc = Path("/proc")
    if not proc.exists():
        return pids
    for d in proc.iterdir():
        if d.name.isdigit():
            pids.append(int(d.name))
    return pids


def read_processes(
    previous_cpu_total: float,
    current_cpu_total: float,
    previous_per_pid: dict[int, tuple[int, int]] | None,
) -> tuple[list[ProcessInfo], dict[int, tuple[int, int]]]:
    """Read process list with CPU% (requires delta from previous read).

    previous_cpu_total: sum of all CPU times from /proc/stat (aggregate)
    current_cpu_total: same from current read
    previous_per_pid: dict of pid -> (utime+stime, utime+stime+cutime+cstime) from last read

    Returns (list of ProcessInfo, current per_pid for next call).
    """
    pids = _list_pids()
    current_per_pid: dict[int, tuple[int, int]] = {}
    processes: list[ProcessInfo] = []

    cpu_delta = current_cpu_total - previous_cpu_total
    # Count logical CPUs from /proc/stat
    num_cores = 0
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu"):
                if line.startswith("cpu "):
                    continue
                num_cores += 1
    if num_cores == 0:
        num_cores = 1

    for pid in pids:
        stat = _parse_proc_stat(pid)
        if stat is None:
            continue
        comm, ppid, utime, stime, rss_bytes = stat
        status = _read_status(pid)
        name = status.get("Name", comm)
        exe = _read_exe(pid) or comm.strip("()")
        cmdline = _read_cmdline(pid)
        if not exe and cmdline:
            exe = cmdline.split()[0] if cmdline else comm
        if "/" in exe:
            exe = exe.split("/")[-1]

        total_time = utime + stime
        current_per_pid[pid] = (total_time, total_time)

        cpu_pct = 0.0
        if previous_per_pid and pid in previous_per_pid and cpu_delta > 0:
            prev_total = previous_per_pid[pid][0]
            process_delta = total_time - prev_total
            # process_delta/cpu_delta is fraction of one core; * num_cores for total system
            cpu_pct = 100.0 * process_delta * num_cores / cpu_delta

        processes.append(
            ProcessInfo(
                pid=pid,
                ppid=ppid,
                name=name,
                exe=exe,
                cpu_pct=cpu_pct,
                rss_bytes=rss_bytes,
                cmdline=cmdline,
            )
        )

    return processes, current_per_pid


def get_aggregate_cpu_times() -> float:
    """Read /proc/stat aggregate cpu line, return total (user+nice+system+idle+...) in ticks."""
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu "):
                parts = line.split()
                total = 0
                for i in range(1, min(11, len(parts))):
                    try:
                        total += int(parts[i])
                    except ValueError:
                        pass
                return float(total)
    return 0.0
