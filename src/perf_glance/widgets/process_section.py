"""Process list section widget with grouping."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from perf_glance.grouping.process_groups import ProcessGroup
from perf_glance.utils.humanize import bytes_to_human

# Sort cycle order
_SORT_CYCLE = ("cpu", "mem", "count")


class ProcessSection(Static):
    """Widget showing grouped process list with sort and scroll."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sort_by: str = "cpu"
        self._scroll_offset: int = 0
        self._group_count: int = 0
        self._user_filter: str | None = None  # None = all, str = filter to this user

    def set_sort(self, sort_by: str) -> None:
        """Set sort column: 'cpu', 'mem', or 'count'."""
        self._sort_by = sort_by

    def cycle_sort(self) -> str:
        """Cycle sort order and return new sort."""
        idx = _SORT_CYCLE.index(self._sort_by) if self._sort_by in _SORT_CYCLE else 0
        self._sort_by = _SORT_CYCLE[(idx + 1) % len(_SORT_CYCLE)]
        return self._sort_by

    def toggle_user_filter(self, current_user: str) -> bool:
        """Toggle between all processes and current-user-only. Returns True if filter is now active."""
        if self._user_filter is None:
            self._user_filter = current_user
            return True
        else:
            self._user_filter = None
            return False

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
        # Apply user filter
        if self._user_filter is not None:
            groups = [g for g in groups if g.user == self._user_filter]

        self._group_count = len(groups)
        if not groups:
            self.update("")
            return

        # Sort
        if self._sort_by == "mem":
            groups = sorted(groups, key=lambda g: g.mem_bytes, reverse=True)
        elif self._sort_by == "count":
            groups = sorted(groups, key=lambda g: g.proc_count, reverse=True)
        else:
            groups = sorted(groups, key=lambda g: g.cpu_pct, reverse=True)

        NAME_WIDTH = 32
        USER_WIDTH = 8
        PROCS_WIDTH = 6
        CPU_WIDTH = 6
        MEMPCT_WIDTH = 5
        MEM_WIDTH = 7

        proc_count_color = getattr(theme, "proc_count", "#4dd0e1")
        sort_active = getattr(theme, "proc_sort_active", "bold")
        header_color = getattr(theme, "proc_count", "#4dd0e1")

        # Active sort column gets brackets
        h_procs = "[#Procs]" if self._sort_by == "count" else "#Procs"
        h_cpu   = "[Cpu%]"   if self._sort_by == "cpu"   else "Cpu%"
        h_mem   = "[Mem%]"   if self._sort_by == "mem"   else "Mem%"

        text = Text()
        # Filter indicator in header
        filter_indicator = " [user]" if self._user_filter is not None else ""
        text.append(("Command" + filter_indicator).ljust(NAME_WIDTH), style=header_color)
        text.append(" ")
        text.append("User".ljust(USER_WIDTH), style=header_color)
        text.append(" ")
        text.append(h_procs.rjust(PROCS_WIDTH), style=sort_active if self._sort_by == "count" else header_color)
        text.append(" ")
        text.append(h_cpu.rjust(CPU_WIDTH), style=sort_active if self._sort_by == "cpu" else header_color)
        text.append(" ")
        text.append(h_mem.rjust(MEMPCT_WIDTH), style=sort_active if self._sort_by == "mem" else header_color)
        text.append(" ")
        text.append("MemB".rjust(MEM_WIDTH) + "\n", style=header_color)

        # Apply scroll
        max_offset = max(0, len(groups) - visible_rows)
        self._scroll_offset = min(self._scroll_offset, max_offset)
        start = self._scroll_offset
        end = min(start + visible_rows, len(groups))
        visible = groups[start:end]

        for g in visible:
            display_name = (g.name or "[other]").strip() or "[other]"
            is_meta = display_name == "user services" or display_name.startswith("other (")
            name_style = "italic dim" if is_meta else ""
            name = (display_name[: NAME_WIDTH - 1] + "…" if len(display_name) > NAME_WIDTH else display_name).ljust(NAME_WIDTH)
            user_str = (g.user or "")[:USER_WIDTH].ljust(USER_WIDTH)
            procs_str = str(g.proc_count).rjust(PROCS_WIDTH)
            cpu_str = f"{g.cpu_pct:5.1f}".rjust(CPU_WIDTH)
            mempct_str = f"{g.mem_pct:4.1f}".rjust(MEMPCT_WIDTH)
            mem_str = bytes_to_human(g.mem_bytes).rjust(MEM_WIDTH)
            text.append(name, style=name_style)
            text.append(" ")
            text.append(user_str, style="dim")
            text.append(" ")
            text.append(procs_str, style=proc_count_color)
            text.append(" ")
            text.append(cpu_str)
            text.append(" ")
            text.append(mempct_str)
            text.append(" ")
            text.append(mem_str + "\n")

        self.update(text)
