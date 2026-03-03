"""Main Textual app for perf-glance."""

from __future__ import annotations

import pwd
import os

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual.widgets import Footer, Static

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
from perf_glance.widgets import CPUSection, MemorySection, ProcessSection


class PerfGlanceApp(App):
    """Main TUI application."""

    CSS_PATH = "perf_glance.css"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit", "quit"),
        Binding("r", "refresh", "refresh"),
        Binding("+", "interval_up", "interval +"),
        Binding("-", "interval_down", "interval -"),
        Binding("s", "sort", "sort"),
        Binding("u", "toggle_user_filter", "user filter"),
        Binding("up", "scroll_up", "scroll up"),
        Binding("down", "scroll_down", "scroll down"),
        Binding("?", "help", "help"),
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

    def compose(self) -> ComposeResult:
        with Vertical():
            yield CPUSection(id="cpu")
            yield MemorySection(id="memory")
            with Container(id="process-container"):
                yield ProcessSection(id="processes")
        yield Footer()

    def on_mount(self) -> None:
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
            self._config.grouping.force_name_group,
            self._config.grouping.generic_parents,
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
        proc_widget.update_processes(groups, self._config.theme, visible_rows)

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
        """Scroll process list down."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc_widget.do_scroll_down()

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

    def action_help(self) -> None:
        """Show help (not yet implemented)."""
        self.notify("Keybindings: q quit  r refresh  +/- interval  s sort  u user filter  ↑↓ scroll")
