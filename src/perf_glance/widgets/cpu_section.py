"""CPU utilization section widget."""

from __future__ import annotations

from collections import deque

from rich.text import Text
from textual.widgets import Static

from perf_glance.collectors.cpu import CPUSnapshot

# Eighth-block chars: index 1–8 = ▁▂▃▄▅▆▇█
_BLOCKS = " ▁▂▃▄▅▆▇█"
# Lower one-eighth block used as dim baseline in per-core charts
_BASELINE = "▁"

# Braille dot bit masks per column, ordered bottom→top (4 dot rows per char)
# Left column:  dot7=0x40, dot3=0x04, dot2=0x02, dot1=0x01
# Right column: dot8=0x80, dot6=0x20, dot5=0x10, dot4=0x08
_BRAILLE_L = (0x40, 0x04, 0x02, 0x01)  # di=0 is bottom dot, di=3 is top
_BRAILLE_R = (0x80, 0x20, 0x10, 0x08)

# Per-core right-panel layout per column: "C00 " + chart + " 100%"
_LABEL_W = 4   # "C00 "
_PCT_W   = 5   # " 100%"
_GAP_W   = 2   # space between the two core columns
# Fraction of terminal width given to the left aggregate graph
_GRAPH_FRAC = 0.52


def _cpu_color(pct: float, theme: object) -> str:
    if pct < 50:
        return getattr(theme, "cpu_low", "white")
    if pct < 80:
        return getattr(theme, "cpu_mid", "white")
    return getattr(theme, "cpu_high", "white")


def _temp_color(temp: float, theme: object) -> str:
    if temp <= 70:
        return getattr(theme, "temp_low", "white")
    if temp <= 85:
        return getattr(theme, "temp_mid", "white")
    return getattr(theme, "temp_high", "white")


def _braille_graph_lines(
    values: list[float], width: int, height: int, theme: object
) -> list[Text]:
    """Render a symmetric center-axis braille graph (btop style).

    The graph is split into top half and bottom half around a center axis.
    Dots grow outward from the axis continuously in both directions.

    Top half: dots fill from the BOTTOM of each char (axis side) upward.
    Bottom half: dots fill from the TOP of each char (axis side) downward.

    Resolution per side = half * 4 dot-rows, so 100% fills all the way to
    the top/bottom border.

    Each column is colored based on its current CPU value (green/yellow/red).
    The axis row shows a single "─" on the left edge only (not full-width).
    """
    half = max(1, height // 2)
    max_dots = half * 4  # dot-rows of resolution per side

    n_samples = width * 2
    raw: list[float] = values[-n_samples:] if len(values) >= n_samples else list(values)
    if len(raw) < n_samples:
        raw = [0.0] * (n_samples - len(raw)) + raw

    lines: list[Text] = []
    for row in range(height):
        is_top = row < half
        # Distance (in rows) from this terminal row to the axis row
        r_from_axis = (half - 1 - row) if is_top else (row - half)
        is_axis_row = is_top and r_from_axis == 0  # row just above the axis gap

        line = Text()
        for col in range(width):
            v_l = raw[col * 2]
            v_r = raw[col * 2 + 1]
            n_l = round(v_l / 100.0 * max_dots)
            n_r = round(v_r / 100.0 * max_dots)

            bits = 0
            for di in range(4):
                if is_top:
                    # axis-distance of dot di: bottom dot (di=0) is closest to axis
                    ad = 4 * r_from_axis + di + 1
                else:
                    # axis-distance of dot di: top dot (di=3) is closest to axis
                    ad = 4 * r_from_axis + (3 - di) + 1
                if ad <= n_l:
                    bits |= _BRAILLE_L[di]
                if ad <= n_r:
                    bits |= _BRAILLE_R[di]

            if bits == 0:
                # Axis indicator: single "─" at left edge only
                if is_axis_row and col == 0:
                    line.append("─", style="dim")
                else:
                    line.append(" ")
            else:
                color = _cpu_color(max(v_l, v_r), theme)
                line.append(chr(0x2800 + bits), style=color)
        lines.append(line)
    return lines


def _mini_chart_segments(
    history: list[tuple[float, str]], width: int
) -> list[tuple[str, str | None]]:
    """Return (char, color) pairs for a 1-char-high per-core history.

    color is None for baseline chars (rendered dim).
    Colors come from the stored snapshot so past spikes retain their color.
    """
    n = len(history)
    if n >= width:
        samples: list[tuple[float, str]] = list(history[-width:])
    else:
        samples = [(0.0, "")] * (width - n) + list(history)
    result: list[tuple[str, str | None]] = []
    for v, color in samples:
        idx = min(int(v / 100 * 8 + 0.5), 8)
        if idx == 0:
            result.append((_BASELINE, None))
        else:
            result.append((_BLOCKS[idx], color))
    return result


class CPUSection(Static):
    """CPU section: aggregate scrolling graph on the left, per-core charts on the right."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._agg_history: deque[float] = deque(maxlen=600)
        self._core_history: list[deque[tuple[float, str]]] = []

    def update_cpu(
        self,
        snapshot: CPUSnapshot,
        temp: float | None,
        theme: object,
        show_freq: bool,
        show_temp: bool,
    ) -> None:
        per_core = snapshot.per_core_pct
        n_cores = len(per_core)

        while len(self._core_history) < n_cores:
            self._core_history.append(deque(maxlen=300))
        for i, pct in enumerate(per_core):
            self._core_history[i].append((pct, _cpu_color(pct, theme)))
        self._agg_history.append(snapshot.aggregate_pct)

        text = Text()
        term_w = self.size.width if self.size and self.size.width > 0 else 80
        graph_color = getattr(theme, "cpu_graph", "#00bcd4")

        # ── Header (full width) ───────────────────────────────────────────────
        # Build left portion as plain string first to measure its length
        left_plain = "CPU"
        if show_freq and snapshot.frequency_ghz is not None:
            left_plain += f"  {snapshot.frequency_ghz:.1f}GHz"
        left_plain += f"  {snapshot.aggregate_pct:.0f}%"

        right_plain = ""
        if show_temp and temp is not None:
            right_plain = f"Temp: {temp:.0f}°C"

        gap = max(2, term_w - len(left_plain) - len(right_plain))

        text.append("CPU", style=graph_color)
        if show_freq and snapshot.frequency_ghz is not None:
            text.append(f"  {snapshot.frequency_ghz:.1f}GHz")
        text.append(f"  {snapshot.aggregate_pct:.0f}%")
        if right_plain:
            text.append(" " * gap)
            text.append(right_plain, style=_temp_color(temp, theme))  # type: ignore[arg-type]
        text.append("\n")

        if not n_cores:
            self.update(text)
            return

        # ── Layout ────────────────────────────────────────────────────────────
        n_rows = max(2, (n_cores + 1) // 2)  # rows of per-core display
        if n_rows % 2:                        # must be even for symmetric axis
            n_rows += 1
        graph_w = max(20, int(term_w * _GRAPH_FRAC))
        sep_w = 2                             # " │"
        cores_w = term_w - graph_w - sep_w
        # Each core column: LABEL + chart + PCT; two columns + GAP
        core_chart_w = max(6, (cores_w - 2 * _LABEL_W - 2 * _PCT_W - _GAP_W) // 2)

        # ── Aggregate braille graph rows ───────────────────────────────────────
        g_lines = _braille_graph_lines(list(self._agg_history), graph_w, n_rows, theme)

        # ── Per-core rows ─────────────────────────────────────────────────────
        half = n_rows
        c_lines: list[Text] = []
        for row in range(half):
            line = Text()
            for col in range(2):
                idx = row + col * half
                if col == 1:
                    line.append(" " * _GAP_W)
                if idx >= n_cores:
                    line.append(" " * (_LABEL_W + core_chart_w + _PCT_W))
                    continue
                pct = per_core[idx]
                history = list(self._core_history[idx])
                segments = _mini_chart_segments(history, core_chart_w)
                line.append(f"C{idx:<2} ", style="dim")
                for char, seg_color in segments:
                    line.append(char, style="dim" if seg_color is None else seg_color)
                line.append(f" {pct:3.0f}%", style=_cpu_color(pct, theme))
            c_lines.append(line)

        # ── Combine side by side ──────────────────────────────────────────────
        for i in range(n_rows):
            g = g_lines[i] if i < len(g_lines) else Text(" " * graph_w)
            c = c_lines[i] if i < len(c_lines) else Text()
            text.append_text(g)
            text.append(" │", style="dim")
            text.append_text(c)
            text.append("\n")

        # Baseline under the graph
        text.append("─" * graph_w, style="dim")
        text.append("─┘", style="dim")
        text.append("\n")

        self.update(text)
