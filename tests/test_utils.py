"""Tests for utility functions."""

from __future__ import annotations

import pytest


def test_bytes_to_human() -> None:
    """bytes_to_human formats correctly."""
    from perf_glance.utils.humanize import bytes_to_human

    assert bytes_to_human(0) == "0"
    assert bytes_to_human(500) == "500B"
    assert bytes_to_human(1024) == "1K"
    assert bytes_to_human(1024 * 1024) == "1M"
    assert bytes_to_human(1024 * 1024 * 1024) == "1G"
    assert bytes_to_human(380 * 1024 * 1024) == "380M"
    assert "31" in bytes_to_human(1024 * 1024 * 1024 * 31 + 500_000_000)


def test_render_line_graph() -> None:
    """render_line_graph produces string."""
    from perf_glance.utils.graph_render import render_line_graph

    values = [10, 30, 50, 70, 90]
    result = render_line_graph(values, width=5, height=4)
    assert result
    assert "\n" in result
