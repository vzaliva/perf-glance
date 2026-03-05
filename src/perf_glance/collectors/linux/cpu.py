"""CPU utilization and frequency collector (Linux via psutil)."""

from __future__ import annotations

from dataclasses import dataclass
import glob
import psutil


@dataclass
class CPUSnapshot:
    """CPU utilization and frequency data."""

    per_core_pct: list[float]
    aggregate_pct: float
    frequency_ghz: float | None
    per_core_freq_ghz: list[float | None] | None = None
    _raw_times: list[tuple[int, int]] | None = None  # (idle, total) per core for next delta


def _parse_cpu_times(ct: object) -> tuple[int, int]:
    """Return (idle, total) in microseconds from a psutil cpu_times item."""
    user = float(getattr(ct, "user", 0.0))
    nice = float(getattr(ct, "nice", 0.0))
    system = float(getattr(ct, "system", 0.0))
    idle = float(getattr(ct, "idle", 0.0))
    iowait = float(getattr(ct, "iowait", 0.0))
    irq = float(getattr(ct, "irq", 0.0))
    softirq = float(getattr(ct, "softirq", 0.0))
    steal = float(getattr(ct, "steal", 0.0))
    guest = float(getattr(ct, "guest", 0.0))
    guest_nice = float(getattr(ct, "guest_nice", 0.0))
    idle_total = round((idle + iowait) * 1_000_000)
    total = round((user + nice + system + idle + iowait + irq + softirq + steal + guest + guest_nice) * 1_000_000)
    return idle_total, total


def _read_freqs_from_paths(paths: list[str]) -> list[float]:
    freqs_mhz: list[float] = []
    for path in paths:
        try:
            with open(path) as f:
                freqs_mhz.append(int(f.read().strip()) / 1000.0)  # kHz -> MHz
        except (OSError, ValueError):
            pass
    return freqs_mhz


def _read_per_core_freq_ghz() -> list[float | None] | None:
    """Read per-core frequency in GHz.

    Prefer psutil per-core frequency (cpuinfo-backed on Linux), then
    cpuinfo_cur_freq, then scaling_cur_freq.
    """
    try:
        per_cpu = psutil.cpu_freq(percpu=True)
    except Exception:
        per_cpu = []
    if per_cpu:
        vals: list[float | None] = [
            (f.current / 1000.0) if f is not None and f.current > 0 else None
            for f in per_cpu
        ]
        if any(v is not None for v in vals):
            return vals

    paths = sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy[0-9]*/cpuinfo_cur_freq"))
    if not paths:
        paths = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_cur_freq"))
    if not paths:
        paths = sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy[0-9]*/scaling_cur_freq"))
    if not paths:
        paths = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"))

    freqs_mhz = _read_freqs_from_paths(paths)
    if freqs_mhz:
        return [v / 1000.0 for v in freqs_mhz]
    return None


def _read_frequency(per_core_ghz: list[float | None] | None) -> float | None:
    """Read aggregate frequency in GHz."""
    if per_core_ghz:
        vals = [v for v in per_core_ghz if v is not None and v > 0]
        if vals:
            return sum(vals) / len(vals)

    try:
        per_cpu = psutil.cpu_freq(percpu=True)
    except Exception:
        per_cpu = []
    if per_cpu:
        vals = [f.current for f in per_cpu if f is not None and f.current > 0]
        if vals:
            return (sum(vals) / len(vals)) / 1000.0
    try:
        freq = psutil.cpu_freq()
    except Exception:
        freq = None
    if freq is None or freq.current <= 0:
        return None
    return freq.current / 1000.0


def read_cpu(previous: CPUSnapshot | None = None) -> CPUSnapshot:
    """Read current CPU utilization. Requires two calls with a delay between for delta-based %; first call returns zeros."""
    per_core_times = psutil.cpu_times(percpu=True)
    per_core_freq_ghz = _read_per_core_freq_ghz()
    if not per_core_times:
        return CPUSnapshot(
            per_core_pct=[],
            aggregate_pct=0.0,
            frequency_ghz=_read_frequency(per_core_freq_ghz),
            per_core_freq_ghz=per_core_freq_ghz,
        )

    current_raw = [_parse_cpu_times(ct) for ct in per_core_times]

    if previous is None or previous._raw_times is None:
        return CPUSnapshot(
            per_core_pct=[0.0] * len(current_raw),
            aggregate_pct=0.0,
            frequency_ghz=_read_frequency(per_core_freq_ghz),
            per_core_freq_ghz=per_core_freq_ghz,
            _raw_times=current_raw,
        )

    prev_raw = previous._raw_times
    if len(prev_raw) != len(current_raw):
        return CPUSnapshot(
            per_core_pct=[0.0] * len(current_raw),
            aggregate_pct=0.0,
            frequency_ghz=_read_frequency(per_core_freq_ghz),
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
            per_core_pct.append(100.0 * used / delta_total)

    aggregate_pct = sum(per_core_pct) / len(per_core_pct) if per_core_pct else 0.0

    return CPUSnapshot(
        per_core_pct=per_core_pct,
        aggregate_pct=aggregate_pct,
        frequency_ghz=_read_frequency(per_core_freq_ghz),
        per_core_freq_ghz=per_core_freq_ghz,
        _raw_times=current_raw,
    )
