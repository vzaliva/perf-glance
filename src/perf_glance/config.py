"""Configuration loading and defaults for perf-glance."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perf_glance.grouping.patterns import AppPattern, ToolPattern


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
generic_parents = ["systemd", "init", "kthreadd", "bash", "dash", "sh", "zsh", "fish", "sudo", "su", "login", "sshd", "tmux", "screen", "env", "start-stop-daemon"]
transparent_runtimes = ["python", "python3", "python3.11", "python3.12", "python3.13", "node", "ruby", "perl"]
other_cpu_max = 0.1
other_mem_max = "30M"
default_expanded = []
expand_threshold = 0
# Legacy: force_name_group -> tools when no [[grouping.tools]] (migration)
force_name_group = ["cc1", "g++", "gcc", "rustc", "clang", "clang++", "as", "ld", "lean", "lake"]

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

DEFAULT_GENERIC_PARENTS = [
    "systemd", "init", "kthreadd", "bash", "dash", "sh", "zsh", "fish",
    "sudo", "su", "login", "sshd", "tmux", "screen", "env", "start-stop-daemon",
]

DEFAULT_TRANSPARENT_RUNTIMES = [
    "python", "python3", "python3.11", "python3.12", "python3.13",
    "node", "ruby", "perl",
]


@dataclass
class GroupingConfig:
    """Process grouping configuration."""

    desktop_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_DESKTOP_DIRS))
    generic_parents: list[str] = field(default_factory=lambda: list(DEFAULT_GENERIC_PARENTS))
    transparent_runtimes: list[str] = field(default_factory=lambda: list(DEFAULT_TRANSPARENT_RUNTIMES))
    apps: list[AppPattern] = field(default_factory=list)
    tools: list[ToolPattern] = field(default_factory=list)
    category_overrides: dict[str, str] = field(default_factory=dict)
    other_cpu_max: float = 0.1
    other_mem_max: int = field(default_factory=lambda: 30 << 20)
    default_expanded: list[str] = field(default_factory=list)
    expand_threshold: int = 0
    # Legacy: used for migration when no explicit tools
    force_name_group: list[str] = field(default_factory=list)


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


def _parse_grouping(raw: dict[str, Any]) -> GroupingConfig:
    """Parse grouping section from config."""
    grouping_raw = raw.get("grouping", {})
    if not isinstance(grouping_raw, dict):
        grouping_raw = {}

    desktop_dirs = _get_list(raw, "grouping", "desktop_dirs")
    if not desktop_dirs:
        desktop_dirs = list(DEFAULT_DESKTOP_DIRS)

    generic_parents = _get_list(raw, "grouping", "generic_parents")
    if not generic_parents:
        generic_parents = list(DEFAULT_GENERIC_PARENTS)

    transparent_runtimes = _get_list(raw, "grouping", "transparent_runtimes")
    if not transparent_runtimes:
        transparent_runtimes = list(DEFAULT_TRANSPARENT_RUNTIMES)

    other_cpu_max = grouping_raw.get("other_cpu_max", 0.1)
    try:
        other_cpu_max = float(other_cpu_max)
    except (TypeError, ValueError):
        other_cpu_max = 0.1

    other_mem_str = grouping_raw.get("other_mem_max", "30M")
    other_mem_max = _parse_bytes(str(other_mem_str))

    default_expanded = _get_list(raw, "grouping", "default_expanded")
    expand_threshold = _get_int(raw, "grouping", "expand_threshold", default=0)

    # Parse [[grouping.apps]]
    apps: list[AppPattern] = []
    for entry in grouping_raw.get("apps", []) or []:
        if isinstance(entry, dict) and entry.get("exe") and entry.get("name"):
            apps.append(AppPattern(
                exe=str(entry["exe"]).strip(),
                name=str(entry["name"]).strip(),
                family=str(entry.get("family", "")).strip(),
                cmdline=str(entry.get("cmdline", "")).strip(),
            ))

    # Parse [[grouping.tools]]
    tools: list[ToolPattern] = []
    tools_raw = grouping_raw.get("tools", []) or []
    force_name_group = _get_list(raw, "grouping", "force_name_group")
    if tools_raw:
        for entry in tools_raw:
            if isinstance(entry, dict) and entry.get("exe") and entry.get("name"):
                tools.append(ToolPattern(
                    exe=str(entry["exe"]).strip(),
                    name=str(entry["name"]).strip(),
                    category=str(entry.get("category", "")).strip(),
                ))
    elif force_name_group:
        # Migration: force_name_group -> tools with name=exe
        for exe in force_name_group:
            exe = exe.strip()
            if exe:
                tools.append(ToolPattern(exe=exe, name=exe.title()))
    else:
        # Default tool list
        tools = [
            ToolPattern(exe="cc1", name="GCC"),
            ToolPattern(exe="g++", name="GCC"),
            ToolPattern(exe="gcc", name="GCC"),
            ToolPattern(exe="rustc", name="Rust"),
            ToolPattern(exe="clang", name="Clang"),
            ToolPattern(exe="clang++", name="Clang"),
            ToolPattern(exe="as", name="Assembler"),
            ToolPattern(exe="ld", name="Linker"),
            ToolPattern(exe="lean", name="Lean"),
            ToolPattern(exe="lake", name="Lake"),
        ]

    # Parse [grouping.category_overrides]
    category_overrides: dict[str, str] = {}
    overrides_raw = grouping_raw.get("category_overrides", {})
    if isinstance(overrides_raw, dict):
        for k, v in overrides_raw.items():
            category_overrides[str(k).strip()] = str(v).strip()

    return GroupingConfig(
        desktop_dirs=desktop_dirs,
        generic_parents=generic_parents,
        transparent_runtimes=transparent_runtimes,
        apps=apps,
        tools=tools,
        category_overrides=category_overrides,
        other_cpu_max=other_cpu_max,
        other_mem_max=other_mem_max,
        default_expanded=default_expanded,
        expand_threshold=expand_threshold,
        force_name_group=force_name_group,
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
