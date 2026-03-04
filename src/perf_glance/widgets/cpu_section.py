"""CPU utilization section widget."""

from __future__ import annotations

from collections import deque

from rich.text import Text
from textual.widgets import Static

from perf_glance.collectors.cpu import CPUSnapshot

# Btop-style braille symbols: each char encodes two values (prev, curr) as 0-4 each.
# Index = prev*5 + curr. "braille_up" fills from bottom, "braille_down" from top.
# Index 6 = graph_bg: light grey baseline for empty/low cells (btop's inactive_fg).
# From https://github.com/aristocratos/btop
_BRAILLE_UP = (
    " ", "⢀", "⢠", "⢰", "⢸",
    "⡀", "⣀", "⣠", "⣰", "⣸",
    "⡄", "⣄", "⣤", "⣴", "⣼",
    "⡆", "⣆", "⣦", "⣶", "⣾",
    "⡇", "⣇", "⣧", "⣷", "⣿",
)
_BRAILLE_DOWN = (
    " ", "⠈", "⠘", "⠸", "⢸",
    "⠁", "⠉", "⠙", "⠹", "⢹",
    "⠃", "⠋", "⠛", "⠻", "⢻",
    "⠇", "⠏", "⠟", "⠿", "⢿",
    "⡇", "⡏", "⡟", "⡿", "⣿",
)

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


def _quantize_to_level(value: float, cur_high: float, cur_low: float, mod: float) -> int:
    """Map value to 0-4 level for btop braille symbol lookup (same as btop's Graph::_create)."""
    clamp_min = 0
    if value >= cur_high:
        return 4
    if value <= cur_low:
        return clamp_min
    r = cur_high - cur_low
    if r <= 0:
        return clamp_min
    return min(4, max(0, int(round((value - cur_low) * 4 / r + mod))))


def _braille_graph_lines(
    values: list[float], width: int, height: int, theme: object
) -> list[Text]:
    """Render aggregate CPU graph using btop-style braille (5x5 symbol table).

    Symmetric layout: top half uses braille_up (fills from axis upward), bottom
    half uses braille_down (fills from axis downward). Each braille char encodes
    two consecutive samples (prev, curr) as 0-4 each. Color from max(prev,curr).
    """
    half = max(1, height // 2)
    mod = 0.1
    n_samples = width * 2
    raw: list[float] = values[-n_samples:] if len(values) >= n_samples else list(values)
    if len(raw) < n_samples:
        raw = [0.0] * (n_samples - len(raw)) + raw

    lines: list[Text] = []
    for row in range(height):
        is_top = row < half
        # Vertical band for this row (btop: cur_high/cur_low)
        if is_top:
            # Top half: row 0 = top (high %), row half-1 = axis
            horizon = row
            cur_high = 100.0 * (half - horizon) / half
            cur_low = 100.0 * (half - (horizon + 1)) / half
            symbols = _BRAILLE_UP
        else:
            # Bottom half: mirror of top — axis row shows low band, bottom shows high
            horizon_inner = row - half
            horizon = half - 1 - horizon_inner
            cur_high = 100.0 * (half - horizon) / half
            cur_low = 100.0 * (half - (horizon + 1)) / half
            symbols = _BRAILLE_DOWN

        line = Text()
        last = raw[0] if len(raw) > 0 else 0.0
        for col in range(width):
            idx_l = col * 2
            idx_r = col * 2 + 1
            v_prev = raw[idx_l] if idx_l < len(raw) else 0.0
            v_curr = raw[idx_r] if idx_r < len(raw) else 0.0

            r0 = _quantize_to_level(v_prev, cur_high, cur_low, mod)
            r1 = _quantize_to_level(v_curr, cur_high, cur_low, mod)
            sym_idx = r0 * 5 + r1
            char = symbols[sym_idx]

            if char == " ":
                # btop graph_bg: grey baseline dots for empty cells
                line.append(_BRAILLE_UP[6], style="dim")
            else:
                color = _cpu_color(max(v_prev, v_curr), theme)
                line.append(char, style=color)
            last = v_curr
        lines.append(line)
    return lines


def _braille_per_core_chart(
    history: list[tuple[float, str]], width: int, theme: object
) -> list[tuple[str, str | None]]:
    """Return (char, color) pairs for 1-row per-core chart using btop braille.

    Each braille char encodes two consecutive samples; color from max(prev, curr).
    Same 5x5 symbol table as btop's height=1 graphs.
    """
    n = len(history)
    if n >= width * 2:
        samples: list[tuple[float, str]] = list(history[-(width * 2):])
    else:
        pad = (width * 2) - n
        samples = [(0.0, "")] * pad + list(history)

    result: list[tuple[str, str | None]] = []
    mod = 0.3  # btop uses 0.3 for height==1
    cur_high, cur_low = 100.0, 0.0

    for col in range(width):
        idx_prev = col * 2
        idx_curr = col * 2 + 1
        v_prev = samples[idx_prev][0] if idx_prev < len(samples) else 0.0
        v_curr = samples[idx_curr][0] if idx_curr < len(samples) else 0.0

        r0 = _quantize_to_level(v_prev, cur_high, cur_low, mod)
        r1 = _quantize_to_level(v_curr, cur_high, cur_low, mod)
        sym_idx = r0 * 5 + r1
        char = _BRAILLE_UP[sym_idx]

        if char == " ":
            # btop uses graph_bg (index 6) with inactive_fg for empty cells
            result.append((_BRAILLE_UP[6], "dim"))  # grey baseline dots
        else:
            color = _cpu_color(max(v_prev, v_curr), theme)
            result.append((char, color))
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
                segments = _braille_per_core_chart(history, core_chart_w, theme)
                line.append(f"C{idx:<2} ", style="dim")
                for char, seg_color in segments:
                    line.append(char, style=seg_color or "dim")
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
