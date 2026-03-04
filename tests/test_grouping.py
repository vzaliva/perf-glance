"""Tests for process grouping."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class MockProcess:
    pid: int
    ppid: int
    name: str
    exe: str
    cpu_pct: float
    rss_bytes: int
    cmdline: str
    uid: int = 0


def test_group_processes_basic() -> None:
    """Basic grouping produces ProcessGroups."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "firefox", "firefox", 5.0, 100_000_000, "firefox"),
        MockProcess(11, 10, "Web Content", "firefox", 3.0, 50_000_000, ""),
    ]
    groups = group_processes(
        processes,
        ram_total_bytes=1_000_000_000,
        force_name_group=[],
        generic_parents=["systemd", "init"],
    )
    assert len(groups) >= 1
    assert any("firefox" in g.name.lower() for g in groups)


def test_force_name_group() -> None:
    """force_name_group groups by exe regardless of tree."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(100, 50, "cc1", "cc1", 10.0, 50_000_000, ""),
        MockProcess(101, 60, "cc1", "cc1", 12.0, 60_000_000, ""),
    ]
    groups = group_processes(
        processes,
        ram_total_bytes=1_000_000_000,
        force_name_group=["cc1"],
        generic_parents=["systemd"],
    )
    assert len(groups) == 1
    assert groups[0].proc_count == 2
    assert groups[0].cpu_pct == 22.0
    assert groups[0].mem_bytes == 110_000_000
