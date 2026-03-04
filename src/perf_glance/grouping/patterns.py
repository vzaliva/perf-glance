"""Shared grouping pattern dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppPattern:
    """Application pattern for Layer 1 recognition."""

    exe: str
    name: str
    family: str = ""
    cmdline: str = ""
    no_tool_reclaim: bool = False


@dataclass(frozen=True)
class ToolPattern:
    """Build/dev tool pattern for Layer 2 grouping."""

    exe: str
    name: str
    category: str = ""

