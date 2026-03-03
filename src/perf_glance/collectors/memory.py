"""Memory (RAM and swap) collector."""

from __future__ import annotations

from dataclasses import dataclass


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


def _parse_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo, return values in bytes (convert from kB)."""
    result: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            key = key.strip()
            val = rest.split()[0]
            try:
                result[key] = int(val) * 1024
            except ValueError:
                pass
    return result


def read_memory() -> MemorySnapshot:
    """Read current memory and swap usage from /proc/meminfo."""
    m = _parse_meminfo()
    ram_total = m.get("MemTotal", 0)
    ram_free = m.get("MemFree", 0)
    buffers = m.get("Buffers", 0)
    cached = m.get("Cached", 0)
    swap_total = m.get("SwapTotal", 0)
    swap_free = m.get("SwapFree", 0)

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
