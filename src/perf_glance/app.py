"""Main Textual app for perf-glance."""

from __future__ import annotations

import pwd
import os
import time

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual.widgets import Footer, Input, Static

from perf_glance.collectors import (
    CPUSnapshot,
    get_aggregate_cpu_times,
    read_cpu,
    read_memory,
    read_processes,
    read_temperature,
)
from perf_glance.config import Config, load_config
from perf_glance.grouping import group_processes
from perf_glance.grouping.desktop_entries import scan_desktop_entries
from perf_glance.widgets import CPUSection, MemorySection, ProcessSection


class PerfGlanceApp(App):
    """Main TUI application."""

    CSS_PATH = "perf_glance.css"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit", "quit", key_display="q"),
        Binding("s", "sort", "sort", key_display="s"),
        Binding("u", "toggle_user_filter", "user", key_display="u"),
        Binding("enter", "expand", "expand", key_display="↵"),
        Binding("/", "filter", "filter", key_display="/"),
        Binding("0", "reset_cumulative", "reset", key_display="0"),
        Binding("?", "help", "help", key_display="?"),
        # Hidden — still active, not shown in footer
        Binding("r", "refresh", "refresh", show=False),
        Binding("+", "interval_up", "+", show=False),
        Binding("-", "interval_down", "-", show=False),
        Binding("up", "scroll_up", "↑", show=False),
        Binding("down", "scroll_down", "↓", show=False),
        Binding("right", "expand", "expand", show=False),
        Binding("left", "collapse", "collapse", show=False),
        Binding("backspace", "collapse", "collapse", show=False),
        Binding("escape", "clear_filter", "clear", show=False),
    ]

    def __init__(self, config: Config | None = None, iterations: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self._config = config or load_config()
        self._iterations = iterations
        self._iteration_count = 0
        self._cpu_snapshot: CPUSnapshot | None = None
        self._prev_cpu_total = 0.0
        self._prev_per_pid: dict[int, tuple[int, int]] | None = None
        self._interval_timer: object | None = None  # Timer from set_interval
        self._exe_to_app: dict[str, str] = {}
        self._last_sample_ts: float | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield CPUSection(id="cpu")
            yield MemorySection(id="memory")
            with Container(id="process-container"):
                yield ProcessSection(id="processes")
                yield Input(placeholder="Filter...", id="process-filter", disabled=True)
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        dirs = getattr(self._config.grouping, "desktop_dirs", []) or []
        self._exe_to_app = scan_desktop_entries(dirs) if dirs else {}
        # Collect baseline for delta-based metrics (CPU% and process CPU%
        # both require two reads with a time gap to compute deltas).
        self._cpu_snapshot = read_cpu(None)
        self._prev_cpu_total = get_aggregate_cpu_times()
        _, self._prev_per_pid = read_processes(0.0, self._prev_cpu_total, None)
        # Short delay so CPU ticks accumulate, then first visible refresh
        self.set_timer(0.5, self._on_first_tick)

    def _on_first_tick(self) -> None:
        """First data refresh after baseline collection."""
        self._refresh()
        self._start_interval_timer()

    def _refresh(self) -> None:
        """Gather data and update widgets. Runs on interval."""
        if self._iterations is not None and self._iteration_count >= self._iterations:
            self.exit()
            return
        self._iteration_count += 1

        cpu_snap = read_cpu(self._cpu_snapshot)
        self._cpu_snapshot = cpu_snap

        memory = read_memory()
        temp = read_temperature()

        cpu_total = get_aggregate_cpu_times()
        processes, self._prev_per_pid = read_processes(
            self._prev_cpu_total,
            cpu_total,
            self._prev_per_pid,
        )
        self._prev_cpu_total = cpu_total

        groups = group_processes(
            processes,
            memory.ram_total_bytes,
            self._config.grouping,
            self._exe_to_app,
        )

        cpu_widget = self.query_one("#cpu", CPUSection)
        mem_widget = self.query_one("#memory", MemorySection)
        proc_widget = self.query_one("#processes", ProcessSection)

        cpu_widget.update_cpu(
            cpu_snap,
            temp,
            self._config.theme,
            self._config.display.show_cpu_freq,
            self._config.display.show_cpu_temp,
        )
        mem_widget.update_memory(
            memory.ram_total_bytes,
            memory.ram_used_bytes,
            memory.ram_cached_bytes,
            memory.swap_total_bytes,
            memory.swap_used_bytes,
            memory.has_swap,
            self._config.theme,
            self._config.display.show_swap,
        )

        # Approximate visible process rows from container height
        proc_container = self.query_one("#process-container")
        visible_rows = max(5, (proc_container.size.height or 10) - 2)
        self._last_sample_ts = time.monotonic()
        proc_widget.update_processes(groups, self._config.theme, visible_rows, sample_ts=self._last_sample_ts)

    def action_refresh(self) -> None:
        """Force immediate refresh."""
        self._refresh()

    def action_interval_up(self) -> None:
        """Increase refresh interval."""
        self._config.display.refresh_interval = min(
            60,
            self._config.display.refresh_interval + 1,
        )
        self._update_interval_timer()

    def action_interval_down(self) -> None:
        """Decrease refresh interval."""
        self._config.display.refresh_interval = max(
            1,
            self._config.display.refresh_interval - 1,
        )
        self._update_interval_timer()

    def _start_interval_timer(self) -> None:
        """Start the refresh interval timer."""
        timer = self._interval_timer
        if timer is not None and hasattr(timer, "stop"):
            timer.stop()  # type: ignore[union-attr]
        interval = self._config.display.refresh_interval
        self._interval_timer = self.set_interval(interval, self._refresh)

    def _update_interval_timer(self) -> None:
        """Restart interval timer with new value."""
        self._start_interval_timer()

    def action_sort(self) -> None:
        """Cycle process sort order."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.cycle_sort()
        self._refresh()

    def action_scroll_up(self) -> None:
        """Scroll process list up."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.do_scroll_up()

    def action_scroll_down(self) -> None:
        """Move process list cursor down."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.do_scroll_down()

    def action_expand(self) -> None:
        """Expand selected process group (instant, no data refresh)."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.do_expand()

    def action_collapse(self) -> None:
        """Collapse selected process group (instant, no data refresh)."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.do_collapse()

    def action_toggle_user_filter(self) -> None:
        """Toggle between all processes and current user's processes."""
        try:
            current_user = pwd.getpwuid(os.getuid()).pw_name
        except (KeyError, OverflowError):
            current_user = os.environ.get("USER", "")
        proc_widget = self.query_one("#processes", ProcessSection)
        active = proc_widget.toggle_user_filter(current_user)
        self.notify(f"Showing {'only ' + current_user + ' processes' if active else 'all processes'}")
        self._refresh()

    def action_filter(self) -> None:
        """Show filter input."""
        filt = self.query_one("#process-filter", Input)
        filt.disabled = False
        filt.styles.display = "block"
        filt.value = self.query_one("#processes", ProcessSection)._text_filter
        filt.focus()

    def action_clear_filter(self) -> None:
        """Clear filter and hide input (instant, no data refresh)."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.clear_text_filter()
        filt = self.query_one("#process-filter", Input)
        filt.styles.display = "none"
        filt.disabled = True
        filt.value = ""
        self.set_focus(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Apply filter when user presses Enter (instant, no data refresh)."""
        if event.input.id == "process-filter":
            proc_widget = self.query_one("#processes", ProcessSection)
            proc_widget.set_text_filter(event.input.value)
            event.input.styles.display = "none"
            event.input.disabled = True
            self.set_focus(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter as user types."""
        if event.input.id == "process-filter":
            proc_widget = self.query_one("#processes", ProcessSection)
            proc_widget.set_text_filter(event.input.value)
            proc_widget.update_processes(
                proc_widget._groups,
                self._config.theme,
                max(5, (self.query_one("#process-container").size.height or 10) - 2),
                sample_ts=self._last_sample_ts,
                update_cumulative=False,
            )

    def action_reset_cumulative(self) -> None:
        """Reset cumulative process CPU counters."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.reset_cumulative()
        self.notify("Cumulative CPU counters reset")

    def action_help(self) -> None:
        """Show help."""
        self.notify("q quit  r refresh  +/- interval  s sort  u user  / filter  0 reset  ↑↓ move  enter expand  ← collapse")
