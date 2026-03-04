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


def _expand_all(groups: list[ProcessGroup]) -> None:
    """Set expanded=True on all groups that have children."""
    for g in groups:
        if g.children:
            g.expanded = True
            _expand_all(g.children)


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
