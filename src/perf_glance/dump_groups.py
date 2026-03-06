"""Dump process group tree to stdout or file (for testing)."""

from __future__ import annotations

import sys
from typing import TextIO

from perf_glance.grouping.process_groups import ProcessGroup, proc_label
from perf_glance.utils.humanize import bytes_to_human

NAME_WIDTH = 32
USER_WIDTH = 8
PROCS_WIDTH = 6
CPU_WIDTH = 6
MEMPCT_WIDTH = 5
MEM_WIDTH = 7


def _make_pid_leaves(g: ProcessGroup) -> None:
    """Populate g.children with per-PID leaf nodes for groups without subgroups.

    Skipped when all processes share the same exe (e.g. Electron Zygote/Utility
    subgroups that all show 'cursor') since per-PID rows would add no information.
    """
    procs = g.processes or []
    if not procs:
        return
    for p in procs:
        label = proc_label(p)
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


def _format_row(g: ProcessGroup, depth: int, name_width: int = NAME_WIDTH) -> str:
    """Format a single row as plain text (no ANSI)."""
    indent = "  " * depth
    if g.children:
        icon = "▼ "
    else:
        icon = "  "
    display_name = (g.name or "[other]").strip() or "[other]"
    name_part = indent + icon + display_name
    name_part = name_part.ljust(name_width)
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

    # Compute name column width from actual content (no truncation)
    name_width = len("Command")
    for g, depth in flat:
        indent = "  " * depth
        icon = "▼ " if g.children else "  "
        display_name = (g.name or "[other]").strip() or "[other]"
        name_width = max(name_width, len(indent + icon + display_name))
    name_width = max(name_width, NAME_WIDTH)

    lines: list[str] = []
    lines.append("Command".ljust(name_width) + " " + "User".ljust(USER_WIDTH) + " " +
                 "#Procs".rjust(PROCS_WIDTH) + " " + "Cpu%".rjust(CPU_WIDTH) + " " +
                 "Mem%".rjust(MEMPCT_WIDTH) + " " + "MemB".rjust(MEM_WIDTH))
    lines.append("-" * (name_width + 1 + USER_WIDTH + 1 + PROCS_WIDTH + 1 + CPU_WIDTH + 1 + MEMPCT_WIDTH + 1 + MEM_WIDTH))
    for g, depth in flat:
        lines.append(_format_row(g, depth, name_width))

    print("\n".join(lines), file=file)
