"""Configuration loading and defaults for perf-glance."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perf_glance.grouping.patterns import AppPattern, ToolPattern
from perf_glance.grouping.rules_loader import LauncherRule, SystemCategory, load_grouping_rules_cached


DEFAULT_CONFIG_TOML = '''# perf-glance configuration
# Config file: ~/.config/perf-glance/config.toml

[display]
refresh_interval = 5          # seconds
color = "auto"                # "auto" | "always" | "never"
cpu_layout = "auto"           # "auto" | "1col" | "2col"
show_swap = true
show_cpu_freq = true
show_cpu_temp = true

[grouping]
desktop_dirs = ["/usr/share/applications", "/usr/local/share/applications", "~/.local/share/applications", "/var/lib/snapd/desktop/applications", "/var/lib/flatpak/exports/share/applications", "~/.local/share/flatpak/exports/share/applications"]
other_cpu_max = 0.1
other_mem_max = "30M"
default_expanded = []
expand_threshold = 0

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


def _parse_bytes(s: str) -> int:
    """Parse size string like 30M, 1G, 512K to bytes."""
    s = str(s).strip()
    if not s:
        return 30 << 20  # default 30 MB
    m = re.match(r"^(\d+)\s*([KMG]?i?B?)?$", s, re.IGNORECASE)
    if not m:
        return 30 << 20
    num = int(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("", "b"):
        return num
    if unit.startswith("k"):
        return num << 10
    if unit.startswith("m"):
        return num << 20
    if unit.startswith("g"):
        return num << 30
    return num


@dataclass
class DisplayConfig:
    """Display-related configuration."""

    refresh_interval: int = 5
    color: str = "auto"
    cpu_layout: str = "auto"
    show_swap: bool = True
    show_cpu_freq: bool = True
    show_cpu_temp: bool = True


DEFAULT_DESKTOP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "~/.local/share/applications",
    "/var/lib/snapd/desktop/applications",
    "/var/lib/flatpak/exports/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
]


@dataclass
class GroupingConfig:
    """Process grouping configuration."""

    desktop_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_DESKTOP_DIRS))
    generic_parents: list[str] = field(default_factory=list)
    transparent_runtimes: list[str] = field(default_factory=list)
    apps: list[AppPattern] = field(default_factory=list)
    tools: list[ToolPattern] = field(default_factory=list)
    system_categories: list[SystemCategory] = field(default_factory=list)
    category_overrides: dict[str, str] = field(default_factory=dict)
    launchers_by_exe: dict[str, list[LauncherRule]] = field(default_factory=dict)
    other_cpu_max: float = 0.1
    other_mem_max: int = field(default_factory=lambda: 30 << 20)
    default_expanded: list[str] = field(default_factory=list)
    expand_threshold: int = 0


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


_LEGACY_GROUPING_RULE_KEYS = {
    "apps",
    "tools",
    "category_overrides",
    "generic_parents",
    "transparent_runtimes",
    "force_name_group",
}


def _parse_grouping(raw: dict[str, Any]) -> GroupingConfig:
    """Parse grouping section from config."""
    grouping_raw = raw.get("grouping", {})
    if not isinstance(grouping_raw, dict):
        grouping_raw = {}

    legacy_present = sorted(k for k in grouping_raw.keys() if k in _LEGACY_GROUPING_RULE_KEYS)
    if legacy_present:
        key_list = ", ".join(legacy_present)
        raise ValueError(
            "config.toml uses legacy [grouping] rule keys that are no longer supported: "
            f"{key_list}. Migrate to rules.d files as documented in docs/rules.md."
        )

    desktop_dirs = _get_list(raw, "grouping", "desktop_dirs")
    if not desktop_dirs:
        desktop_dirs = list(DEFAULT_DESKTOP_DIRS)

    other_cpu_max_raw = grouping_raw.get("other_cpu_max", 0.1)
    try:
        other_cpu_max = float(other_cpu_max_raw)
    except (TypeError, ValueError):
        other_cpu_max = 0.1

    other_mem_str = grouping_raw.get("other_mem_max", "30M")
    other_mem_max = _parse_bytes(str(other_mem_str))

    default_expanded = _get_list(raw, "grouping", "default_expanded")
    expand_threshold = _get_int(raw, "grouping", "expand_threshold", default=0)

    rules = load_grouping_rules_cached()

    return GroupingConfig(
        desktop_dirs=desktop_dirs,
        generic_parents=list(rules.generic_parents),
        transparent_runtimes=list(rules.transparent_runtimes),
        apps=list(rules.apps),
        tools=list(rules.tools),
        system_categories=list(rules.system_categories),
        category_overrides=dict(rules.category_overrides),
        launchers_by_exe={k: list(v) for k, v in rules.launchers_by_exe.items()},
        other_cpu_max=other_cpu_max,
        other_mem_max=other_mem_max,
        default_expanded=default_expanded,
        expand_threshold=expand_threshold,
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
        refresh_interval=_get_int(raw, "display", "refresh_interval", default=5),
        color=_get_str(raw, "display", "color", default="auto"),
        cpu_layout=_get_str(raw, "display", "cpu_layout", default="auto"),
        show_swap=_get_bool(raw, "display", "show_swap", default=True),
        show_cpu_freq=_get_bool(raw, "display", "show_cpu_freq", default=True),
        show_cpu_temp=_get_bool(raw, "display", "show_cpu_temp", default=True),
    )

    grouping = _parse_grouping(raw)

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
