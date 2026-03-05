"""Main Textual app for perf-glance."""

from __future__ import annotations

import pwd
import os
import signal
import time
from pathlib import Path
from typing import cast

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual.screen import ModalScreen
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
import sys

from perf_glance.grouping.app_bundles import update_bundle_map
from perf_glance.grouping.desktop_entries import scan_desktop_entries
from perf_glance.widgets import CPUSection, MemorySection, ProcessSection


class ProcessInfoScreen(ModalScreen[None]):
    """Popup screen with details for one selected process."""

    BINDINGS = [
        Binding("escape", "close", "close", key_display="esc"),
        Binding("k", "kill", "kill", key_display="k"),
        Binding("K", "kill9", "kill-9", key_display="K"),
    ]

    def __init__(self, title: str, body: str):
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self._title, id="proc-popup-title"),
            Static(self._body, id="proc-popup-body"),
            Static("ESC close   k SIGTERM   K SIGKILL", id="proc-popup-hint"),
            id="proc-popup",
        )

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_kill(self) -> None:
        app = cast("PerfGlanceApp", self.app)
        app.action_kill()
        app.pop_screen()

    def action_kill9(self) -> None:
        app = cast("PerfGlanceApp", self.app)
        app.action_kill9()
        app.pop_screen()


class PerfGlanceApp(App):
    """Main TUI application."""

    CSS_PATH = "perf_glance.css"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit", "quit", key_display="q"),
        Binding("s", "sort", "sort", key_display="s"),
        Binding("u", "toggle_user_filter", "user", key_display="u"),
        Binding("enter", "inspect", "info", key_display="↵"),
        Binding("/", "filter", "filter", key_display="/"),
        Binding("0", "reset_cumulative", "reset", key_display="0"),
        Binding("k", "kill", "kill", key_display="k"),
        Binding("K", "kill9", "kill-9", key_display="K"),
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
        if sys.platform != "darwin":
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
        if sys.platform == "darwin":
            update_bundle_map(processes, self._exe_to_app)

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

    def action_inspect(self) -> None:
        """Open process info popup for the selected row's representative PID."""
        proc_widget = self.query_one("#processes", ProcessSection)
        proc = proc_widget.selected_individual_process()
        if proc is None:
            return
        pid = int(getattr(proc, "pid", 0) or 0)
        title = f"Process {pid}  {getattr(proc, 'exe', '') or getattr(proc, 'name', '') or ''}".strip()
        body = self._process_popup_body(proc)
        self.push_screen(ProcessInfoScreen(title, body))

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
        self.notify("q quit  r refresh  +/- interval  s sort  u user  / filter  0 reset  k kill  K kill-9  ↑↓ move  enter info  → expand  ← collapse")

    @staticmethod
    def _read_status_map(pid: int) -> dict[str, str]:
        """Read /proc/<pid>/status key-value fields."""
        out: dict[str, str] = {}
        path = Path(f"/proc/{pid}/status")
        if not path.exists():
            return out
        try:
            for line in path.read_text().splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
        except OSError:
            return out
        return out

    @staticmethod
    def _resolve_exe_path(pid: int) -> str:
        """Resolve executable symlink for pid."""
        try:
            return str(Path(f"/proc/{pid}/exe").resolve())
        except (OSError, RuntimeError):
            return ""

    @staticmethod
    def _resolve_cwd_path(pid: int) -> str:
        """Resolve current working directory symlink for pid."""
        try:
            return str(Path(f"/proc/{pid}/cwd").resolve())
        except (OSError, RuntimeError):
            return ""

    @staticmethod
    def _read_uptime_seconds() -> float | None:
        """Read system uptime seconds from /proc/uptime."""
        path = Path("/proc/uptime")
        try:
            first = path.read_text().split()[0]
            return float(first)
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds as compact human duration."""
        total = max(0, int(seconds))
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {mins}m"
        if mins:
            return f"{mins}m {secs}s"
        return f"{secs}s"

    @classmethod
    def _process_age(cls, start_ticks: int) -> str:
        """Compute process age from start ticks since boot."""
        if start_ticks <= 0:
            return "?"
        uptime = cls._read_uptime_seconds()
        if uptime is None:
            return "?"
        try:
            hz = os.sysconf("SC_CLK_TCK")
            hz_val = float(hz)
        except (AttributeError, ValueError, OSError, TypeError):
            return "?"
        if hz_val <= 0:
            return "?"
        started_at = float(start_ticks) / hz_val
        age = uptime - started_at
        if age < 0:
            return "?"
        return cls._format_duration(age)

    def _process_popup_body(self, proc: object) -> str:
        """Build popup body text for one process."""
        from perf_glance.utils.humanize import bytes_to_human

        pid = int(getattr(proc, "pid", 0) or 0)
        ppid = int(getattr(proc, "ppid", 0) or 0)
        uid = int(getattr(proc, "uid", 0) or 0)
        try:
            user = pwd.getpwuid(uid).pw_name
        except (KeyError, OverflowError):
            user = str(uid)

        status = self._read_status_map(pid)
        exe = str(getattr(proc, "exe", "") or getattr(proc, "name", "") or "")
        exe_path = self._resolve_exe_path(pid)
        cwd_path = self._resolve_cwd_path(pid)
        cmdline = str(getattr(proc, "cmdline", "") or "")
        state = status.get("State", "")
        threads = status.get("Threads", "")
        cpu_pct = float(getattr(proc, "cpu_pct", 0.0) or 0.0)
        rss = int(getattr(proc, "rss_bytes", 0) or 0)
        start_ticks = int(getattr(proc, "starttime_ticks", 0) or 0)
        age = self._process_age(start_ticks)

        lines = [
            f"PID: {pid}    PPID: {ppid}    User: {user} ({uid})",
            f"Exe: {exe}",
            f"Path: {exe_path or '[unavailable]'}",
            f"Workdir: {cwd_path or '[unavailable]'}",
            f"CPU%: {cpu_pct:.1f}    Mem: {bytes_to_human(rss)}    Threads: {threads or '?'}",
            f"State: {state or '?'}    Age: {age}",
            "",
            "Command line:",
            cmdline or "[empty]",
        ]
        return "\n".join(lines)

    def _kill_selected(self, sig: int, kill_group: bool) -> None:
        """Send signal to selected process or selected row's whole group."""
        proc_widget = self.query_one("#processes", ProcessSection)
        pids = proc_widget.selected_pids(kill_group=kill_group)
        # If SIGTERM is requested on a non-leaf row, fall back to killing the
        # full selected group tree recursively.
        if not pids and not kill_group:
            pids = proc_widget.selected_pids(kill_group=True)
        if not pids:
            self.notify("No process PIDs found for selected row/group")
            return

        ok = 0
        denied = 0
        missing = 0
        failed = 0
        for pid in pids:
            try:
                os.kill(pid, sig)
                ok += 1
            except ProcessLookupError:
                missing += 1
            except PermissionError:
                denied += 1
            except OSError:
                failed += 1

        parts: list[str] = []
        if ok:
            parts.append(f"signaled {ok}")
        if missing:
            parts.append(f"missing {missing}")
        if denied:
            parts.append(f"denied {denied}")
        if failed:
            parts.append(f"failed {failed}")
        signal_name = "SIGKILL" if sig == signal.SIGKILL else "SIGTERM"
        self.notify(f"{signal_name}: " + ", ".join(parts))
        if ok:
            self._refresh()

    def action_kill(self) -> None:
        """Kill selected process (SIGTERM)."""
        self._kill_selected(signal.SIGTERM, kill_group=False)

    def action_kill9(self) -> None:
        """Kill selected group (SIGKILL)."""
        self._kill_selected(signal.SIGKILL, kill_group=True)
