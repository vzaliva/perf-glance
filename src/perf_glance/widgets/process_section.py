"""Process list section widget with grouping and hierarchical expansion."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from perf_glance.grouping.process_groups import ProcessGroup, proc_label
from perf_glance.utils.humanize import bytes_to_human

_STATE_PATH = Path.home() / ".config" / "perf-glance" / "state.json"

# Sort cycle order
_SORT_CYCLE = ("cpu", "cum", "mem", "count")
_PID_GROUP_KEY_RE = re.compile(r"\|pid:(\d+):")


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
        self._cum_by_key: dict[str, float] = {}
        self._prev_pct_by_key: dict[str, float] = {}
        self._cum_share_by_key: dict[str, float] = {}
        self._top_level_keys: set[str] = set()
        self._prev_sample_ts: float | None = None

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
        """Set sort column: 'cpu', 'mem', 'count', or 'cum'."""
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

    @staticmethod
    def _make_pid_leaves(g: ProcessGroup, display_depth: int) -> None:
        """Populate g.children with per-PID leaf nodes (in-place)."""
        for p in g.processes:
            pid_label = f"PID {p.pid}"
            exe = proc_label(p)
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
                processes=[p],
                depth=display_depth + 1,
                group_key=f"{g.group_key}|pid:{p.pid}:{getattr(p, 'starttime_ticks', 0)}",
            ))

    @staticmethod
    def _pid_from_group_key(group_key: str) -> int | None:
        """Extract PID from per-PID leaf group_key suffix."""
        m = _PID_GROUP_KEY_RE.search(group_key or "")
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def selected_pids(self, kill_group: bool = False) -> list[int]:
        """Return PIDs targeted by current selection.

        kill_group=False: one PID only (selected row must represent one process)
        kill_group=True: all processes represented by selected row
        """
        if not self._flat_rows or self._cursor_index < 0 or self._cursor_index >= len(self._flat_rows):
            return []
        g, _ = self._flat_rows[self._cursor_index]
        pids: list[int] = []
        procs = g.processes or []
        if kill_group:
            def collect_recursive(node: ProcessGroup) -> None:
                for p in (node.processes or []):
                    pid_val = getattr(p, "pid", None)
                    if pid_val is not None:
                        pids.append(int(pid_val))
                pid_from_key = self._pid_from_group_key(node.group_key)
                if pid_from_key is not None:
                    pids.append(pid_from_key)
                for child in (node.children or []):
                    collect_recursive(child)

            collect_recursive(g)
        else:
            if len(procs) == 1 and getattr(procs[0], "pid", None) is not None:
                pids = [int(procs[0].pid)]
            elif not procs:
                pid = self._pid_from_group_key(g.group_key)
                if pid is not None:
                    pids = [pid]

        # Stable dedup while preserving order
        seen: set[int] = set()
        deduped: list[int] = []
        for pid in pids:
            if pid in seen:
                continue
            seen.add(pid)
            deduped.append(pid)
        return deduped

    def reset_cumulative(self) -> None:
        """Reset cumulative CPU counters and baseline."""
        self._cum_by_key.clear()
        self._prev_pct_by_key.clear()
        self._cum_share_by_key.clear()
        self._top_level_keys.clear()
        self._prev_sample_ts = None
        if self._groups and self._theme:
            self.refresh_display()

    def _update_cumulative(self, groups: list[ProcessGroup], sample_ts: float) -> None:
        """Integrate CPU% over time using a linear (trapezoid) approximation."""
        current_pct_by_key: dict[str, float] = {}
        top_level_keys: set[str] = set()

        def collect_rows(gs: list[ProcessGroup], depth: int) -> None:
            for g in gs:
                key = (g.group_key or "").strip()
                if key:
                    current_pct_by_key[key] = g.cpu_pct
                    if depth == 0:
                        top_level_keys.add(key)

                # For groups without explicit hierarchy children, track per-process
                # rows by PID+starttime so ended processes keep accumulated history.
                if not g.children and g.processes and len(g.processes) > 1 and key:
                    for p in g.processes:
                        pid_key = f"{key}|pid:{p.pid}:{getattr(p, 'starttime_ticks', 0)}"
                        current_pct_by_key[pid_key] = getattr(p, "cpu_pct", 0.0) or 0.0

                if g.children:
                    collect_rows(g.children, depth + 1)

        collect_rows(groups, 0)

        self._top_level_keys = top_level_keys
        prev_ts = self._prev_sample_ts
        if prev_ts is None:
            self._prev_pct_by_key = current_pct_by_key
            self._prev_sample_ts = sample_ts
            self._recompute_cum_shares()
            return

        dt = sample_ts - prev_ts
        if dt > 0:
            all_keys = set(self._prev_pct_by_key) | set(current_pct_by_key)
            for key in all_keys:
                prev_pct = self._prev_pct_by_key.get(key, 0.0)
                curr_pct = current_pct_by_key.get(key, 0.0)
                self._cum_by_key[key] = self._cum_by_key.get(key, 0.0) + ((prev_pct + curr_pct) * 0.5 * dt)

        self._prev_pct_by_key = current_pct_by_key
        self._prev_sample_ts = sample_ts
        self._recompute_cum_shares()

    def _recompute_cum_shares(self) -> None:
        """Recompute cumulative percentages normalized by top-level totals."""
        denom = sum(max(0.0, self._cum_by_key.get(k, 0.0)) for k in self._top_level_keys)
        if denom <= 0:
            self._cum_share_by_key = {}
            return
        keys = {k for g, _ in self._flat_rows for k in [(g.group_key or "").strip()] if k}
        self._cum_share_by_key = {
            k: max(0.0, 100.0 * self._cum_by_key.get(k, 0.0) / denom)
            for k in keys
        }

    def _apply_expanded_state(self, groups: list[ProcessGroup]) -> None:
        """Restore expanded state from _expanded_state."""
        def walk(gs: list[ProcessGroup], depth: int) -> None:
            for g in gs:
                key = (g.name.lower(), g.user or "")
                if key in self._expanded_state:
                    # Recreate on-demand per-PID leaves if the group was
                    # expanded without pre-built children (e.g. lean-lsp-mcp (2))
                    if not g.children and g.processes and len(g.processes) > 1:
                        self._make_pid_leaves(g, depth)
                    if g.children:
                        g.expanded = True
                if g.children:
                    walk(g.children, depth + 1)
        walk(groups, 0)

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

    def _get_visible_rows(self) -> int:
        """Get actual visible rows from widget size, falling back to stored value."""
        h = getattr(self.size, "height", 0) or 0
        if h > 2:
            return h - 1  # subtract header row
        return self._visible_rows

    def _scroll_to_cursor(self) -> None:
        """Adjust scroll so cursor stays visible."""
        vr = self._get_visible_rows()
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
            self._make_pid_leaves(g, depth)
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

    def selected_row(self) -> tuple[ProcessGroup, int] | None:
        """Return currently selected flattened row."""
        if not self._flat_rows or self._cursor_index < 0 or self._cursor_index >= len(self._flat_rows):
            return None
        return self._flat_rows[self._cursor_index]

    def selected_individual_process(self) -> object | None:
        """Return selected process object for popup.

        Uses recursive PID collection (same logic as group-kill) and only
        returns a process when exactly one PID is associated with the row.
        """
        row = self.selected_row()
        if row is None:
            return None
        g, _ = row
        pids = self.selected_pids(kill_group=True)
        if len(pids) != 1:
            return None
        target_pid = pids[0]

        def find_proc(node: ProcessGroup) -> object | None:
            for p in (node.processes or []):
                if getattr(p, "pid", None) == target_pid:
                    return p
            for child in (node.children or []):
                found = find_proc(child)
                if found is not None:
                    return found
            return None

        found = find_proc(g)
        if found is not None:
            return found

        # Fallback: selected row itself may be a synthetic PID leaf without
        # attached process object.
        if "|pid:" in (g.group_key or ""):
            pid = self._pid_from_group_key(g.group_key)
            if pid == target_pid:
                return None
        return None

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
        sample_ts: float | None = None,
        update_cumulative: bool = True,
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
        elif self._sort_by == "cum":
            groups = sorted(groups, key=lambda g: self._cum_share_by_key.get(g.group_key, 0.0), reverse=True)
        else:
            groups = sorted(groups, key=lambda g: g.cpu_pct, reverse=True)

        self._groups = groups
        self._theme = theme
        self._visible_rows = visible_rows
        self._apply_expanded_state(groups)
        self._flat_rows = _flatten_groups(groups, self._text_filter)
        if update_cumulative:
            self._update_cumulative(groups, sample_ts if sample_ts is not None else time.monotonic())
        else:
            self._recompute_cum_shares()

        actual_vr = self._get_visible_rows()
        max_offset = max(0, len(self._flat_rows) - actual_vr)
        self._scroll_offset = min(self._scroll_offset, max_offset)
        self._cursor_index = min(self._cursor_index, max(0, len(self._flat_rows) - 1))
        self._scroll_to_cursor()

        self._repaint(theme)

    def _repaint(self, theme: object) -> None:
        """Render process list to Text and update widget."""
        if not self._groups:
            return
        visible_rows = self._get_visible_rows()
        USER_WIDTH = 8
        PROCS_WIDTH = 6
        CPU_WIDTH = 6
        CUMCPU_WIDTH = 6
        MEMPCT_WIDTH = 5
        MEM_WIDTH = 7
        # Command column: fills remaining space after fixed columns, clamped 20..64
        fixed_width = USER_WIDTH + PROCS_WIDTH + CPU_WIDTH + CUMCPU_WIDTH + MEMPCT_WIDTH + MEM_WIDTH + 6  # 6 spaces between columns
        content_width = getattr(self.size, "width", 0) or 80
        NAME_WIDTH = min(64, max(20, content_width - fixed_width))

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
        hdr("Cum%", self._sort_by == "cum", CUMCPU_WIDTH)
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
            cumcpu = self._cum_share_by_key.get(g.group_key, 0.0) if g.group_key else 0.0
            cumcpu_str = f"{cumcpu:5.1f}".rjust(CUMCPU_WIDTH)
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
            text.append(cumcpu_str, style="reverse" if is_selected else None)
            text.append(" ")
            text.append(mempct_str, style="reverse" if is_selected else None)
            text.append(" ")
            text.append(mem_str + "\n", style="reverse" if is_selected else None)

        self.update(text)
