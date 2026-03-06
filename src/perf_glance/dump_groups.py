"""Dump process group tree to stdout or file (for testing)."""

from __future__ import annotations

import sys
from typing import TextIO

from perf_glance.grouping.process_groups import ProcessGroup
from perf_glance.utils.humanize import bytes_to_human

NAME_WIDTH = 32
USER_WIDTH = 8
PROCS_WIDTH = 6
CPU_WIDTH = 6
MEMPCT_WIDTH = 5
MEM_WIDTH = 7


def _proc_label(p: object) -> str:
    """Label for a single process in per-PID leaves: effective exe via launcher rules.

    For processes where no launcher transformation occurs (e.g. cursor subprocesses),
    appends the --type=xxx Electron flag so the per-PID row is distinguishable.
    """
    import re
    from perf_glance.grouping.process_groups import _effective_exe, _normalize_exe
    from perf_glance.grouping.rules_loader import load_grouping_rules_cached
    defaults = load_grouping_rules_cached()
    raw_exe = _normalize_exe(getattr(p, "exe", "") or getattr(p, "name", "") or "")
    exe = _effective_exe(p, defaults.transparent_runtimes, defaults.launchers_by_exe)
    label = exe or raw_exe
    if label == raw_exe:
        # No launcher transformation — try to show Electron --type= for context
        cmdline = getattr(p, "cmdline", "") or ""
        m = re.search(r"--type=(\S+)", cmdline)
        if m:
            label = f"{label} [{m.group(1)}]"
    return label


def _make_pid_leaves(g: ProcessGroup) -> None:
    """Populate g.children with per-PID leaf nodes for groups without subgroups.

    Skipped when all processes share the same exe (e.g. Electron Zygote/Utility
    subgroups that all show 'cursor') since per-PID rows would add no information.
    """
    procs = g.processes or []
    if not procs:
        return
    for p in procs:
        label = _proc_label(p)
        child_name = f"PID {p.pid}  {label}" if label else f"PID {p.pid}"
        g.children.append(ProcessGroup(
            name=child_name,
            proc_count=1,
            cpu_pct=p.cpu_pct,
            mem_bytes=getattr(p, "rss_bytes", 0) or 0,
            mem_pct=0.0,
            user=g.user,
            category=g.category,
            processes=[p],
            depth=g.depth + 1,
            group_key=f"{g.group_key}|pid:{p.pid}",
        ))


def _expand_all(groups: list[ProcessGroup]) -> None:
    """Expand all groups; for leaf groups with multiple processes, add per-PID rows."""
    for g in groups:
        if g.children:
            g.expanded = True
            _expand_all(g.children)
        elif g.processes and len(g.processes) > 1:
            _make_pid_leaves(g)
            if g.children:
                g.expanded = True


def _flatten_expanded(groups: list[ProcessGroup], depth: int = 0) -> list[tuple[ProcessGroup, int]]:
    """Flatten tree in display order with all branches expanded."""
    result: list[tuple[ProcessGroup, int]] = []
    for g in groups:
        result.append((g, depth))
        if g.children:
            result.extend(_flatten_expanded(g.children, depth + 1))
    return result


def _format_row(g: ProcessGroup, depth: int) -> str:
    """Format a single row as plain text (no ANSI)."""
    indent = "  " * depth
    if g.children:
        icon = "▼ "
    else:
        icon = "  "
    display_name = (g.name or "[other]").strip() or "[other]"
    name_part = indent + icon + display_name
    if len(name_part) > NAME_WIDTH:
        name_part = name_part[: NAME_WIDTH - 1] + "…"
    name_part = name_part.ljust(NAME_WIDTH)
    user_str = (g.user or "")[:USER_WIDTH].ljust(USER_WIDTH)
    procs_str = str(g.proc_count).rjust(PROCS_WIDTH)
    cpu_str = f"{g.cpu_pct:5.1f}".rjust(CPU_WIDTH)
    mempct_str = f"{g.mem_pct:4.1f}".rjust(MEMPCT_WIDTH)
    mem_str = bytes_to_human(g.mem_bytes).rjust(MEM_WIDTH)
    return f"{name_part} {user_str} {procs_str} {cpu_str} {mempct_str} {mem_str}"


def dump_group_tree(
    groups: list[ProcessGroup],
    file: TextIO = sys.stdout,
    sort_by: str = "cpu",
) -> None:
    """Dump the full group tree (expanded) to stdout or file.

    Output matches the display format exactly, with all groups expanded.
    """
    if not groups:
        print("(no groups)", file=file)
        return

    if sort_by == "mem":
        groups = sorted(groups, key=lambda g: g.mem_bytes, reverse=True)
    elif sort_by == "count":
        groups = sorted(groups, key=lambda g: g.proc_count, reverse=True)
    else:
        groups = sorted(groups, key=lambda g: g.cpu_pct, reverse=True)

    _expand_all(groups)
    flat = _flatten_expanded(groups)

    lines: list[str] = []
    lines.append("Command".ljust(NAME_WIDTH) + " " + "User".ljust(USER_WIDTH) + " " +
                 "#Procs".rjust(PROCS_WIDTH) + " " + "Cpu%".rjust(CPU_WIDTH) + " " +
                 "Mem%".rjust(MEMPCT_WIDTH) + " " + "MemB".rjust(MEM_WIDTH))
    lines.append("-" * (NAME_WIDTH + 1 + USER_WIDTH + 1 + PROCS_WIDTH + 1 + CPU_WIDTH + 1 + MEMPCT_WIDTH + 1 + MEM_WIDTH))
    for g, depth in flat:
        lines.append(_format_row(g, depth))

    print("\n".join(lines), file=file)
