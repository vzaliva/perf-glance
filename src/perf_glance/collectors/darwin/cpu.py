"""CPU utilization and frequency collector — macOS (psutil)."""

from __future__ import annotations

import psutil

from perf_glance.collectors.linux.cpu import CPUSnapshot


def read_cpu(previous: CPUSnapshot | None = None) -> CPUSnapshot:
    """Read current CPU utilization via psutil. Requires two calls for delta-based %."""
    per_core_times = psutil.cpu_times(percpu=True)

    current_raw: list[tuple[int, int]] = []
    for ct in per_core_times:
        idle = round(getattr(ct, "idle", 0) * 1_000_000)
        total = round(sum(ct) * 1_000_000)
        current_raw.append((idle, total))

    per_core_freq = psutil.cpu_freq(percpu=True)
    per_core_freq_ghz: list[float | None] | None = None
    if per_core_freq:
        per_core_freq_ghz = [
            (f.current / 1000.0) if f is not None and f.current > 0 else None
            for f in per_core_freq
        ]

    freq = psutil.cpu_freq()
    frequency_ghz: float | None = None
    if freq is not None:
        frequency_ghz = freq.current / 1000.0  # MHz -> GHz

    if previous is None or previous._raw_times is None:
        return CPUSnapshot(
            per_core_pct=[0.0] * len(current_raw),
            aggregate_pct=0.0,
            frequency_ghz=frequency_ghz,
            per_core_freq_ghz=per_core_freq_ghz,
            _raw_times=current_raw,
        )

    prev_raw = previous._raw_times
    if len(prev_raw) != len(current_raw):
        return CPUSnapshot(
            per_core_pct=[0.0] * len(current_raw),
            aggregate_pct=0.0,
            frequency_ghz=frequency_ghz,
            per_core_freq_ghz=per_core_freq_ghz,
            _raw_times=current_raw,
        )

    per_core_pct: list[float] = []
    for (prev_idle, prev_total), (curr_idle, curr_total) in zip(prev_raw, current_raw):
        delta_total = curr_total - prev_total
        delta_idle = curr_idle - prev_idle
        if delta_total <= 0:
            per_core_pct.append(0.0)
        else:
            used = delta_total - delta_idle
            pct = 100.0 * used / delta_total
            per_core_pct.append(min(100.0, max(0.0, pct)))

    aggregate_pct = sum(per_core_pct) / len(per_core_pct) if per_core_pct else 0.0

    return CPUSnapshot(
        per_core_pct=per_core_pct,
        aggregate_pct=aggregate_pct,
        frequency_ghz=frequency_ghz,
        per_core_freq_ghz=per_core_freq_ghz,
        _raw_times=current_raw,
    )
