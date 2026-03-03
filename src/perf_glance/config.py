"""Configuration loading and defaults for perf-glance."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_TOML = '''# perf-glance configuration
# Config file: ~/.config/perf-glance/config.toml

[display]
refresh_interval = 2          # seconds
color = "auto"                # "auto" | "always" | "never"
cpu_layout = "auto"           # "auto" | "1col" | "2col"
show_swap = true
show_cpu_freq = true
show_cpu_temp = true

[grouping]
force_name_group = ["cc1", "g++", "gcc", "rustc", "clang", "clang++", "as", "ld", "lean", "lake"]
generic_parents = ["systemd", "init", "kthreadd", "bash", "sh", "zsh", "fish", "sudo", "su", "login", "sshd", "tmux", "screen"]

[theme]
cpu_low    = "#00e676"
cpu_mid    = "#ffb300"
cpu_high   = "#f44336"
cpu_graph  = "#00bcd4"
temp_low   = "#00e676"
temp_mid   = "#ff6d00"
temp_high  = "#f44336"
mem_used   = "#00bcd4"
mem_cached = "#1565c0"
mem_swap   = "#ab47bc"
proc_sort_active = "bold"
proc_count       = "#4dd0e1"
'''


def _config_dir() -> Path:
    """Return the config directory path."""
    return Path.home() / ".config" / "perf-glance"


def _default_config_path() -> Path:
    """Return the default config file path."""
    return _config_dir() / "config.toml"


def _ensure_config_file(path: Path) -> None:
    """Create config directory and default config file if they don't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")


def _get_nested(d: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    """Get nested value from dict."""
    if not keys:
        return default
    for key in keys[:-1]:
        d = d.get(key, {})
        if not isinstance(d, dict):
            return default
    return d.get(keys[-1], default)


def _get_str(d: dict[str, Any], *keys: str, default: str = "") -> str:
    """Get nested string from dict."""
    val = _get_nested(d, keys, default)
    return str(val) if val is not None else default


def _get_int(d: dict[str, Any], *keys: str, default: int = 0) -> int:
    """Get nested int from dict."""
    val = _get_nested(d, keys, default)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _get_bool(d: dict[str, Any], *keys: str, default: bool = False) -> bool:
    """Get nested bool from dict."""
    val = _get_nested(d, keys, default)
    if val is None:
        return default
    return bool(val)


def _get_list(d: dict[str, Any], *keys: str) -> list[str]:
    """Get nested list of strings from dict."""
    val = _get_nested(d, keys, [])
    if not isinstance(val, list):
        return []
    return [str(item) for item in val]


@dataclass
class DisplayConfig:
    """Display-related configuration."""

    refresh_interval: int = 2
    color: str = "auto"
    cpu_layout: str = "auto"
    show_swap: bool = True
    show_cpu_freq: bool = True
    show_cpu_temp: bool = True


@dataclass
class GroupingConfig:
    """Process grouping configuration."""

    force_name_group: list[str] = field(default_factory=list)
    generic_parents: list[str] = field(default_factory=list)


@dataclass
class ThemeConfig:
    """Theme/color configuration."""

    cpu_low: str = "#00e676"
    cpu_mid: str = "#ffb300"
    cpu_high: str = "#f44336"
    cpu_graph: str = "#00bcd4"
    temp_low: str = "#00e676"
    temp_mid: str = "#ff6d00"
    temp_high: str = "#f44336"
    mem_used: str = "#00bcd4"
    mem_cached: str = "#1565c0"
    mem_swap: str = "#ab47bc"
    proc_sort_active: str = "bold"
    proc_count: str = "#4dd0e1"


@dataclass
class Config:
    """Full configuration for perf-glance."""

    display: DisplayConfig = field(default_factory=DisplayConfig)
    grouping: GroupingConfig = field(default_factory=GroupingConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)


def _default_grouping() -> GroupingConfig:
    return GroupingConfig(
        force_name_group=[
            "cc1", "g++", "gcc", "rustc", "clang", "clang++", "as", "ld", "lean", "lake"
        ],
        generic_parents=[
            "systemd", "init", "kthreadd", "bash", "sh", "zsh", "fish",
            "sudo", "su", "login", "sshd", "tmux", "screen",
        ],
    )


def load_config(path: Path | None = None) -> Config:
    """Load configuration from file, creating defaults if needed."""
    if path is None:
        path = _default_config_path()
    _ensure_config_file(path)

    raw: dict[str, Any] = {}
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    display = DisplayConfig(
        refresh_interval=_get_int(raw, "display", "refresh_interval", default=2),
        color=_get_str(raw, "display", "color", default="auto"),
        cpu_layout=_get_str(raw, "display", "cpu_layout", default="auto"),
        show_swap=_get_bool(raw, "display", "show_swap", default=True),
        show_cpu_freq=_get_bool(raw, "display", "show_cpu_freq", default=True),
        show_cpu_temp=_get_bool(raw, "display", "show_cpu_temp", default=True),
    )

    grouping = GroupingConfig(
        force_name_group=_get_list(raw, "grouping", "force_name_group")
        or _default_grouping().force_name_group,
        generic_parents=_get_list(raw, "grouping", "generic_parents")
        or _default_grouping().generic_parents,
    )

    theme = ThemeConfig(
        cpu_low=_get_str(raw, "theme", "cpu_low", default="#00e676"),
        cpu_mid=_get_str(raw, "theme", "cpu_mid", default="#ffb300"),
        cpu_high=_get_str(raw, "theme", "cpu_high", default="#f44336"),
        cpu_graph=_get_str(raw, "theme", "cpu_graph", default="#00bcd4"),
        temp_low=_get_str(raw, "theme", "temp_low", default="#00e676"),
        temp_mid=_get_str(raw, "theme", "temp_mid", default="#ff6d00"),
        temp_high=_get_str(raw, "theme", "temp_high", default="#f44336"),
        mem_used=_get_str(raw, "theme", "mem_used", default="#00bcd4"),
        mem_cached=_get_str(raw, "theme", "mem_cached", default="#1565c0"),
        mem_swap=_get_str(raw, "theme", "mem_swap", default="#ab47bc"),
        proc_sort_active=_get_str(raw, "theme", "proc_sort_active", default="bold"),
        proc_count=_get_str(raw, "theme", "proc_count", default="#4dd0e1"),
    )

    return Config(display=display, grouping=grouping, theme=theme)
