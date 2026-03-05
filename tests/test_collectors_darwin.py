"""Tests for macOS (Darwin) collector implementations via psutil mocking."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_darwin_cpu_uses_psutil(monkeypatch: "pytest.MonkeyPatch") -> None:
    """darwin/cpu.py read_cpu() uses psutil.cpu_times and cpu_freq."""
    import pytest
    from perf_glance.collectors.darwin import cpu as darwin_cpu

    # Fake per-core times: 2 cores, each with user+system+idle summing to 100
    core_times = [
        SimpleNamespace(user=20.0, system=10.0, idle=70.0, nice=0.0),
        SimpleNamespace(user=30.0, system=5.0, idle=65.0, nice=0.0),
    ]
    # sum() on a SimpleNamespace won't work; patch __iter__ instead via namedtuple-like object
    import collections
    CoreTimes = collections.namedtuple("CoreTimes", ["user", "system", "idle", "nice"])
    core_times = [CoreTimes(20.0, 10.0, 70.0, 0.0), CoreTimes(30.0, 5.0, 65.0, 0.0)]

    freq = SimpleNamespace(current=2400.0)

    monkeypatch.setattr(darwin_cpu.psutil, "cpu_times", lambda percpu=False: core_times)
    monkeypatch.setattr(darwin_cpu.psutil, "cpu_freq", lambda: freq)

    snap1 = darwin_cpu.read_cpu(None)
    assert len(snap1.per_core_pct) == 2
    assert snap1.aggregate_pct == 0.0
    assert snap1.frequency_ghz == pytest.approx(2.4)
    assert snap1._raw_times is not None

    # Second read with shifted times → non-zero %
    core_times2 = [CoreTimes(25.0, 12.0, 73.0, 0.0), CoreTimes(35.0, 6.0, 69.0, 0.0)]
    monkeypatch.setattr(darwin_cpu.psutil, "cpu_times", lambda percpu=False: core_times2)

    snap2 = darwin_cpu.read_cpu(snap1)
    assert len(snap2.per_core_pct) == 2
    assert all(0.0 <= p <= 100.0 for p in snap2.per_core_pct)


def test_darwin_memory_uses_psutil(monkeypatch: "pytest.MonkeyPatch") -> None:
    """darwin/memory.py read_memory() uses psutil.virtual_memory and swap_memory."""
    from perf_glance.collectors.darwin import memory as darwin_mem

    vm = SimpleNamespace(total=16 * 1024**3, used=8 * 1024**3, inactive=2 * 1024**3, percent=50.0)
    sw = SimpleNamespace(total=4 * 1024**3, used=1 * 1024**3, percent=25.0)

    monkeypatch.setattr(darwin_mem.psutil, "virtual_memory", lambda: vm)
    monkeypatch.setattr(darwin_mem.psutil, "swap_memory", lambda: sw)

    snap = darwin_mem.read_memory()
    assert snap.ram_total_bytes == 16 * 1024**3
    assert snap.ram_used_bytes == 8 * 1024**3
    assert snap.ram_cached_bytes == 2 * 1024**3
    assert snap.ram_percent == 50.0
    assert snap.swap_total_bytes == 4 * 1024**3
    assert snap.swap_used_bytes == 1 * 1024**3
    assert snap.has_swap is True


def test_darwin_processes_uses_psutil(monkeypatch: "pytest.MonkeyPatch") -> None:
    """darwin/processes.py read_processes() uses psutil.pids and psutil.Process."""
    import psutil
    from perf_glance.collectors.darwin import processes as darwin_proc

    monkeypatch.setattr(darwin_proc, "_list_pids", lambda: [42])

    mock_proc = MagicMock()
    mock_proc.__enter__ = lambda s: s
    mock_proc.__exit__ = MagicMock(return_value=False)
    mock_proc.name.return_value = "bash"
    mock_proc.ppid.return_value = 1
    mock_proc.exe.return_value = "/bin/bash"
    mock_proc.cmdline.return_value = ["/bin/bash", "-l"]
    mock_proc.uids.return_value = SimpleNamespace(real=501)
    mock_proc.memory_info.return_value = SimpleNamespace(rss=4096 * 10)
    mock_proc.cpu_times.return_value = SimpleNamespace(user=0.5, system=0.1)
    mock_proc.create_time.return_value = 1700000000.0
    mock_proc.oneshot.return_value = mock_proc

    def fake_process(pid: int) -> MagicMock:
        return mock_proc

    monkeypatch.setattr(darwin_proc.psutil, "Process", fake_process)

    procs, per_pid = darwin_proc.read_processes(100.0, 160.0, {42: (50, 50)})
    assert len(procs) == 1
    p = procs[0]
    assert p.pid == 42
    assert p.name == "bash"
    assert p.exe == "bash"
    assert p.uid == 501
    assert p.rss_bytes == 4096 * 10
    assert p.starttime_ticks == int(1700000000.0 * 100)
    assert 42 in per_pid
