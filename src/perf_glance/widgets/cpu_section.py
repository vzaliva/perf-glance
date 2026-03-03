"""CPU utilization section widget."""

from __future__ import annotations

from collections import deque

from rich.text import Text
from textual.widgets import Static

from perf_glance.collectors.cpu import CPUSnapshot
from perf_glance.utils.graph_render import render_line_graph


BAR_WIDTH = 20
FILLED = "█"
EMPTY = "░"
# Fixed width per CPU column: " XX " + "[...]" + " XXX.X%"
COL_WIDTH = 4 + 2 + BAR_WIDTH + 2 + 7  # ~35 chars


def _cpu_color(pct: float, theme: object) -> str:
    """Return theme color for CPU percentage."""
    cpu_low = getattr(theme, "cpu_low", "white")
    cpu_mid = getattr(theme, "cpu_mid", "white")
    cpu_high = getattr(theme, "cpu_high", "white")
    if pct < 50:
        return cpu_low
    if pct < 80:
        return cpu_mid
    return cpu_high


def _temp_color(temp: float, theme: object) -> str:
    """Return theme color for temperature."""
    temp_low = getattr(theme, "temp_low", "white")
    temp_mid = getattr(theme, "temp_mid", "white")
    temp_high = getattr(theme, "temp_high", "white")
    if temp <= 70:
        return temp_low
    if temp <= 85:
        return temp_mid
    return temp_high


class CPUSection(Static):
    """Widget showing CPU utilization, frequency, temperature, and history graph."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history: deque[float] = deque(maxlen=150)

    def update_cpu(
        self,
        snapshot: CPUSnapshot,
        temp: float | None,
        theme: object,
        show_freq: bool,
        show_temp: bool,
    ) -> None:
        """Update display from CPU snapshot and temperature."""
        text = Text()

        # Header
        header_color = getattr(theme, "cpu_graph", "#00bcd4")
        text.append("CPU", style=header_color)
        if show_freq and snapshot.frequency_ghz is not None:
            text.append(f" {snapshot.frequency_ghz:.1f}GHz")
        if show_temp and temp is not None:
            text.append("  ")
            text.append(f"Temp: {temp:.0f}°C", style=_temp_color(temp, theme))
        text.append("\n")

        # Per-core bars in two columns with fixed width per column
        per_core = snapshot.per_core_pct
        if per_core:
            half = (len(per_core) + 1) // 2
            for row in range(half):
                line_parts = []
                for col in [0, 1]:
                    idx = row + col * half
                    if idx < len(per_core):
                        pct = per_core[idx]
                        filled = min(int(BAR_WIDTH * pct / 100 + 0.5), BAR_WIDTH)
                        color = _cpu_color(pct, theme)
                        cell = (
                            f"  {idx:2} "
                            f"[{FILLED * filled}{EMPTY * (BAR_WIDTH - filled)}]"
                            f" {pct:5.1f}%"
                        )
                        line_parts.append((cell, color))
                    else:
                        line_parts.append((" " * COL_WIDTH, "dim"))
                for i, (cell, style) in enumerate(line_parts):
                    text.append(cell.ljust(COL_WIDTH), style=style)
                    if i == 0 and len(line_parts) == 2:
                        text.append("  ", style="dim")
                text.append("\n")

        # History graph: scrolls right-to-left, newest sample at right edge
        self._history.append(snapshot.aggregate_pct)
        width = self.size.width if self.size else 80
        graph_width = max(40, min(width - 6, len(self._history)))
        # Take most recent samples; render left=oldest, right=newest
        samples = list(self._history)[-graph_width:]
        graph_str = render_line_graph(
            samples,
            width=graph_width,
            height=4,
            use_braille=False,
            use_unicode=True,
        )
        if graph_str:
            graph_color = getattr(theme, "cpu_graph", "#00bcd4")
            text.append("\n")
            for line in graph_str.splitlines():
                text.append(line + "\n", style=graph_color)
            # X-axis baseline: older ← ──── → newer
            baseline = "─" * graph_width
            text.append(baseline + "\n", style="dim")

        self.update(text)
