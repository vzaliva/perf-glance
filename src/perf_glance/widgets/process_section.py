"""Process list section widget with grouping."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from perf_glance.grouping.process_groups import ProcessGroup
from perf_glance.utils.humanize import bytes_to_human


class ProcessSection(Static):
    """Widget showing grouped process list with sort and scroll."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sort_by: str = "cpu"  # "cpu" or "mem"
        self._scroll_offset: int = 0
        self._group_count: int = 0

    def set_sort(self, sort_by: str) -> None:
        """Set sort column: 'cpu' or 'mem'."""
        self._sort_by = sort_by

    def cycle_sort(self) -> str:
        """Cycle sort order and return new sort."""
        self._sort_by = "mem" if self._sort_by == "cpu" else "cpu"
        return self._sort_by

    def do_scroll_up(self) -> None:
        """Scroll process list view up."""
        self._scroll_offset = max(0, self._scroll_offset - 1)

    def do_scroll_down(self) -> None:
        """Scroll view down."""
        self._scroll_offset = min(
            max(0, self._group_count - 1),
            self._scroll_offset + 1,
        )

    def update_processes(
        self,
        groups: list[ProcessGroup],
        theme: object,
        visible_rows: int,
    ) -> None:
        """Update display from process groups."""
        self._group_count = len(groups)
        if not groups:
            self.update("")
            return

        # Sort
        if self._sort_by == "mem":
            groups = sorted(groups, key=lambda g: g.mem_bytes, reverse=True)
        else:
            groups = sorted(groups, key=lambda g: g.cpu_pct, reverse=True)

        # Fixed column widths for alignment
        NAME_WIDTH = 38
        PROCS_WIDTH = 6
        CPU_WIDTH = 7
        MEMPCT_WIDTH = 6
        MEM_WIDTH = 7

        proc_count_color = getattr(theme, "proc_count", "#4dd0e1")
        sort_active = getattr(theme, "proc_sort_active", "bold")
        header_color = getattr(theme, "proc_count", "#4dd0e1")
        # Active sort gets [CPU%] or [MEM%]
        h_cpu = "[CPU%]" if self._sort_by == "cpu" else "CPU%"
        h_mem = "[MEM%]" if self._sort_by == "mem" else "MEM%"

        text = Text()
        text.append("Processes".ljust(NAME_WIDTH), style=header_color)
        text.append(" ")
        text.append("Procs".rjust(PROCS_WIDTH), style=header_color)
        text.append(" ")
        text.append(h_cpu.rjust(CPU_WIDTH), style=sort_active if self._sort_by == "cpu" else header_color)
        text.append(" ")
        text.append(h_mem.rjust(MEMPCT_WIDTH), style=sort_active if self._sort_by == "mem" else header_color)
        text.append(" ")
        text.append("MEM".rjust(MEM_WIDTH) + "\n", style=header_color)

        # Apply scroll
        max_offset = max(0, len(groups) - visible_rows)
        self._scroll_offset = min(self._scroll_offset, max_offset)
        start = self._scroll_offset
        end = min(start + visible_rows, len(groups))
        visible = groups[start:end]

        for g in visible:
            display_name = (g.name or "[other]").strip() or "[other]"
            name = (display_name[: NAME_WIDTH - 1] + "…" if len(display_name) > NAME_WIDTH else display_name).ljust(NAME_WIDTH)
            procs_str = str(g.proc_count).rjust(PROCS_WIDTH)
            cpu_str = f"{g.cpu_pct:5.1f}".rjust(CPU_WIDTH)
            mempct_str = f"{g.mem_pct:4.1f}".rjust(MEMPCT_WIDTH)
            mem_str = bytes_to_human(g.mem_bytes).rjust(MEM_WIDTH)
            text.append(name)
            text.append(" ")
            text.append(procs_str, style=proc_count_color)
            text.append(" ")
            text.append(cpu_str)
            text.append(" ")
            text.append(mempct_str)
            text.append(" ")
            text.append(mem_str + "\n")

        self.update(text)
