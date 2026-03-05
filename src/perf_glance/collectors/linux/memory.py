"""Memory (RAM and swap) collector (Linux via psutil)."""

from __future__ import annotations

from dataclasses import dataclass
import psutil


@dataclass
class MemorySnapshot:
    """Memory usage data."""

    ram_total_bytes: int
    ram_used_bytes: int
    ram_cached_bytes: int
    ram_percent: float
    swap_total_bytes: int
    swap_used_bytes: int
    swap_percent: float
    has_swap: bool


def read_memory() -> MemorySnapshot:
    """Read current memory and swap usage via psutil."""
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()

    ram_total = int(vm.total)
    ram_free = int(vm.free)
    buffers = int(getattr(vm, "buffers", 0))
    cached = int(getattr(vm, "cached", 0))
    swap_total = int(sw.total)
    swap_free = int(sw.free)

    # Used = total - free - buffers - cached (matching 'free' command)
    ram_used = ram_total - ram_free - buffers - cached
    if ram_used < 0:
        ram_used = ram_total - ram_free
    ram_cached = buffers + cached
    ram_percent = 100.0 * ram_used / ram_total if ram_total else 0.0

    swap_used = swap_total - swap_free if swap_total else 0
    swap_percent = 100.0 * swap_used / swap_total if swap_total else 0.0
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
