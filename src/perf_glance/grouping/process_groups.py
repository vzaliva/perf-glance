"""Two-tier process grouping: tree grouping first, then binary name grouping."""

from __future__ import annotations

import os
import pwd
from dataclasses import dataclass

# Thresholds for collapsing uninteresting single groups
_USER_SVC_CPU_MAX = 0.2          # %
_USER_SVC_MEM_MAX = 80 << 20    # 80 MB
_OTHER_CPU_MAX    = 0.1          # %
_OTHER_MEM_MAX    = 30 << 20    # 30 MB


@dataclass
class ProcessGroup:
    """A group of processes with aggregated stats."""

    name: str
    proc_count: int
    cpu_pct: float
    mem_bytes: int
    mem_pct: float  # percent of total RAM
    user: str = ""


def _current_username() -> str:
    """Return the username of the process owner (current user)."""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except (KeyError, OverflowError):
        return os.environ.get("USER", "")


def _uid_to_user(uid: int) -> str:
    """Resolve a numeric uid to a username."""
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OverflowError):
        return str(uid)


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
) -> int:
    """Walk up the tree to find the group root.

    Rules:
    - Generic processes (shells, sudo, etc.) are transparent: skip them and keep walking up.
    - Non-generic processes stop at the current node UNLESS the parent has the same
      binary name (same application family, e.g. all firefox/chrome/electron processes),
      in which case we walk up to keep the family together.
    """
    current = pid
    while True:
        name = name_map.get(current, "").lower()
        ppid = ppid_map.get(current)
        if ppid is None or ppid <= 0 or ppid == current or ppid not in ppid_map:
            return current

        parent_name = name_map.get(ppid, "").lower()

        if name in generic_parents:
            # Generic: skip over this node, walk up to parent
            current = ppid
        elif parent_name in generic_parents:
            # Parent is generic (e.g. systemd, bash): this process is the group root
            return current
        elif parent_name == name:
            # Same binary name as parent: walk up to keep process family together
            current = ppid
        else:
            # Different non-generic parent: this process is its own root
            return current


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
        # Kernel threads have no cmdline (user-space processes always have one)
        if not proc.cmdline:
            k: int | str = "kernel_threads"
        elif _normalize_exe(proc.exe) in force_set:
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

        if key == "kernel_threads":
            name = "kernel threads"
            user = "root"
        elif isinstance(key, str) and key.startswith("exe:"):
            exe = key[4:]
            name = _humanize_exe_group(exe, procs)
            user = _uid_to_user(procs[0].uid) if procs else ""
        else:
            root_pid = key if isinstance(key, int) else 0
            root_proc = pid_to_proc.get(root_pid)
            if root_proc:
                name = _humanize_tree_group(root_proc, pid_to_proc)
                user = _uid_to_user(root_proc.uid)
            else:
                name = procs[0].exe or procs[0].name if procs else "[other]"
                user = _uid_to_user(procs[0].uid) if procs else ""

        if name.lower() == "systemd":
            name = "systemd services"
        if not name or not name.strip():
            name = "[other]"

        result.append(
            ProcessGroup(
                name=name,
                proc_count=len(procs),
                cpu_pct=cpu_pct,
                mem_bytes=mem_bytes,
                mem_pct=mem_pct,
                user=user,
            )
        )

    result = _post_process_groups(result)
    return result


def _post_process_groups(groups: list[ProcessGroup]) -> list[ProcessGroup]:
    """Three-pass post-processing:
    1. Merge groups that have the same display name.
    2. Bucket small user-owned groups into "user services".
    3. Bucket remaining tiny groups into "other (N)".
    """
    _PRESERVED = {"kernel threads", "systemd services"}
    current_user = _current_username()

    # Pass 1: deduplicate by name
    by_name: dict[str, ProcessGroup] = {}
    for g in groups:
        if g.name in by_name:
            e = by_name[g.name]
            by_name[g.name] = ProcessGroup(
                name=g.name,
                proc_count=e.proc_count + g.proc_count,
                cpu_pct=e.cpu_pct + g.cpu_pct,
                mem_bytes=e.mem_bytes + g.mem_bytes,
                mem_pct=e.mem_pct + g.mem_pct,
                user=e.user,
            )
        else:
            by_name[g.name] = g
    groups = list(by_name.values())

    # Pass 2 & 3: bucket small groups
    user_svc: list[ProcessGroup] = []
    other: list[ProcessGroup] = []
    kept: list[ProcessGroup] = []

    for g in groups:
        if g.name in _PRESERVED:
            kept.append(g)
        elif (
            g.user == current_user
            and g.cpu_pct < _USER_SVC_CPU_MAX
            and g.mem_bytes < _USER_SVC_MEM_MAX
        ):
            user_svc.append(g)
        elif g.cpu_pct < _OTHER_CPU_MAX and g.mem_bytes < _OTHER_MEM_MAX:
            other.append(g)
        else:
            kept.append(g)

    if user_svc:
        kept.append(ProcessGroup(
            name="user services",
            proc_count=sum(g.proc_count for g in user_svc),
            cpu_pct=sum(g.cpu_pct for g in user_svc),
            mem_bytes=sum(g.mem_bytes for g in user_svc),
            mem_pct=sum(g.mem_pct for g in user_svc),
            user=current_user,
        ))

    if other:
        n = sum(g.proc_count for g in other)
        kept.append(ProcessGroup(
            name=f"other ({n})",
            proc_count=n,
            cpu_pct=sum(g.cpu_pct for g in other),
            mem_bytes=sum(g.mem_bytes for g in other),
            mem_pct=sum(g.mem_pct for g in other),
            user="",
        ))

    return kept


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
