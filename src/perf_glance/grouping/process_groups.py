"""Four-layer process grouping: apps, tools, system categories, catch-all."""

from __future__ import annotations

import os
import pwd
import re
from dataclasses import dataclass, field

from perf_glance.grouping.patterns import AppPattern, ToolPattern
from perf_glance.grouping.rules_loader import LauncherRule, SystemCategory, load_grouping_rules_cached

# Type for ProcessInfo-like objects (from collectors.processes)
from typing import Any

ProcLike = Any


@dataclass
class ProcessGroup:
    """A group of processes with aggregated stats."""

    name: str
    proc_count: int
    cpu_pct: float
    mem_bytes: int
    mem_pct: float  # percent of total RAM
    user: str = ""
    category: str = ""  # "app", "tool", "system", "other"
    children: list[ProcessGroup] = field(default_factory=list)
    processes: list = field(default_factory=list)
    expanded: bool = False
    depth: int = 0
    group_key: str = ""


def _current_username() -> str:
    """Return the username of the process owner (current user)."""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except (KeyError, OverflowError):
        return os.environ.get("USER", "")


def _uid_to_user(uid: int) -> str:
    """Resolve a numeric uid to a username."""
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OverflowError):
        return str(uid)


def _skip_flags(
    parts: list[str],
    start: int,
    flags_with_value: set[str],
    stop_at_double_dash: bool = True,
) -> int:
    """Return index of first non-flag argument at or after start."""
    i = start
    while i < len(parts):
        arg = parts[i]
        if stop_at_double_dash and arg == "--":
            return i + 1
        if not arg.startswith("-"):
            return i
        base = arg.split("=")[0]
        i += 1
        if base in flags_with_value and "=" not in arg:
            i += 1  # skip value token
    return i


def _normalize_exe(exe: str) -> str:
    """Normalize executable name for matching (lowercase, no path)."""
    if not exe:
        return ""
    return exe.lower().split("/")[-1].rstrip(":,;")


def _strip_npm_scope(pkg: str) -> str:
    """Strip npm scope prefix: @scope/name -> name."""
    if pkg.startswith("@") and "/" in pkg:
        return pkg.split("/", 1)[1]
    return pkg


_GENERIC_ENTRYPOINTS: frozenset[str] = frozenset({
    "index.js", "index.ts", "index.mjs", "index.cjs",
    "main.js", "main.ts", "main.py", "__main__.py",
    "cli.js", "cli.ts", "start.js", "run.js", "app.js",
})

_IGNORED_PARENT_DIRS: frozenset[str] = frozenset({"dist", "build", "lib", "src", "out", "bin"})


def _launcher_match(parts: list[str], rule: LauncherRule) -> bool:
    """Check whether command line matches launcher rule constraints."""
    match = rule.match
    if match.min_argv > 0 and len(parts) < match.min_argv:
        return False
    if match.argv1_in:
        if len(parts) < 2 or parts[1] not in set(match.argv1_in):
            return False
    if match.argv_prefix:
        prefix = list(match.argv_prefix)
        if parts[1:1 + len(prefix)] != prefix:
            return False
    return True


def _extract_from_step(parts: list[str], rule: LauncherRule, step) -> str | None:
    """Run one launcher extraction step."""
    flags_with_value = set(step.flags_with_value)

    if step.kind == "next_after_flag":
        if not step.flag:
            return None
        for i, arg in enumerate(parts[1:], start=1):
            if arg == step.flag and i + 1 < len(parts):
                return parts[i + 1]
        return None

    if step.kind == "argv_at":
        idx = step.index if step.index >= 0 else step.start_index
        return parts[idx] if 0 <= idx < len(parts) else None

    if step.kind == "first_non_flag_after_prefix":
        if rule.match.argv_prefix:
            start = 1 + len(rule.match.argv_prefix)
        else:
            start = step.start_index
        i = _skip_flags(parts, start, flags_with_value, stop_at_double_dash=step.stop_at_double_dash)
        return parts[i] if i < len(parts) else None

    if step.kind == "first_non_flag":
        i = step.start_index
        abort_flags = set(step.abort_flags)
        while i < len(parts):
            arg = parts[i]
            if step.stop_at_double_dash and arg == "--":
                i += 1
                break
            if arg in abort_flags:
                return None
            if step.module_flag and arg == step.module_flag:
                return parts[i + 1] if i + 1 < len(parts) else None
            if not arg.startswith("-"):
                return arg
            base = arg.split("=")[0]
            i += 1
            if base in flags_with_value and "=" not in arg:
                i += 1
        return parts[i] if i < len(parts) else None

    return None


def _apply_transform(value: str, rule: LauncherRule) -> str:
    """Apply launcher output transform steps."""
    transformed = value
    t = rule.transform

    if t.strip_npm_scope:
        transformed = _strip_npm_scope(transformed)

    if t.java_class_tail:
        transformed = transformed.split(".")[-1] if "." in transformed else transformed

    if t.generic_entrypoint_fallback and "/" in transformed:
        base = _normalize_exe(transformed.split("/")[-1])
        if base in _GENERIC_ENTRYPOINTS:
            parts_path = [p for p in transformed.split("/") if p]
            for part in reversed(parts_path[:-1]):
                cleaned = _normalize_exe(part)
                if cleaned and cleaned not in _IGNORED_PARENT_DIRS:
                    transformed = cleaned
                    break

    if t.basename:
        transformed = transformed.split("/")[-1]
    if t.strip_trailing_punct:
        transformed = transformed.rstrip(":,;")
    if t.lowercase:
        transformed = transformed.lower()

    return transformed


def _resolve_via_launcher_rules(parts: list[str], rules: list[LauncherRule]) -> str | None:
    """Evaluate launcher rules for argv and return effective executable."""
    for rule in rules:
        if not _launcher_match(parts, rule):
            continue
        for step in rule.steps:
            extracted = _extract_from_step(parts, rule, step)
            if not extracted:
                continue
            transformed = _apply_transform(extracted, rule)
            normalized = _normalize_exe(transformed)
            if normalized:
                return normalized
    return None


def _resolve_as_script_fallback(parts: list[str]) -> str | None:
    """Fallback for transparent runtimes without explicit launcher rules."""
    i = 1
    while i < len(parts):
        arg = parts[i]
        if arg == "-m" and i + 1 < len(parts):
            return _normalize_exe(parts[i + 1])
        if arg == "-c" and i + 1 < len(parts):
            return _normalize_exe(parts[i + 1])
        if arg.startswith("-"):
            i += 1
            continue
        return _normalize_exe(arg)
    return None


def _effective_exe(
    proc: ProcLike,
    transparent_runtimes: set[str],
    launchers_by_exe: dict[str, list[LauncherRule]],
) -> str:
    """Get effective exe by applying declarative launcher rules."""
    exe = (getattr(proc, "exe", None) or getattr(proc, "name", None) or "").strip()
    exe_lower = _normalize_exe(exe)
    if not exe_lower:
        return ""

    cmdline = getattr(proc, "cmdline", None) or ""
    parts = cmdline.split() if cmdline else []
    if len(parts) < 2:
        return exe_lower

    argv0_base = _normalize_exe(parts[0])
    candidate_exes: list[str] = []
    if argv0_base and argv0_base != exe_lower and argv0_base in launchers_by_exe:
        candidate_exes.append(argv0_base)
    if exe_lower in launchers_by_exe:
        candidate_exes.append(exe_lower)

    for candidate in candidate_exes:
        resolved = _resolve_via_launcher_rules(parts, launchers_by_exe.get(candidate, []))
        if resolved:
            return resolved

    if exe_lower in transparent_runtimes:
        fallback = _resolve_as_script_fallback(parts)
        if fallback:
            return fallback

    return exe_lower


_VERSION_SUFFIX_RE = re.compile(r"[-_.]\d+(\.\d+)*$")


def _strip_version_suffix(exe: str) -> str:
    """Strip version suffix like -30.2 or .3.12 from exe name."""
    return _VERSION_SUFFIX_RE.sub("", exe)


def proc_label(p: object) -> str:
    """Label for a single process: effective exe via launcher rules.

    For processes where no launcher transformation occurs (e.g. cursor subprocesses),
    appends the --type=xxx Electron flag so the label is distinguishable.
    """
    defaults = load_grouping_rules_cached()
    raw_exe = _normalize_exe(getattr(p, "exe", "") or getattr(p, "name", "") or "")
    exe = _effective_exe(p, set(defaults.transparent_runtimes), defaults.launchers_by_exe)
    label = exe or raw_exe
    if label == raw_exe:
        cmdline = getattr(p, "cmdline", "") or ""
        m = re.search(r"--type=(\S+)", cmdline)
        if m:
            label = f"{label} [{m.group(1)}]"
    return label


def _match_app(
    effective: str,
    cmdline: str,
    app_patterns: list[AppPattern],
    exe_to_app: dict[str, str],
    desktop_excluded: frozenset[str] = frozenset(),
) -> tuple[str, AppPattern | None] | None:
    """Match process against app patterns. Returns (display_name, pattern) or None.

    desktop_excluded: exe names that should NOT match via exe_to_app (system/generic processes).
    """
    effective_lower = effective.lower()
    effective_base = _strip_version_suffix(effective_lower)
    cmdline_lower = (cmdline or "").lower()
    for pattern in app_patterns:
        exe = pattern.exe.lower()
        if effective_lower != exe and effective_base != exe:
            continue
        cmdline_pat = pattern.cmdline or ""
        if cmdline_pat and cmdline_pat.lower() not in cmdline_lower:
            continue
        return (pattern.name, pattern)
    if effective_lower not in desktop_excluded:
        key = effective_lower if effective_lower in exe_to_app else effective_base
        if key in exe_to_app:
            return (exe_to_app[key], None)
    return None


def _match_tool(effective: str, tool_patterns: list[ToolPattern]) -> tuple[str, str] | None:
    """Match process against tool patterns. Returns (display_name, category) or None."""
    effective_lower = effective.lower()
    for pattern in tool_patterns:
        exe = pattern.exe.lower()
        if effective_lower == exe:
            return (pattern.name, pattern.category or "compiler")
    return None


def _match_system_category(
    proc: ProcLike,
    effective: str,
    system_categories: list[SystemCategory],
    category_overrides: dict[str, str],
) -> str | None:
    """Match process against system categories. Returns category name or None."""
    effective_lower = effective.lower()
    proc_exe = (_normalize_exe(getattr(proc, "exe", "") or "") or effective_lower)
    overridden = category_overrides.get(effective_lower) or category_overrides.get(proc_exe)
    if overridden == "":
        return None
    if overridden:
        return overridden
    for category in system_categories:
        if effective_lower in category.exe:
            return category.name
        for prefix in category.exe_prefix:
            if effective_lower.startswith(prefix):
                return category.name
    return None


def _ancestor_matches_app(
    pid: int,
    ppid_map: dict[int, int],
    pid_to_proc: dict[int, Any],
    effective_exe_map: dict[int, str],
    app_patterns: list[AppPattern],
    exe_to_app: dict[str, str],
    terminal_exes: set[str],
    desktop_excluded: frozenset[str] = frozenset(),
) -> tuple[str, AppPattern | None] | None:
    """Walk up from PARENT; return (app_name, pattern) if any ancestor matches app."""
    start = ppid_map.get(pid)
    if not start or start == pid or start not in ppid_map:
        return None
    current = start
    seen: set[int] = set()
    while current and current not in seen:
        seen.add(current)
        proc = pid_to_proc.get(current)
        if not proc:
            break
        exe = effective_exe_map.get(current, _normalize_exe(getattr(proc, "exe", "") or ""))
        cmdline = getattr(proc, "cmdline", "") or ""
        if exe in terminal_exes:
            return None
        match = _match_app(exe, cmdline, app_patterns, exe_to_app, desktop_excluded)
        if match:
            return match
        ppid = ppid_map.get(current)
        if not ppid or ppid == current or ppid not in ppid_map:
            break
        current = ppid
    return None


def _is_electron_child(proc: ProcLike, parent_exe: str) -> bool:
    """Check if process is Electron/Chromium child (renderer, gpu, utility, etc.)."""
    cmdline = (getattr(proc, "cmdline", "") or "").lower()
    exe = (getattr(proc, "exe", "") or "").lower()
    if not cmdline and not exe:
        return False
    markers = [
        "--type=renderer",
        "--type=gpu-process",
        "--type=utility",
        "--type=zygote",
        "--crashpad-handler",
    ]
    has_marker = any(m in cmdline for m in markers)
    if not has_marker:
        return False
    return parent_exe in cmdline or parent_exe in exe


def _is_gecko_child(proc: ProcLike, parent_exe: str) -> bool:
    """Check if process is Gecko (Firefox) child."""
    cmdline = (getattr(proc, "cmdline", "") or "").lower()
    exe = (getattr(proc, "exe", "") or "").lower()
    return "-contentproc" in cmdline and parent_exe in exe


def _get_tree_root(
    pid: int,
    ppid_map: dict[int, int],
    name_map: dict[int, str],
    generic_parents: set[str],
) -> int:
    """Walk up tree to find group root, skipping generic parents."""
    current = pid
    while True:
        name = name_map.get(current, "").lower()
        ppid = ppid_map.get(current)
        if ppid is None or ppid <= 0 or ppid == current or ppid not in ppid_map:
            return current
        parent_name = name_map.get(ppid, "").lower()
        if name in generic_parents:
            current = ppid
        elif parent_name in generic_parents:
            return current
        elif parent_name == name:
            current = ppid
        else:
            return current


def group_processes(
    processes: list,
    ram_total_bytes: int,
    config: object,
    exe_to_app: dict[str, str] | None = None,
) -> list[ProcessGroup]:
    """Group processes by four-layer algorithm: apps, tools, system, catch-all."""
    from perf_glance.collectors.processes import ProcessInfo

    defaults = load_grouping_rules_cached()
    if exe_to_app is None:
        exe_to_app = {}

    generic_parents_raw = getattr(config, "generic_parents", None)
    if isinstance(generic_parents_raw, list) and generic_parents_raw:
        generic_parents = [str(p).lower() for p in generic_parents_raw]
    else:
        generic_parents = list(defaults.generic_parents)
    generic_set = set(generic_parents)

    transparent_runtimes_raw = getattr(config, "transparent_runtimes", None)
    if isinstance(transparent_runtimes_raw, list) and transparent_runtimes_raw:
        transparent_runtimes = {str(r).lower() for r in transparent_runtimes_raw}
    else:
        transparent_runtimes = set(defaults.transparent_runtimes)

    app_patterns_raw = getattr(config, "apps", None)
    app_patterns = list(app_patterns_raw) if isinstance(app_patterns_raw, list) and app_patterns_raw else list(defaults.apps)

    tool_patterns_raw = getattr(config, "tools", None)
    tool_patterns = list(tool_patterns_raw) if isinstance(tool_patterns_raw, list) and tool_patterns_raw else list(defaults.tools)

    system_categories_raw = getattr(config, "system_categories", None)
    if isinstance(system_categories_raw, list) and system_categories_raw:
        system_categories = list(system_categories_raw)
    else:
        system_categories = list(defaults.system_categories)

    category_overrides_raw = getattr(config, "category_overrides", None)
    if isinstance(category_overrides_raw, dict):
        category_overrides = {str(k).lower(): str(v) for k, v in category_overrides_raw.items()}
    else:
        category_overrides = dict(defaults.category_overrides)

    launchers_by_exe_raw = getattr(config, "launchers_by_exe", None)
    if isinstance(launchers_by_exe_raw, dict) and launchers_by_exe_raw:
        launchers_by_exe = {
            str(exe).lower(): list(rules)
            for exe, rules in launchers_by_exe_raw.items()
            if isinstance(rules, list)
        }
    else:
        launchers_by_exe = {k: list(v) for k, v in defaults.launchers_by_exe.items()}

    other_cpu_max = getattr(config, "other_cpu_max", 0.1) or 0.1
    other_mem_max = getattr(config, "other_mem_max", 30 << 20) or 30 << 20

    pid_to_proc: dict[int, ProcessInfo] = {p.pid: p for p in processes}
    ppid_map: dict[int, int] = {p.pid: p.ppid for p in processes}
    name_map: dict[int, str] = {}
    for p in processes:
        name_map[p.pid] = (p.exe or p.name or "").lower()
    effective_exe_map: dict[int, str] = {}
    for p in processes:
        effective_exe_map[p.pid] = _effective_exe(p, transparent_runtimes, launchers_by_exe)

    terminal_exes = {
        "wezterm-gui", "alacritty", "kitty", "gnome-terminal",
        "konsole", "xterm",
        # macOS terminals
        "iterm2", "terminal", "wezterm",
    }

    # Build set of all exe names claimed by system categories so Layer 1
    # .desktop fallback doesn't steal them (e.g. picom, i3, nm-applet).
    system_exes: set[str] = set()
    for category in system_categories:
        for exe in category.exe:
            system_exes.add(exe)
    desktop_excluded: frozenset[str] = frozenset(system_exes | generic_set)

    # pid -> (layer, group_key)  group_key is "name:uid" or category name
    pid_to_assignment: dict[int, tuple[str, str]] = {}

    def assign(pid: int, layer: str, key: str) -> None:
        pid_to_assignment[pid] = (layer, key)

    def is_assigned(pid: int) -> bool:
        return pid in pid_to_assignment

    # Pids assigned to no-tool-reclaim apps (agent apps, etc.)
    no_tool_reclaim_pids: set[int] = set()

    def _assign_app(pid: int, app_name: str, uid: int, pattern: AppPattern | None) -> None:
        assign(pid, "app", f"{app_name}:{uid}")
        if pattern and (pattern.family == "agent" or pattern.no_tool_reclaim):
            no_tool_reclaim_pids.add(pid)

    # Layer 1: Application recognition
    for proc in processes:
        pid = proc.pid
        if is_assigned(pid):
            continue
        exe = effective_exe_map[pid]
        cmdline = proc.cmdline or ""
        uid = proc.uid

        if not proc.cmdline:
            continue

        # Generic parents (shells, sudo, etc.) are transparent wrappers —
        # they should not become app groups themselves.
        if exe in generic_set:
            continue

        ancestor_match = _ancestor_matches_app(
            pid, ppid_map, pid_to_proc, effective_exe_map,
            app_patterns, exe_to_app, terminal_exes,
            desktop_excluded,
        )
        if ancestor_match:
            app_name, anc_pattern = ancestor_match
            _assign_app(pid, app_name, uid, anc_pattern)
            continue

        # Direct match on the process's own exe.
        match = _match_app(exe, cmdline, app_patterns, exe_to_app, desktop_excluded)
        if match:
            app_name, pattern = match
            if pattern:
                family = pattern.family or ""
                if family in ("electron", "chromium"):
                    if _is_electron_child(proc, pattern.exe.lower()):
                        _assign_app(pid, app_name, uid, pattern)
                        continue
                    root_exe = effective_exe_map.get(pid, exe)
                    if root_exe == pattern.exe.lower():
                        _assign_app(pid, app_name, uid, pattern)
                        continue
                elif family == "gecko":
                    if _is_gecko_child(proc, pattern.exe.lower()):
                        _assign_app(pid, app_name, uid, pattern)
                        continue
                    if exe == pattern.exe.lower():
                        _assign_app(pid, app_name, uid, pattern)
                        continue
            _assign_app(pid, app_name, uid, pattern)
            continue

        root = _get_tree_root(pid, ppid_map, name_map, generic_set)
        root_proc = pid_to_proc.get(root)
        if root_proc:
            root_exe = effective_exe_map.get(root, _normalize_exe(root_proc.exe or ""))
            root_match = _match_app(
                root_exe, root_proc.cmdline or "",
                app_patterns, exe_to_app, desktop_excluded,
            )
            if root_match and root_match[0] and root_match[0] not in terminal_exes:
                _assign_app(pid, root_match[0], uid, root_match[1])
                continue

        if exe in terminal_exes:
            match = _match_app(exe, cmdline, app_patterns, exe_to_app, desktop_excluded)
            if match:
                _assign_app(pid, match[0], uid, match[1])
                continue

    # Layer 2: Tool grouping (reclaims from Layer 1, but not no-tool-reclaim app children)
    for proc in processes:
        pid = proc.pid
        if pid in no_tool_reclaim_pids:
            continue
        exe = effective_exe_map[pid]
        uid = proc.uid
        tool_match = _match_tool(exe, tool_patterns)
        if tool_match:
            tool_name, _ = tool_match
            assign(pid, "tool", f"{tool_name}:{uid}")

    # Layer 3: System categories.
    # Split "current user" from system accounts so e.g. lord's session tools
    # and security agents appear in their own groups.
    current_uid = os.getuid()
    for proc in processes:
        if is_assigned(proc.pid):
            continue
        if not proc.cmdline:
            assign(proc.pid, "system", "Kernel")
            continue
        exe = effective_exe_map[proc.pid]
        cat = _match_system_category(proc, exe, system_categories, category_overrides)
        if cat:
            # Use uid in key only for current user; all other system accounts
            # share the same group per category.
            uid_key = proc.uid if proc.uid == current_uid else -1
            assign(proc.pid, "system", f"{cat}:{uid_key}")

    # Layer 4: Catch-all
    for proc in processes:
        if is_assigned(proc.pid):
            continue
        exe = effective_exe_map[proc.pid] or _normalize_exe(proc.exe or proc.name or "")
        uid = proc.uid
        key = f"exe:{exe}:{uid}" if exe else f"pid:{proc.pid}"
        assign(proc.pid, "other", key)

    # Build key -> list of pids
    key_to_pids: dict[str, list[int]] = {}
    for pid, (layer, key) in pid_to_assignment.items():
        full_key = f"{layer}:{key}"
        key_to_pids.setdefault(full_key, []).append(pid)

    # Build ProcessGroup list
    result: list[ProcessGroup] = []
    for full_key, pids in key_to_pids.items():
        if not pids:
            continue
        procs = [pid_to_proc[pid] for pid in pids if pid in pid_to_proc]
        if not procs:
            continue
        layer, rest = full_key.split(":", 1)
        cpu_pct = sum(p.cpu_pct for p in procs)
        mem_bytes = sum(p.rss_bytes for p in procs)
        mem_pct = 100.0 * mem_bytes / ram_total_bytes if ram_total_bytes else 0.0
        user = _uid_to_user(procs[0].uid) if procs else ""

        if layer == "system" and rest == "Kernel":
            name = "Kernel"
            user = "root"
        elif layer == "system":
            # rest format: "Category Name:uid_key"  (uid_key is current uid or -1)
            cat_name, _, _ = rest.rpartition(":")
            name = cat_name if cat_name else rest
        elif layer == "app":
            name = rest.rsplit(":", 1)[0] if ":" in rest else rest
        elif layer == "tool":
            parts = rest.rsplit(":", 1)
            name = parts[0]
            if len(procs) > 1:
                name = f"{name} build ({len(procs)} procs)"
        else:
            if rest.startswith("exe:"):
                exe_part = rest[4:].rsplit(":", 1)[0]
            else:
                exe_part = rest
            # Prefer the resolved effective exe over the raw proc.exe
            # (e.g. show "proton.vpn.daemon" instead of "python3")
            name = exe_part or procs[0].exe or procs[0].name or "[other]"

        if not name or not name.strip():
            name = "[other]"
        if name.lower() == "systemd":
            name = "Session / Desktop"

        result.append(ProcessGroup(
            name=name,
            proc_count=len(procs),
            cpu_pct=cpu_pct,
            mem_bytes=mem_bytes,
            mem_pct=mem_pct,
            user=user,
            category=layer,
            processes=procs,
            group_key=full_key,
        ))

    result = _post_process_groups(result, other_cpu_max, other_mem_max)
    result = _build_hierarchy(result, ram_total_bytes, config)
    return result


def _electron_type_name(cmdline: str) -> str:
    """Extract Electron/Chromium process type from cmdline."""
    cl = (cmdline or "").lower()
    if "--type=renderer" in cl:
        return "Web Content"
    if "--type=gpu-process" in cl:
        return "GPU Process"
    if "--type=utility" in cl:
        return "Utility"
    if "--type=zygote" in cl:
        return "Zygote"
    if "--crashpad-handler" in cl:
        return "Crashpad"
    return "Main Process"


_GECKO_COMM_FIXUP: dict[str, str] = {
    "Isolated Web Co": "Isolated Web Content",
    "Isolated Servic": "Isolated Service",
    "Privileged Cont": "Privileged Content",
    "Utility Process": "Utility Process",
}


def _gecko_type_name(name: str, cmdline: str) -> str:
    """Use process name (comm) for Gecko sub-type, fixing truncated comm names."""
    name = (name or "").strip()
    if name:
        return _GECKO_COMM_FIXUP.get(name, name)
    if "-contentproc" in (cmdline or ""):
        return "Web Content"
    return "Other"



def _build_tree_subgroups(
    procs: list,
    key_fn,
    parent_group_key: str,
    user: str,
    category: str,
    ram_total_bytes: int,
    skip_keys: frozenset[str] = frozenset(),
    skip_root_keys: frozenset[str] = frozenset(),
) -> list[ProcessGroup]:
    """Build hierarchical sub-groups following actual process tree.

    Algorithm:
    1. Build local tree from ppid links within the group
    2. At each level, merge siblings with same key (from key_fn)
    3. Chain-collapse: absorb same-key children into the parent node
    4. Skip transparent nodes (skip_keys): promote their children at any level
    5. Skip root-only nodes (skip_root_keys): promote their children only at root
    6. Recurse into remaining different-key children
    """
    if not procs:
        return []

    pid_set = {p.pid for p in procs}
    children_of: dict[int, list] = {}
    roots: list = []
    for p in procs:
        if p.ppid in pid_set and p.ppid != p.pid:
            children_of.setdefault(p.ppid, []).append(p)
        else:
            roots.append(p)

    def _expand_transparent(proc_list: list, also_skip: frozenset[str] = frozenset()) -> list:
        """Replace transparent-key procs with their children, recursively."""
        all_skip = skip_keys | also_skip
        result: list = []
        for p in proc_list:
            if key_fn(p) in all_skip:
                result.extend(_expand_transparent(children_of.get(p.pid, [])))
            else:
                result.append(p)
        return result

    def collect(proc_list: list, parent_key: str, is_root: bool = False) -> list[ProcessGroup]:
        if not proc_list:
            return []

        # Expand any transparent nodes before grouping
        # At root level, also expand skip_root_keys
        extra = skip_root_keys if is_root else frozenset()
        proc_list = _expand_transparent(proc_list, also_skip=extra)
        if not proc_list:
            return []

        # Group siblings by key, preserving first-seen order
        by_key: dict[str, tuple[list, list]] = {}
        order: list[str] = []
        for p in proc_list:
            key = key_fn(p)
            if key not in by_key:
                by_key[key] = ([], [])
                order.append(key)
            own_procs, child_pool = by_key[key]
            own_procs.append(p)
            child_pool.extend(children_of.get(p.pid, []))

        result: list[ProcessGroup] = []
        for key in order:
            own_procs, child_pool = by_key[key]

            # Chain-collapse: absorb same-key children, promote grandchildren
            same = [c for c in child_pool if key_fn(c) == key]
            diff = [c for c in child_pool if key_fn(c) != key]
            while same:
                own_procs.extend(same)
                next_gen: list = []
                for c in same:
                    next_gen.extend(children_of.get(c.pid, []))
                same = [g for g in next_gen if key_fn(g) == key]
                diff.extend(g for g in next_gen if key_fn(g) != key)

            node_key = f"{parent_key}|sub:{key.strip().lower()}"
            sub_children = collect(diff, node_key)

            cpu = sum(getattr(p, "cpu_pct", 0) for p in own_procs)
            mem = sum(getattr(p, "rss_bytes", 0) for p in own_procs)
            mem_pct = 100.0 * mem / ram_total_bytes if ram_total_bytes else 0.0

            name = f"{key} ({len(own_procs)})" if len(own_procs) > 1 else key

            result.append(ProcessGroup(
                name=name, proc_count=len(own_procs), cpu_pct=cpu,
                mem_bytes=mem, mem_pct=mem_pct, user=user,
                category=category, processes=own_procs,
                children=sub_children, depth=0,
                group_key=node_key,
            ))
        return result

    return collect(roots, parent_group_key, is_root=True)


def _build_hierarchy(
    groups: list[ProcessGroup],
    ram_total_bytes: int,
    config: object,
) -> list[ProcessGroup]:
    """Build children sub-groups for apps, tools, and system categories."""
    defaults = load_grouping_rules_cached()
    default_expanded = {
        str(x).lower()
        for x in (getattr(config, "default_expanded", None) or [])
    }
    expand_threshold = getattr(config, "expand_threshold", 0) or 0

    transparent_runtimes_raw = getattr(config, "transparent_runtimes", None)
    if isinstance(transparent_runtimes_raw, list) and transparent_runtimes_raw:
        transparent_runtimes: set[str] = {str(r).lower() for r in transparent_runtimes_raw}
    else:
        transparent_runtimes = set(defaults.transparent_runtimes)

    generic_parents_raw = getattr(config, "generic_parents", None)
    if isinstance(generic_parents_raw, list) and generic_parents_raw:
        generic_parents: set[str] = {str(p).lower() for p in generic_parents_raw}
    else:
        generic_parents = set(defaults.generic_parents)

    # Keys that are transparent inside sub-group trees: don't create nodes,
    # promote their children instead.
    skip_keys: frozenset[str] = frozenset(generic_parents | transparent_runtimes)

    launchers_by_exe_raw = getattr(config, "launchers_by_exe", None)
    if isinstance(launchers_by_exe_raw, dict) and launchers_by_exe_raw:
        launchers_by_exe = {
            str(exe).lower(): list(rules)
            for exe, rules in launchers_by_exe_raw.items()
            if isinstance(rules, list)
        }
    else:
        launchers_by_exe = {k: list(v) for k, v in defaults.launchers_by_exe.items()}

    app_patterns_raw = getattr(config, "apps", None)
    if isinstance(app_patterns_raw, list) and app_patterns_raw:
        app_patterns = list(app_patterns_raw)
    else:
        app_patterns = list(defaults.apps)

    # Agent-family app names (TUI AI agents whose children should be labeled
    # by effective exe, not by Electron process type).
    agent_app_names = {
        p.name.lower() for p in app_patterns if getattr(p, "family", "") == "agent"
    }

    result: list[ProcessGroup] = []
    for g in groups:
        procs = g.processes or []
        children: list[ProcessGroup] = []

        if g.category == "app" and len(procs) > 1:
            exe_lower = (procs[0].exe or "").lower() if procs else ""
            _app_exe = _normalize_exe(procs[0].exe or "") if procs else ""
            if any(x in exe_lower for x in ["firefox", "thunderbird", "librewolf"]):
                # Skip the app's own root process — it's redundant with the group
                gecko_root_skip = frozenset({_app_exe}) if _app_exe else frozenset()
                children = _build_tree_subgroups(
                    procs,
                    lambda p: _gecko_type_name(p.name or "", p.cmdline or ""),
                    g.group_key,
                    g.user, "app", ram_total_bytes,
                    skip_keys=skip_keys,
                    skip_root_keys=gecko_root_skip,
                )
            elif g.name.lower() in agent_app_names:
                children = _build_tree_subgroups(
                    procs,
                    lambda p, tr=transparent_runtimes, lr=launchers_by_exe: _effective_exe(p, tr, lr) or _normalize_exe(p.exe or p.name or "unknown"),
                    g.group_key,
                    g.user, "app", ram_total_bytes,
                    skip_keys=skip_keys,
                )
            else:
                def _electron_key(
                    p,
                    tr=transparent_runtimes, lr=launchers_by_exe,
                    app_exe=_app_exe,
                ):
                    t = _electron_type_name(p.cmdline or "")
                    if t != "Main Process":
                        return t
                    exe = _effective_exe(p, tr, lr) or _normalize_exe(p.exe or p.name or "unknown")
                    return "Main Process" if exe == app_exe else exe
                # Skip "Main Process" at root — the app group already represents it
                children = _build_tree_subgroups(
                    procs, _electron_key,
                    g.group_key, g.user, "app", ram_total_bytes,
                    skip_keys=skip_keys,
                    skip_root_keys=frozenset({"Main Process"}),
                )

        elif g.category == "tool" and len(procs) > 1:
            children = _build_tree_subgroups(
                procs,
                lambda p, tr=transparent_runtimes, lr=launchers_by_exe: _effective_exe(p, tr, lr) or _normalize_exe(p.exe or p.name or "unknown"),
                g.group_key,
                g.user, "tool", ram_total_bytes,
                skip_keys=skip_keys,
            )

        elif g.category == "system" and len(procs) > 1 and g.name != "Kernel":
            children = _build_tree_subgroups(
                procs,
                lambda p, tr=transparent_runtimes, lr=launchers_by_exe: _effective_exe(p, tr, lr) or _normalize_exe(p.exe or p.name or "unknown"),
                g.group_key,
                g.user, "system", ram_total_bytes,
                skip_keys=skip_keys,
            )

        expanded = (
            g.name.lower() in default_expanded
            or (expand_threshold > 0 and g.proc_count <= expand_threshold)
        )
        result.append(ProcessGroup(
            name=g.name,
            proc_count=g.proc_count,
            cpu_pct=g.cpu_pct,
            mem_bytes=g.mem_bytes,
            mem_pct=g.mem_pct,
            user=g.user,
            category=g.category,
            children=children,
            processes=g.processes,
            expanded=expanded,
            depth=0,
            group_key=g.group_key,
        ))
    return result


def _post_process_groups(
    groups: list[ProcessGroup],
    other_cpu_max: float,
    other_mem_max: int,
) -> list[ProcessGroup]:
    """Dedup by name, bucket small groups into other (N). No user services bucket."""
    preserved = {"kernel", "session / desktop"}
    kept: list[ProcessGroup] = []
    other: list[ProcessGroup] = []

    by_key: dict[tuple[str, str], ProcessGroup] = {}
    for g in groups:
        key = (g.name.lower(), g.user)
        dedup_group_key = f"{(g.category or '').lower()}:{g.name.lower()}:{g.user}"
        if key in by_key:
            existing = by_key[key]
            by_key[key] = ProcessGroup(
                name=g.name,
                proc_count=existing.proc_count + g.proc_count,
                cpu_pct=existing.cpu_pct + g.cpu_pct,
                mem_bytes=existing.mem_bytes + g.mem_bytes,
                mem_pct=existing.mem_pct + g.mem_pct,
                user=g.user,
                category=g.category or existing.category,
                children=existing.children or g.children,
                processes=(existing.processes or []) + (g.processes or []),
                group_key=dedup_group_key,
            )
        else:
            g.group_key = dedup_group_key
            by_key[key] = g
    groups = list(by_key.values())

    for g in groups:
        if g.name.lower() in preserved:
            kept.append(g)
        elif g.category in ("app", "tool", "system"):
            # Named categories are never bucketed into "other"
            kept.append(g)
        elif g.cpu_pct < other_cpu_max and g.mem_bytes < other_mem_max:
            other.append(g)
        else:
            kept.append(g)

    if other:
        n = sum(g.proc_count for g in other)
        all_procs = [p for g in other for p in (g.processes or [])]
        kept.append(ProcessGroup(
            name=f"other ({n})",
            proc_count=n,
            cpu_pct=sum(g.cpu_pct for g in other),
            mem_bytes=sum(g.mem_bytes for g in other),
            mem_pct=sum(g.mem_pct for g in other),
            user="",
            category="other",
            children=other,
            processes=all_procs,
            group_key="other:bucket",
        ))
    return kept
