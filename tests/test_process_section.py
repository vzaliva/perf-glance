"""Tests for ProcessSection cumulative CPU accounting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from perf_glance.grouping.process_groups import ProcessGroup
from perf_glance.widgets.process_section import ProcessSection


def test_cumulative_cpu_share_uses_linear_integration() -> None:
    """Cumulative shares are integrated with trapezoid rule between samples."""
    section = ProcessSection()
    g1 = ProcessGroup(name="A", proc_count=1, cpu_pct=10.0, mem_bytes=1, mem_pct=0.1, group_key="g:a")
    g2 = ProcessGroup(name="B", proc_count=1, cpu_pct=10.0, mem_bytes=1, mem_pct=0.1, group_key="g:b")

    groups = [g1, g2]
    section._flat_rows = [(g1, 0), (g2, 0)]
    section._update_cumulative(groups, 100.0)  # baseline only

    g1.cpu_pct = 20.0
    g2.cpu_pct = 10.0
    section._flat_rows = [(g1, 0), (g2, 0)]
    section._update_cumulative(groups, 102.0)

    assert section._cum_by_key["g:a"] == pytest.approx(30.0)
    assert section._cum_by_key["g:b"] == pytest.approx(20.0)
    assert section._cum_share_by_key["g:a"] == pytest.approx(60.0)
    assert section._cum_share_by_key["g:b"] == pytest.approx(40.0)


def test_cumulative_denominator_uses_top_level_only() -> None:
    """Children do not affect the denominator for cumulative percent share."""
    section = ProcessSection()
    parent = ProcessGroup(name="Parent", proc_count=1, cpu_pct=10.0, mem_bytes=1, mem_pct=0.1, group_key="g:parent")
    child = ProcessGroup(name="Child", proc_count=1, cpu_pct=90.0, mem_bytes=1, mem_pct=0.1, group_key="g:parent|sub:child")

    groups = [parent]
    parent.children = [child]
    section._flat_rows = [(parent, 0), (child, 1)]
    section._update_cumulative(groups, 200.0)

    parent.cpu_pct = 10.0
    child.cpu_pct = 90.0
    section._flat_rows = [(parent, 0), (child, 1)]
    section._update_cumulative(groups, 201.0)

    assert section._cum_share_by_key["g:parent"] == pytest.approx(100.0)
    assert section._cum_share_by_key["g:parent|sub:child"] == pytest.approx(900.0)


def test_make_pid_leaves_uses_pid_and_starttime_in_group_key() -> None:
    """Per-PID leaves include starttime in key to avoid PID-reuse collisions."""
    section = ProcessSection()
    parent = ProcessGroup(name="Tool", proc_count=1, cpu_pct=1.0, mem_bytes=1, mem_pct=0.1, group_key="tool:cc1")
    parent.processes = [
        SimpleNamespace(pid=123, exe="cc1", name="cc1", cpu_pct=1.0, rss_bytes=4096, starttime_ticks=555),
    ]

    section._make_pid_leaves(parent, 0)
    assert len(parent.children) == 1
    assert parent.children[0].group_key == "tool:cc1|pid:123:555"
    assert len(parent.children[0].processes) == 1
    assert parent.children[0].processes[0].pid == 123


def test_reset_cumulative_clears_state() -> None:
    """Reset clears integrated totals and baseline sample state."""
    section = ProcessSection()
    g = ProcessGroup(name="A", proc_count=1, cpu_pct=5.0, mem_bytes=1, mem_pct=0.1, group_key="g:a")
    groups = [g]
    section._flat_rows = [(g, 0)]
    section._update_cumulative(groups, 10.0)
    section._update_cumulative(groups, 11.0)

    section.reset_cumulative()

    assert section._cum_by_key == {}
    assert section._prev_pct_by_key == {}
    assert section._cum_share_by_key == {}
    assert section._prev_sample_ts is None


def test_sort_cycle_includes_cumulative() -> None:
    """Sort cycle includes cumulative CPU sorting via key 'cum'."""
    section = ProcessSection()
    assert section.cycle_sort() == "cum"
    assert section.cycle_sort() == "mem"
    assert section.cycle_sort() == "count"
    assert section.cycle_sort() == "cpu"


def test_selected_pids_single_process_row() -> None:
    """k targets exactly one PID when selected row maps to one process."""
    section = ProcessSection()
    proc = SimpleNamespace(pid=42, exe="lean", name="lean", cpu_pct=1.0, rss_bytes=1, starttime_ticks=1)
    g = ProcessGroup(name="Lean", proc_count=1, cpu_pct=1.0, mem_bytes=1, mem_pct=0.1, group_key="tool:lean")
    g.processes = [proc]
    section._flat_rows = [(g, 0)]
    section._cursor_index = 0

    assert section.selected_pids(kill_group=False) == [42]
    assert section.selected_pids(kill_group=True) == [42]


def test_selected_pids_requires_single_row_for_kill() -> None:
    """k does not target multi-process rows; K targets the whole selected row."""
    section = ProcessSection()
    p1 = SimpleNamespace(pid=10, exe="lean", name="lean", cpu_pct=1.0, rss_bytes=1, starttime_ticks=1)
    p2 = SimpleNamespace(pid=11, exe="lake", name="lake", cpu_pct=1.0, rss_bytes=1, starttime_ticks=2)
    g = ProcessGroup(name="Claude", proc_count=2, cpu_pct=2.0, mem_bytes=2, mem_pct=0.2, group_key="app:claude")
    g.processes = [p1, p2]
    section._flat_rows = [(g, 0)]
    section._cursor_index = 0

    assert section.selected_pids(kill_group=False) == []
    assert section.selected_pids(kill_group=True) == [10, 11]


def test_selected_pids_group_kill_collects_nested_children_recursively() -> None:
    """K collects PIDs from selected group and all nested subgroups."""
    section = ProcessSection()
    root = ProcessGroup(name="Root", proc_count=3, cpu_pct=3.0, mem_bytes=3, mem_pct=0.3, group_key="app:root")
    child = ProcessGroup(name="Child", proc_count=2, cpu_pct=2.0, mem_bytes=2, mem_pct=0.2, group_key="app:root|sub:child")
    leaf = ProcessGroup(name="Leaf", proc_count=1, cpu_pct=1.0, mem_bytes=1, mem_pct=0.1, group_key="app:root|sub:child|sub:leaf")

    child.processes = [SimpleNamespace(pid=101), SimpleNamespace(pid=102)]
    leaf.processes = [SimpleNamespace(pid=103)]
    child.children = [leaf]
    root.children = [child]
    root.processes = []

    section._flat_rows = [(root, 0)]
    section._cursor_index = 0

    assert section.selected_pids(kill_group=True) == [101, 102, 103]
