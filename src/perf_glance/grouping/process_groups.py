"""Two-tier process grouping: tree grouping first, then binary name grouping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProcessGroup:
    """A group of processes with aggregated stats."""

    name: str
    proc_count: int
    cpu_pct: float
    mem_bytes: int
    mem_pct: float  # percent of total RAM


def _normalize_exe(exe: str) -> str:
    """Normalize executable name for grouping (e.g. python3 -> python)."""
    base = exe.lower()
    if base in ("python3", "python3.11", "python3.12"):
        return "python"
    return base


def _get_tree_root(
    pid: int,
    ppid_map: dict[int, int],
    name_map: dict[int, str],
    generic_parents: set[str],
) -> int | None:
    """Walk up the tree to find the group root (first non-generic ancestor)."""
    current = pid
    while True:
        name = name_map.get(current, "").lower()
        if name not in generic_parents:
            return current
        ppid = ppid_map.get(current)
        if ppid is None or ppid <= 0 or ppid == current:
            return current
        current = ppid


def group_processes(
    processes: list,
    ram_total_bytes: int,
    force_name_group: list[str],
    generic_parents: list[str],
) -> list[ProcessGroup]:
    """Group processes by tree (Tier 1) and binary name (Tier 2)."""
    from perf_glance.collectors.processes import ProcessInfo

    generic_set = {p.lower() for p in generic_parents}
    force_set = {e.lower() for e in force_name_group}

    pid_to_proc: dict[int, ProcessInfo] = {p.pid: p for p in processes}
    ppid_map: dict[int, int] = {p.pid: p.ppid for p in processes}
    name_map: dict[int, str] = {p.pid: p.exe or p.name for p in processes}
    # Also add exe from /proc/pid/exe for better root naming
    for p in processes:
        if p.exe:
            name_map[p.pid] = p.exe

    # Assign each process to a group key
    # Normalized key: int (root pid) for tree, or "exe:name" for force_name_group
    pid_to_key: dict[int, int | str] = {}

    for proc in processes:
        if _normalize_exe(proc.exe) in force_set:
            k = f"exe:{_normalize_exe(proc.exe)}"
        else:
            root = _get_tree_root(proc.pid, ppid_map, name_map, generic_set)
            if root is not None:
                k = root
            else:
                k = f"exe:{_normalize_exe(proc.exe)}"
        pid_to_key[proc.pid] = k

    # Build groups: key -> list of PIDs
    key_to_pids: dict[str | int, list[int]] = {}
    for pid, k in pid_to_key.items():
        key_to_pids.setdefault(k, []).append(pid)

    # Build ProcessGroup for each
    result: list[ProcessGroup] = []
    for key, pids in key_to_pids.items():
        procs = [pid_to_proc[pid] for pid in pids if pid in pid_to_proc]
        if not procs:
            continue
        cpu_pct = sum(p.cpu_pct for p in procs)
        mem_bytes = sum(p.rss_bytes for p in procs)
        mem_pct = 100.0 * mem_bytes / ram_total_bytes if ram_total_bytes else 0.0

        if isinstance(key, str) and key.startswith("exe:"):
            exe = key[4:]
            name = _humanize_exe_group(exe, procs)
        else:
            root_pid = key if isinstance(key, int) else 0
            root_proc = pid_to_proc.get(root_pid)
            if root_proc:
                name = _humanize_tree_group(root_proc, pid_to_proc)
            else:
                name = procs[0].exe or procs[0].name if procs else "[other]"

        if name.lower() == "systemd":
            name = "systemd services"
        elif procs and procs[0].ppid == 2 and not (procs[0].exe or procs[0].name):
            name = "kernel threads"
        elif not name:
            name = "[other]"

        result.append(
            ProcessGroup(
                name=name,
                proc_count=len(procs),
                cpu_pct=cpu_pct,
                mem_bytes=mem_bytes,
                mem_pct=mem_pct,
            )
        )

    return result


def _humanize_exe_group(exe: str, procs: list) -> str:
    """Human-readable name for binary-only group (e.g. python/python3)."""
    exes = {_normalize_exe(p.exe or p.name) for p in procs if (p.exe or p.name)}
    exes.discard("")
    if not exes:
        return "kernel threads" if any(getattr(p, "ppid", 0) == 2 for p in procs) else "[other]"
    if len(exes) <= 1:
        return procs[0].exe or procs[0].name or exe or "[other]"
    parts = sorted(exes)
    if "python" in parts:
        parts = ["python"] + [e for e in parts if e != "python" and e.startswith("python")]
    return " / ".join(parts)


def _humanize_tree_group(root_proc, pid_to_proc: dict) -> str:
    """Human-readable name for tree root (e.g. code (VSCode))."""
    exe = (root_proc.exe or root_proc.name or "").strip()
    name = (root_proc.name or "").strip()
    if "code" in exe.lower() or "code" in (root_proc.cmdline or "").lower():
        return "code (VSCode)"
    if "firefox" in exe.lower():
        return "firefox"
    if "Xorg" in exe or "Xorg" in name:
        return "Xorg / Wayland compositor"
    # Kernel threads and odd names
    if not exe and not name:
        return "[other]"
    if exe.isdigit() or name.isdigit():
        return "[other]"
    if exe.startswith("-") or name.startswith("-"):  # truncated comm
        return "kernel threads"
    return exe or name or "[other]"
