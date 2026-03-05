"""CPU utilization and frequency collector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CPUSnapshot:
    """CPU utilization and frequency data."""

    per_core_pct: list[float]
    aggregate_pct: float
    frequency_ghz: float | None
    _raw_times: list[tuple[int, int]] | None = None  # (idle, total) per core for next delta


def _read_proc_stat() -> list[list[int]]:
    """Read /proc/stat and return parsed CPU lines. Each line is [user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice]."""
    result: list[list[int]] = []
    aggregate: list[int] | None = None
    with open("/proc/stat") as f:
        for line in f:
            if not line.startswith("cpu"):
                break
            parts = line.split()
            if len(parts) < 5:
                continue
            values = []
            for i in range(1, min(11, len(parts))):
                try:
                    values.append(int(parts[i]))
                except ValueError:
                    values.append(0)
            while len(values) < 10:
                values.append(0)
            if parts[0] == "cpu":
                aggregate = values
            else:
                result.append(values)
    # If no per-core lines (e.g. some VMs), use aggregate as single core
    if not result and aggregate:
        result = [aggregate]
    return result


def _parse_cpu_times(values: list[int]) -> tuple[int, int]:
    """Return (idle, total) from CPU time values."""
    # user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice
    user = values[0]
    nice = values[1]
    system = values[2]
    idle = values[3]
    iowait = values[4]
    irq = values[5] if len(values) > 5 else 0
    softirq = values[6] if len(values) > 6 else 0
    steal = values[7] if len(values) > 7 else 0
    guest = values[8] if len(values) > 8 else 0
    guest_nice = values[9] if len(values) > 9 else 0

    total = user + nice + system + idle + iowait + irq + softirq + steal + guest + guest_nice
    idle_total = idle + iowait
    return idle_total, total


def _read_frequency() -> float | None:
    """Read average CPU frequency from sysfs in GHz. Returns None if unavailable (VM, etc)."""
    base = Path("/sys/devices/system/cpu")
    if not base.exists():
        return None
    freqs: list[float] = []
    for cpu_dir in sorted(base.iterdir()):
        if not cpu_dir.name.startswith("cpu") or cpu_dir.name == "cpufreq":
            continue
        cpufreq = cpu_dir / "cpufreq"
        if not cpufreq.exists():
            continue
        for name in ("scaling_cur_freq", "cpuinfo_cur_freq"):
            freq_file = cpufreq / name
            if freq_file.exists():
                try:
                    val = int(freq_file.read_text().strip())
                    freqs.append(val / 1_000_000)  # kHz -> GHz
                    break
                except (ValueError, OSError):
                    pass
    if not freqs:
        return None
    return sum(freqs) / len(freqs)


def read_cpu(previous: CPUSnapshot | None = None) -> CPUSnapshot:
    """Read current CPU utilization. Requires two calls with a delay between for delta-based %; first call returns zeros."""
    per_core_raw = _read_proc_stat()
    if not per_core_raw:
        return CPUSnapshot(
            per_core_pct=[],
            aggregate_pct=0.0,
            frequency_ghz=_read_frequency(),
        )

    current_raw = [_parse_cpu_times(v) for v in per_core_raw]

    if previous is None or previous._raw_times is None:
        return CPUSnapshot(
            per_core_pct=[0.0] * len(per_core_raw),
            aggregate_pct=0.0,
            frequency_ghz=_read_frequency(),
            _raw_times=current_raw,
        )

    prev_raw = previous._raw_times
    if len(prev_raw) != len(current_raw):
        return CPUSnapshot(
            per_core_pct=[0.0] * len(per_core_raw),
            aggregate_pct=0.0,
            frequency_ghz=_read_frequency(),
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
            per_core_pct.append(100.0 * used / delta_total)

    aggregate_pct = sum(per_core_pct) / len(per_core_pct) if per_core_pct else 0.0

    return CPUSnapshot(
        per_core_pct=per_core_pct,
        aggregate_pct=aggregate_pct,
        frequency_ghz=_read_frequency(),
        _raw_times=current_raw,
    )
