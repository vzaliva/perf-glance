"""Memory (RAM and swap) collector — macOS (psutil)."""

from __future__ import annotations

import psutil

from perf_glance.collectors.linux.memory import MemorySnapshot


def read_memory() -> MemorySnapshot:
    """Read current memory and swap usage via psutil."""
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()

    ram_total = vm.total
    ram_used = vm.used
    # macOS doesn't have 'buffers'; use inactive as a proxy for cached
    ram_cached = getattr(vm, "inactive", 0)
    ram_percent = vm.percent

    swap_total = sw.total
    swap_used = sw.used
    swap_percent = sw.percent
    has_swap = swap_total > 0

    return MemorySnapshot(
        ram_total_bytes=ram_total,
        ram_used_bytes=ram_used,
        ram_cached_bytes=ram_cached,
        ram_percent=ram_percent,
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
        swap_percent=swap_percent,
        has_swap=has_swap,
    )
