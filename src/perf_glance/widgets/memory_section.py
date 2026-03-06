"""Memory (RAM and swap) section widget."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from perf_glance.utils.humanize import bytes_to_human


BAR_WIDTH = 32
FILLED = "█"
EMPTY = "░"


class MemorySection(Static):
    """Widget showing RAM and swap usage."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_args: tuple | None = None

    def refresh_display(self) -> None:
        """Re-render from cached state (no new data collection)."""
        if self._last_args is not None:
            self._repaint(*self._last_args)

    def update_memory(
        self,
        ram_total: int,
        ram_used: int,
        ram_cached: int,
        swap_total: int,
        swap_used: int,
        has_swap: bool,
        theme: object,
        show_swap: bool,
    ) -> None:
        """Update display from memory stats."""
        self._last_args = (ram_total, ram_used, ram_cached, swap_total, swap_used, has_swap, theme, show_swap)
        self._repaint(ram_total, ram_used, ram_cached, swap_total, swap_used, has_swap, theme, show_swap)

    def _repaint(
        self,
        ram_total: int,
        ram_used: int,
        ram_cached: int,
        swap_total: int,
        swap_used: int,
        has_swap: bool,
        theme: object,
        show_swap: bool,
    ) -> None:
        header_color = getattr(theme, "mem_used", "#00bcd4")
        show_swap = show_swap and has_swap and swap_total > 0
        # Adjust bar width: split available space when showing swap side-by-side
        term_w = self.size.width if self.size and self.size.width > 0 else 80
        if show_swap:
            # Each half: "RAM  [bar]  stats   Swap [bar]  stats"
            # Label(5) + bar(w+2) + gap(2) + stats(~22) = ~31+w per side, plus separator
            bar_w = max(12, min(BAR_WIDTH, (term_w - 64) // 2))
        else:
            bar_w = max(12, min(BAR_WIDTH, term_w - 32))

        text = Text()
        text.append("Memory\n", style=header_color)
        text.append("RAM  ", style=header_color)

        # RAM bar: used (colored) + cached (muted) + free (empty)
        if ram_total > 0:
            used_frac = ram_used / ram_total
            cached_frac = ram_cached / ram_total
            used_w = int(bar_w * used_frac + 0.5)
            cached_w = int(bar_w * cached_frac + 0.5)
            used_w = min(used_w, bar_w)
            cached_w = min(cached_w, bar_w - used_w)
            free_w = bar_w - used_w - cached_w

            mem_used = getattr(theme, "mem_used", "#00bcd4")
            mem_cached = getattr(theme, "mem_cached", "#1565c0")
            text.append(f"[{FILLED * used_w}", style=mem_used)
            text.append(f"{FILLED * cached_w}", style=mem_cached)
            text.append(f"{EMPTY * free_w}]  ", style="dim")

        ram_pct = 100.0 * ram_used / ram_total if ram_total else 0
        ram_stats = f"{bytes_to_human(ram_used, use_gib=False)} / {bytes_to_human(ram_total, use_gib=False)}  ({ram_pct:.0f}%)"
        text.append(ram_stats, style="white")

        if show_swap:
            text.append("   ", style="")
            swap_color = getattr(theme, "mem_swap", "#ab47bc")
            text.append("Swap ", style=swap_color)
            swap_frac = swap_used / swap_total if swap_total else 0
            swap_w = min(int(bar_w * swap_frac + 0.5), bar_w)
            text.append(f"[{FILLED * swap_w}{EMPTY * (bar_w - swap_w)}]  ", style=swap_color)
            swap_pct = 100.0 * swap_used / swap_total if swap_total else 0
            text.append(
                f"{bytes_to_human(swap_used, use_gib=False)} / {bytes_to_human(swap_total, use_gib=False)}  ({swap_pct:.0f}%)",
                style="white",
            )

        text.append("\n")
        self.update(text)
