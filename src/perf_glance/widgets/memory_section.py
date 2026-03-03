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
        header_color = getattr(theme, "mem_used", "#00bcd4")
        text = Text()
        text.append("Memory\n", style=header_color)
        text.append("RAM  ", style=header_color)

        # RAM bar: used (colored) + cached (muted) + free (empty)
        if ram_total > 0:
            used_frac = ram_used / ram_total
            cached_frac = ram_cached / ram_total
            used_w = int(BAR_WIDTH * used_frac + 0.5)
            cached_w = int(BAR_WIDTH * cached_frac + 0.5)
            used_w = min(used_w, BAR_WIDTH)
            cached_w = min(cached_w, BAR_WIDTH - used_w)
            free_w = BAR_WIDTH - used_w - cached_w

            mem_used = getattr(theme, "mem_used", "#00bcd4")
            mem_cached = getattr(theme, "mem_cached", "#1565c0")
            text.append(f"[{FILLED * used_w}", style=mem_used)
            text.append(f"{FILLED * cached_w}", style=mem_cached)
            text.append(f"{EMPTY * free_w}]  ", style="dim")

        ram_pct = 100.0 * ram_used / ram_total if ram_total else 0
        text.append(
            f"{bytes_to_human(ram_used, use_gib=False)} / {bytes_to_human(ram_total, use_gib=False)}  ({ram_pct:.0f}%)\n",
            style="white",
        )

        if show_swap and has_swap and swap_total > 0:
            text.append("Swap ", style=getattr(theme, "mem_swap", "#ab47bc"))
            swap_frac = swap_used / swap_total if swap_total else 0
            swap_w = min(int(BAR_WIDTH * swap_frac + 0.5), BAR_WIDTH)
            mem_swap = getattr(theme, "mem_swap", "#ab47bc")
            text.append(f"[{FILLED * swap_w}{EMPTY * (BAR_WIDTH - swap_w)}]  ", style=mem_swap)
            swap_pct = 100.0 * swap_used / swap_total if swap_total else 0
            text.append(
                f"{bytes_to_human(swap_used, use_gib=False)} / {bytes_to_human(swap_total, use_gib=False)}  ({swap_pct:.0f}%)\n",
                style="white",
            )

        self.update(text)
