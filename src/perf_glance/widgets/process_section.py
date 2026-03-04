"""Process list section widget with grouping and hierarchical expansion."""

from __future__ import annotations

import json
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from perf_glance.grouping.process_groups import ProcessGroup
from perf_glance.utils.humanize import bytes_to_human

_STATE_PATH = Path.home() / ".config" / "perf-glance" / "state.json"

# Sort cycle order
_SORT_CYCLE = ("cpu", "mem", "count")


def _flatten_groups(
    groups: list[ProcessGroup],
    text_filter: str = "",
) -> list[tuple[ProcessGroup, int]]:
    """Flatten tree to display order (preorder, skip collapsed children)."""
    result: list[tuple[ProcessGroup, int]] = []
    filter_lower = text_filter.lower().strip() if text_filter else ""

    def walk(gs: list[ProcessGroup], depth: int) -> None:
        for g in gs:
            result.append((g, depth))
            if g.expanded and g.children:
                walk(g.children, depth + 1)

    walk(groups, 0)

    if filter_lower:
        result = [(g, d) for g, d in result if filter_lower in (g.name or "").lower() or filter_lower in (g.user or "").lower()]
    return result


class ProcessSection(Static):
    """Widget showing grouped process list with cursor, sort, and expand/collapse."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sort_by: str = "cpu"
        self._cursor_index: int = 0
        self._scroll_offset: int = 0
        self._flat_rows: list[tuple[ProcessGroup, int]] = []
        self._groups: list[ProcessGroup] = []
        self._visible_rows: int = 10
        self._user_filter: str | None = None
        self._text_filter: str = ""
        self._expanded_state: set[tuple[str, str]] = set()
        self._theme: object = None

    def refresh_display(self) -> None:
        """Re-render display from current state. Independent of data refresh."""
        if not self._groups or not self._theme:
            return
        self._repaint(self._theme)

    def _load_expanded_state(self) -> None:
        """Load expanded state from state file."""
        if not _STATE_PATH.exists():
            return
        try:
            data = json.loads(_STATE_PATH.read_text())
            expanded = data.get("expanded", [])
            self._expanded_state = {tuple(x) for x in expanded if isinstance(x, list) and len(x) == 2}
        except (OSError, json.JSONDecodeError):
            pass

    def _persist_expanded_state(self) -> None:
        """Save expanded state to state file."""
        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"expanded": [list(k) for k in self._expanded_state]}
            _STATE_PATH.write_text(json.dumps(data, indent=2))
        except OSError:
            pass

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

    def _apply_expanded_state(self, groups: list[ProcessGroup]) -> None:
        """Restore expanded state from _expanded_state."""
        def walk(gs: list[ProcessGroup]) -> None:
            for g in gs:
                key = (g.name.lower(), g.user or "")
                if key in self._expanded_state:
                    g.expanded = True
                if g.children:
                    walk(g.children)
        walk(groups)

    def _save_expanded_state(self, groups: list[ProcessGroup]) -> None:
        """Save expanded state to _expanded_state."""
        expanded: set[tuple[str, str]] = set()

        def walk(gs: list[ProcessGroup]) -> None:
            for g in gs:
                if g.expanded and g.children:
                    expanded.add((g.name.lower(), g.user or ""))
                if g.children:
                    walk(g.children)
        walk(groups)
        self._expanded_state = expanded

    def do_scroll_up(self) -> None:
        """Move cursor/selection up."""
        self._cursor_index = max(0, self._cursor_index - 1)
        self._scroll_to_cursor()
        self.refresh_display()

    def do_scroll_down(self) -> None:
        """Move cursor/selection down."""
        if not self._flat_rows:
            return
        self._cursor_index = min(len(self._flat_rows) - 1, self._cursor_index + 1)
        self._scroll_to_cursor()
        self.refresh_display()

    def _scroll_to_cursor(self) -> None:
        """Adjust scroll so cursor stays visible."""
        vr = self._visible_rows
        if self._cursor_index < self._scroll_offset:
            self._scroll_offset = self._cursor_index
        elif self._cursor_index >= self._scroll_offset + vr:
            self._scroll_offset = self._cursor_index - vr + 1

    def do_expand(self) -> bool:
        """Expand selected group. Returns True if changed."""
        if not self._flat_rows or self._cursor_index < 0 or self._cursor_index >= len(self._flat_rows):
            return False
        g, depth = self._flat_rows[self._cursor_index]
        if g.expanded:
            return False
        # If no pre-built children but has processes, create per-process leaf children
        if not g.children and g.processes and len(g.processes) > 1:
            for p in g.processes:
                pid_label = f"PID {p.pid}"
                exe = getattr(p, "exe", "") or getattr(p, "name", "") or ""
                child_name = f"{pid_label}  {exe}" if exe else pid_label
                rss = getattr(p, "rss_bytes", 0) or 0
                g.children.append(ProcessGroup(
                    name=child_name,
                    proc_count=1,
                    cpu_pct=p.cpu_pct,
                    mem_bytes=rss,
                    mem_pct=0.0,
                    user=g.user,
                    category=g.category,
                    depth=depth + 1,
                ))
        if g.children:
            g.expanded = True
            self._expanded_state.add((g.name.lower(), g.user or ""))
            self._persist_expanded_state()
            self._flat_rows = _flatten_groups(self._groups, self._text_filter)
            self.refresh_display()
            return True
        return False

    def do_collapse(self) -> bool:
        """Collapse selected group. Returns True if changed."""
        if not self._flat_rows or self._cursor_index < 0 or self._cursor_index >= len(self._flat_rows):
            return False
        g, _ = self._flat_rows[self._cursor_index]
        if g.children and g.expanded:
            g.expanded = False
            self._expanded_state.discard((g.name.lower(), g.user or ""))
            self._persist_expanded_state()
            self._flat_rows = _flatten_groups(self._groups, self._text_filter)
            self.refresh_display()
            return True
        return False

    def set_text_filter(self, s: str) -> None:
        """Set filter string; empty clears filter."""
        self._text_filter = s
        if self._groups:
            self._flat_rows = _flatten_groups(self._groups, self._text_filter)
            self._cursor_index = min(self._cursor_index, max(0, len(self._flat_rows) - 1))
            self.refresh_display()

    def append_text_filter(self, char: str) -> None:
        """Append character to filter."""
        self.set_text_filter(self._text_filter + char)

    def clear_text_filter(self) -> bool:
        """Clear filter. Returns True if filter was non-empty."""
        had = bool(self._text_filter)
        self.set_text_filter("")
        return had

    def update_processes(
        self,
        groups: list[ProcessGroup],
        theme: object,
        visible_rows: int,
    ) -> None:
        """Update display from process groups."""
        if self._user_filter is not None:
            groups = [g for g in groups if g.user == self._user_filter]

        if not groups:
            self._groups = []
            self._flat_rows = []
            self._theme = None
            self.update("")
            return

        # Sort top-level only
        if self._sort_by == "mem":
            groups = sorted(groups, key=lambda g: g.mem_bytes, reverse=True)
        elif self._sort_by == "count":
            groups = sorted(groups, key=lambda g: g.proc_count, reverse=True)
        else:
            groups = sorted(groups, key=lambda g: g.cpu_pct, reverse=True)

        self._groups = groups
        self._theme = theme
        self._visible_rows = visible_rows
        self._apply_expanded_state(groups)
        self._flat_rows = _flatten_groups(groups, self._text_filter)

        max_offset = max(0, len(self._flat_rows) - visible_rows)
        self._scroll_offset = min(self._scroll_offset, max_offset)
        self._cursor_index = min(self._cursor_index, max(0, len(self._flat_rows) - 1))
        self._scroll_to_cursor()

        self._repaint(theme)

    def _repaint(self, theme: object) -> None:
        """Render process list to Text and update widget."""
        if not self._groups:
            return
        visible_rows = self._visible_rows
        USER_WIDTH = 8
        PROCS_WIDTH = 6
        CPU_WIDTH = 6
        MEMPCT_WIDTH = 5
        MEM_WIDTH = 7
        # Command column: 32 by default, up to 64 when horizontal space allows
        fixed_width = USER_WIDTH + PROCS_WIDTH + CPU_WIDTH + MEMPCT_WIDTH + MEM_WIDTH + 5  # 5 spaces between columns
        content_width = getattr(self.size, "width", 0) or 80
        NAME_WIDTH = min(64, max(32, content_width - fixed_width))

        proc_count_color = getattr(theme, "proc_count", "#4dd0e1")
        bracket_color = "white"
        header_color = getattr(theme, "proc_count", "#4dd0e1")
        sort_style = getattr(theme, "proc_sort_active", "bold")

        def hdr(label: str, is_active: bool, w: int) -> None:
            if is_active:
                pad = max(0, w - len(label) - 2)
                text.append(" " * pad, style=header_color)
                text.append("[", style=bracket_color)
                text.append(label, style=sort_style)
                text.append("]", style=bracket_color)
            else:
                text.append(label.rjust(w), style=header_color)

        text = Text()
        filter_indicator = " [user]" if self._user_filter is not None else ""
        text.append(("Command" + filter_indicator).ljust(NAME_WIDTH), style=header_color)
        text.append(" ")
        text.append("User".ljust(USER_WIDTH), style=header_color)
        text.append(" ")
        hdr("#Procs", self._sort_by == "count", PROCS_WIDTH)
        text.append(" ")
        hdr("Cpu%", self._sort_by == "cpu", CPU_WIDTH)
        text.append(" ")
        hdr("Mem%", self._sort_by == "mem", MEMPCT_WIDTH)
        text.append(" ")
        text.append("MemB".rjust(MEM_WIDTH) + "\n", style=header_color)

        start = self._scroll_offset
        end = min(start + visible_rows, len(self._flat_rows))
        visible = self._flat_rows[start:end]

        for i, (g, depth) in enumerate(visible):
            row_idx = start + i
            is_selected = row_idx == self._cursor_index

            indent = "  " * depth
            expandable = g.children or (g.processes and len(g.processes) > 1)
            if expandable and g.expanded:
                icon = "▼ "
            elif expandable:
                icon = "▶ "
            elif depth > 0:
                icon = "· "
            else:
                icon = "  "

            display_name = (g.name or "[other]").strip() or "[other]"
            is_meta = display_name.startswith("other (")
            is_child = depth > 0
            if is_meta:
                name_style = "italic dim"
            elif is_child:
                name_style = "italic"
            else:
                name_style = ""
            if is_selected:
                name_style = (name_style + " reverse").strip() if name_style else "reverse"

            name_part = indent + icon + display_name
            name_part = (name_part[: NAME_WIDTH - 1] + "…" if len(name_part) > NAME_WIDTH else name_part).ljust(NAME_WIDTH)

            user_str = (g.user or "")[:USER_WIDTH].ljust(USER_WIDTH)
            procs_str = str(g.proc_count).rjust(PROCS_WIDTH)
            cpu_str = f"{g.cpu_pct:5.1f}".rjust(CPU_WIDTH)
            mempct_str = f"{g.mem_pct:4.1f}".rjust(MEMPCT_WIDTH)
            mem_str = bytes_to_human(g.mem_bytes).rjust(MEM_WIDTH)

            text.append(name_part, style=name_style)
            text.append(" ")
            text.append(user_str, style="dim" if not is_selected else "reverse")
            text.append(" ")
            text.append(procs_str, style=proc_count_color if not is_selected else "reverse")
            text.append(" ")
            text.append(cpu_str, style="reverse" if is_selected else None)
            text.append(" ")
            text.append(mempct_str, style="reverse" if is_selected else None)
            text.append(" ")
            text.append(mem_str + "\n", style="reverse" if is_selected else None)

        self.update(text)
