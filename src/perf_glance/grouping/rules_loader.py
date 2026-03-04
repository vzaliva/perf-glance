"""Load grouping rules from builtin/system/user rules.d directories."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging
from pathlib import Path
import tomllib
from typing import Any

from perf_glance.grouping.patterns import AppPattern, ToolPattern

log = logging.getLogger(__name__)


def _warn(path: Path, scope: str, message: str) -> None:
    log.warning("rules: %s: %s: %s", path, scope, message)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _append_unique(target: list[str], items: list[str]) -> None:
    seen = set(target)
    for item in items:
        if item not in seen:
            target.append(item)
            seen.add(item)


def _remove_items(target: list[str], items: list[str]) -> list[str]:
    if not items:
        return target
    remove = set(items)
    return [x for x in target if x not in remove]


def _norm_key(value: str) -> str:
    return value.strip().lower()


def _warn_unknown_keys(path: Path, scope: str, entry: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(k for k in entry.keys() if k not in allowed)
    if unknown:
        _warn(path, scope, f"unknown keys: {', '.join(unknown)}")


@dataclass(frozen=True)
class SystemCategory:
    """System category rule."""

    id: str
    name: str
    exe: tuple[str, ...] = ()
    exe_prefix: tuple[str, ...] = ()


@dataclass(frozen=True)
class LauncherMatch:
    """Launcher match constraints."""

    argv_prefix: tuple[str, ...] = ()
    argv1_in: tuple[str, ...] = ()
    min_argv: int = 0


@dataclass(frozen=True)
class LauncherStep:
    """Launcher extraction step."""

    kind: str
    start_index: int = 1
    stop_at_double_dash: bool = True
    flags_with_value: tuple[str, ...] = ()
    module_flag: str = ""
    abort_flags: tuple[str, ...] = ()
    flag: str = ""
    index: int = -1


@dataclass(frozen=True)
class LauncherTransform:
    """Launcher output transform."""

    basename: bool = False
    lowercase: bool = False
    strip_trailing_punct: bool = False
    strip_npm_scope: bool = False
    java_class_tail: bool = False
    generic_entrypoint_fallback: bool = False


@dataclass(frozen=True)
class LauncherRule:
    """Launcher rule entry."""

    id: str
    exe: str
    match: LauncherMatch = field(default_factory=LauncherMatch)
    steps: tuple[LauncherStep, ...] = ()
    transform: LauncherTransform = field(default_factory=LauncherTransform)


@dataclass
class CompiledRules:
    """Compiled rules object consumed by grouping."""

    apps: list[AppPattern]
    tools: list[ToolPattern]
    system_categories: list[SystemCategory]
    category_overrides: dict[str, str]
    launchers_by_exe: dict[str, list[LauncherRule]]
    generic_parents: list[str]
    transparent_runtimes: list[str]


@dataclass
class _RawState:
    apps: dict[str, dict[str, Any]] = field(default_factory=dict)
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    system_categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    category_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    launchers: dict[str, dict[str, Any]] = field(default_factory=dict)
    generic_parents: list[str] = field(default_factory=list)
    transparent_runtimes: list[str] = field(default_factory=list)


def _parse_app(path: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    _warn_unknown_keys(
        path,
        "app",
        entry,
        {"id", "enabled", "exe", "name", "family", "cmdline", "no_tool_reclaim"},
    )
    rid = str(entry.get("id", "")).strip()
    exe = _norm_key(str(entry.get("exe", "")))
    name = str(entry.get("name", "")).strip()
    if not rid or not exe or not name:
        _warn(path, "app", "missing required keys id/exe/name")
        return None
    family = str(entry.get("family", "")).strip().lower()
    cmdline = str(entry.get("cmdline", "")).strip()
    no_tool_reclaim = bool(entry.get("no_tool_reclaim", False))
    return {
        "id": rid,
        "enabled": bool(entry.get("enabled", True)),
        "exe": exe,
        "name": name,
        "family": family,
        "cmdline": cmdline,
        "no_tool_reclaim": no_tool_reclaim,
    }


def _parse_tool(path: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    _warn_unknown_keys(path, "tool", entry, {"id", "enabled", "exe", "name", "category"})
    rid = str(entry.get("id", "")).strip()
    exe = _norm_key(str(entry.get("exe", "")))
    name = str(entry.get("name", "")).strip()
    if not rid or not exe or not name:
        _warn(path, "tool", "missing required keys id/exe/name")
        return None
    return {
        "id": rid,
        "enabled": bool(entry.get("enabled", True)),
        "exe": exe,
        "name": name,
        "category": str(entry.get("category", "")).strip(),
    }


def _parse_system_category(path: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    _warn_unknown_keys(path, "system_category", entry, {"id", "enabled", "name", "exe", "exe_prefix"})
    rid = str(entry.get("id", "")).strip()
    name = str(entry.get("name", "")).strip()
    exe = [_norm_key(x) for x in _as_str_list(entry.get("exe", []))]
    exe_prefix = [_norm_key(x) for x in _as_str_list(entry.get("exe_prefix", []))]
    if not rid or not name:
        _warn(path, "system_category", "missing required keys id/name")
        return None
    if not exe and not exe_prefix:
        _warn(path, f"system_category:{rid}", "at least one of exe/exe_prefix must be non-empty")
        return None
    return {
        "id": rid,
        "enabled": bool(entry.get("enabled", True)),
        "name": name,
        "exe": exe,
        "exe_prefix": exe_prefix,
    }


def _parse_category_override(path: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    _warn_unknown_keys(path, "category_override", entry, {"id", "enabled", "exe", "category"})
    rid = str(entry.get("id", "")).strip()
    exe = _norm_key(str(entry.get("exe", "")))
    if not rid or not exe or "category" not in entry:
        _warn(path, "category_override", "missing required keys id/exe/category")
        return None
    category = str(entry.get("category", ""))
    return {
        "id": rid,
        "enabled": bool(entry.get("enabled", True)),
        "exe": exe,
        "category": category,
    }


def _parse_launcher_step(path: Path, rid: str, step: dict[str, Any]) -> LauncherStep | None:
    _warn_unknown_keys(
        path,
        f"launcher:{rid}.step",
        step,
        {
            "kind",
            "start_index",
            "stop_at_double_dash",
            "flags_with_value",
            "module_flag",
            "abort_flags",
            "flag",
            "index",
        },
    )
    kind = str(step.get("kind", "")).strip()
    if kind not in {"next_after_flag", "first_non_flag", "argv_at", "first_non_flag_after_prefix"}:
        _warn(path, f"launcher:{rid}.step", f"unsupported kind={kind!r}")
        return None
    try:
        start_index = int(step.get("start_index", 1))
    except (TypeError, ValueError):
        start_index = 1
    try:
        index = int(step.get("index", -1))
    except (TypeError, ValueError):
        index = -1
    return LauncherStep(
        kind=kind,
        start_index=max(0, start_index),
        stop_at_double_dash=bool(step.get("stop_at_double_dash", True)),
        flags_with_value=tuple(_as_str_list(step.get("flags_with_value", []))),
        module_flag=str(step.get("module_flag", "")).strip(),
        abort_flags=tuple(_as_str_list(step.get("abort_flags", []))),
        flag=str(step.get("flag", "")).strip(),
        index=index,
    )


def _parse_launcher_match(path: Path, rid: str, match: dict[str, Any]) -> LauncherMatch:
    _warn_unknown_keys(path, f"launcher:{rid}.match", match, {"argv_prefix", "argv1_in", "min_argv"})
    try:
        min_argv = int(match.get("min_argv", 0))
    except (TypeError, ValueError):
        min_argv = 0
    return LauncherMatch(
        argv_prefix=tuple(_as_str_list(match.get("argv_prefix", []))),
        argv1_in=tuple(_as_str_list(match.get("argv1_in", []))),
        min_argv=max(0, min_argv),
    )


def _parse_launcher_transform(path: Path, rid: str, transform: dict[str, Any]) -> LauncherTransform:
    _warn_unknown_keys(
        path,
        f"launcher:{rid}.transform",
        transform,
        {
            "basename",
            "lowercase",
            "strip_trailing_punct",
            "strip_npm_scope",
            "java_class_tail",
            "generic_entrypoint_fallback",
        },
    )
    return LauncherTransform(
        basename=bool(transform.get("basename", False)),
        lowercase=bool(transform.get("lowercase", False)),
        strip_trailing_punct=bool(transform.get("strip_trailing_punct", False)),
        strip_npm_scope=bool(transform.get("strip_npm_scope", False)),
        java_class_tail=bool(transform.get("java_class_tail", False)),
        generic_entrypoint_fallback=bool(transform.get("generic_entrypoint_fallback", False)),
    )


def _parse_launcher(path: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    _warn_unknown_keys(path, "launcher", entry, {"id", "enabled", "exe", "match", "step", "transform"})
    rid = str(entry.get("id", "")).strip()
    exe = _norm_key(str(entry.get("exe", "")))
    if not rid or not exe:
        _warn(path, "launcher", "missing required keys id/exe")
        return None

    steps_raw = entry.get("step", [])
    if not isinstance(steps_raw, list):
        _warn(path, f"launcher:{rid}", "step must be an array table ([[launcher.step]])")
        return None
    steps: list[LauncherStep] = []
    for idx, step_raw in enumerate(steps_raw):
        if not isinstance(step_raw, dict):
            _warn(path, f"launcher:{rid}.step[{idx}]", "step entry must be a table")
            continue
        parsed_step = _parse_launcher_step(path, rid, step_raw)
        if parsed_step:
            steps.append(parsed_step)
    if not steps:
        _warn(path, f"launcher:{rid}", "at least one valid launcher.step is required")
        return None

    match_raw = entry.get("match", {})
    if not isinstance(match_raw, dict):
        _warn(path, f"launcher:{rid}", "match must be a table")
        match_raw = {}
    transform_raw = entry.get("transform", {})
    if not isinstance(transform_raw, dict):
        _warn(path, f"launcher:{rid}", "transform must be a table")
        transform_raw = {}

    rule = LauncherRule(
        id=rid,
        exe=exe,
        match=_parse_launcher_match(path, rid, match_raw),
        steps=tuple(steps),
        transform=_parse_launcher_transform(path, rid, transform_raw),
    )
    return {
        "id": rid,
        "enabled": bool(entry.get("enabled", True)),
        "rule": rule,
    }


def _apply_list_patch(path: Path, state: _RawState, patch: dict[str, Any]) -> None:
    _warn_unknown_keys(
        path,
        "list_patch",
        patch,
        {
            "generic_parents_add",
            "generic_parents_remove",
            "transparent_runtimes_add",
            "transparent_runtimes_remove",
        },
    )
    gp_remove = [_norm_key(x) for x in _as_str_list(patch.get("generic_parents_remove", []))]
    gp_add = [_norm_key(x) for x in _as_str_list(patch.get("generic_parents_add", []))]
    tr_remove = [_norm_key(x) for x in _as_str_list(patch.get("transparent_runtimes_remove", []))]
    tr_add = [_norm_key(x) for x in _as_str_list(patch.get("transparent_runtimes_add", []))]

    state.generic_parents = _remove_items(state.generic_parents, gp_remove)
    _append_unique(state.generic_parents, gp_add)

    state.transparent_runtimes = _remove_items(state.transparent_runtimes, tr_remove)
    _append_unique(state.transparent_runtimes, tr_add)


def _load_file(path: Path, state: _RawState) -> None:
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except OSError as e:
        _warn(path, "file", f"read failed: {e}")
        return
    except tomllib.TOMLDecodeError as e:
        _warn(path, "file", f"TOML parse failed: {e}")
        return

    schema_raw = raw.get("schema_version", 0)
    try:
        schema_version = int(schema_raw or 0)
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version != 1:
        _warn(path, "schema_version", "unsupported schema_version; skipping file")
        return

    for key in raw.keys():
        if key not in {"schema_version", "app", "tool", "system_category", "category_override", "launcher", "list_patch"}:
            _warn(path, "file", f"unknown top-level section: {key}")

    for entry in raw.get("app", []) or []:
        if not isinstance(entry, dict):
            _warn(path, "app", "entry must be table")
            continue
        parsed = _parse_app(path, entry)
        if parsed:
            state.apps[parsed["id"]] = parsed

    for entry in raw.get("tool", []) or []:
        if not isinstance(entry, dict):
            _warn(path, "tool", "entry must be table")
            continue
        parsed = _parse_tool(path, entry)
        if parsed:
            state.tools[parsed["id"]] = parsed

    for entry in raw.get("system_category", []) or []:
        if not isinstance(entry, dict):
            _warn(path, "system_category", "entry must be table")
            continue
        parsed = _parse_system_category(path, entry)
        if parsed:
            state.system_categories[parsed["id"]] = parsed

    for entry in raw.get("category_override", []) or []:
        if not isinstance(entry, dict):
            _warn(path, "category_override", "entry must be table")
            continue
        parsed = _parse_category_override(path, entry)
        if parsed:
            state.category_overrides[parsed["id"]] = parsed

    for entry in raw.get("launcher", []) or []:
        if not isinstance(entry, dict):
            _warn(path, "launcher", "entry must be table")
            continue
        parsed = _parse_launcher(path, entry)
        if parsed:
            state.launchers[parsed["id"]] = parsed

    patch = raw.get("list_patch")
    if isinstance(patch, dict):
        _apply_list_patch(path, state, patch)


def _compile(state: _RawState) -> CompiledRules:
    apps: list[AppPattern] = []
    for entry in state.apps.values():
        if not entry["enabled"]:
            continue
        apps.append(
            AppPattern(
                exe=entry["exe"],
                name=entry["name"],
                family=entry["family"],
                cmdline=entry["cmdline"],
                no_tool_reclaim=bool(entry["no_tool_reclaim"]),
            )
        )

    tools: list[ToolPattern] = []
    for entry in state.tools.values():
        if not entry["enabled"]:
            continue
        tools.append(
            ToolPattern(
                exe=entry["exe"],
                name=entry["name"],
                category=entry["category"],
            )
        )

    categories: list[SystemCategory] = []
    for entry in state.system_categories.values():
        if not entry["enabled"]:
            continue
        categories.append(
            SystemCategory(
                id=entry["id"],
                name=entry["name"],
                exe=tuple(entry["exe"]),
                exe_prefix=tuple(entry["exe_prefix"]),
            )
        )

    overrides: dict[str, str] = {}
    for entry in state.category_overrides.values():
        if not entry["enabled"]:
            continue
        overrides[entry["exe"]] = entry["category"]

    launchers_by_exe: dict[str, list[LauncherRule]] = {}
    for entry in state.launchers.values():
        if not entry["enabled"]:
            continue
        rule = entry["rule"]
        launchers_by_exe.setdefault(rule.exe, []).append(rule)

    return CompiledRules(
        apps=apps,
        tools=tools,
        system_categories=categories,
        category_overrides=overrides,
        launchers_by_exe=launchers_by_exe,
        generic_parents=list(state.generic_parents),
        transparent_runtimes=list(state.transparent_runtimes),
    )


def _builtin_rules_dir() -> Path:
    return Path(__file__).resolve().parent / "rules" / "builtin.d"


def _iter_rule_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted([p for p in base.iterdir() if p.is_file() and p.suffix.lower() == ".toml"])


def load_grouping_rules(
    user_rules_dir: Path | None = None,
    system_rules_dir: Path | None = None,
    builtin_rules_dir: Path | None = None,
) -> CompiledRules:
    """Load grouping rules from builtin, system, and user directories."""
    builtin_dir = builtin_rules_dir or _builtin_rules_dir()
    if not builtin_dir.is_dir():
        raise FileNotFoundError(f"missing built-in rules directory: {builtin_dir}")

    system_dir = system_rules_dir or Path("/etc/perf-glance/rules.d/")
    user_dir = user_rules_dir or (Path.home() / ".config" / "perf-glance" / "rules.d")
    dirs = [builtin_dir, system_dir, user_dir]

    state = _RawState()
    for directory in dirs:
        for path in _iter_rule_files(directory):
            _load_file(path, state)
    return _compile(state)


@lru_cache(maxsize=1)
def load_grouping_rules_cached() -> CompiledRules:
    """Load rules with process-level caching."""
    return load_grouping_rules()
