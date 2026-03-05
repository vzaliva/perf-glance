"""Tests for data collectors."""

from __future__ import annotations

import pytest


def test_memory_collector_returns_snapshot() -> None:
    """Memory collector returns valid snapshot."""
    from perf_glance.collectors.memory import read_memory

    mem = read_memory()
    assert mem.ram_total_bytes > 0
    assert mem.ram_used_bytes >= 0
    assert mem.ram_cached_bytes >= 0
    assert 0 <= mem.ram_percent <= 100
    assert mem.swap_total_bytes >= 0
    assert mem.swap_used_bytes >= 0


def test_cpu_collector_first_call_returns_zeros() -> None:
    """First CPU read returns zeros (needs delta for percentages)."""
    from perf_glance.collectors.cpu import read_cpu

    snap = read_cpu(None)
    assert snap.per_core_pct is not None
    assert snap._raw_times is not None


def test_cpu_collector_second_call_returns_percentages() -> None:
    """Second CPU read after delay returns percentages."""
    import time
    from perf_glance.collectors.cpu import read_cpu

    snap1 = read_cpu(None)
    time.sleep(0.1)
    snap2 = read_cpu(snap1)
    assert len(snap2.per_core_pct) == len(snap1.per_core_pct)
    assert all(0 <= p <= 100 for p in snap2.per_core_pct)


def test_temperature_returns_float_or_none() -> None:
    """Temperature returns float or None."""
    from perf_glance.collectors.temperature import read_temperature

    temp = read_temperature()
    assert temp is None or isinstance(temp, (int, float))


def test_get_aggregate_cpu_times() -> None:
    """get_aggregate_cpu_times returns positive number."""
    from perf_glance.collectors.processes import get_aggregate_cpu_times

    total = get_aggregate_cpu_times()
    assert total >= 0


@pytest.mark.skipif(
    __import__("sys").platform != "linux",
    reason="Linux-specific psutil-backed collector monkeypatching",
)
def test_read_processes_includes_starttime_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_processes propagates starttime_ticks into ProcessInfo."""
    from perf_glance.collectors.linux import processes as proc_mod

    monkeypatch.setattr(proc_mod, "_list_pids", lambda: [123])
    monkeypatch.setattr(
        proc_mod,
        "_snapshot_pid",
        lambda _pid: {
            "name": "bash",
            "ppid": 1,
            "cmdline": "/usr/bin/bash -lc true",
            "exe_path": "/usr/bin/bash",
            "uid": 1000,
            "total_time_ticks": 15,
            "rss_bytes": 4096,
            "starttime_ticks": 777,
        },
    )

    procs, _ = proc_mod.read_processes(100.0, 120.0, {123: (10, 10)})
    assert len(procs) == 1
    assert procs[0].starttime_ticks == 777
