"""Four-layer process grouping: apps, tools, system categories, catch-all."""

from __future__ import annotations

import os
import pwd
import re
from dataclasses import dataclass, field

from perf_glance.grouping.patterns import (
    APP_PATTERNS,
    SYSTEM_CATEGORIES,
    TOOL_PATTERNS,
)

# Type for ProcessInfo-like objects (from collectors.processes)
from typing import Any, Callable

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


def _skip_flags(parts: list[str], start: int, flags_with_value: frozenset[str] = frozenset()) -> int:
    """Return index of first non-flag argument at or after start."""
    i = start
    while i < len(parts):
        arg = parts[i]
        if arg == "--":
            return i + 1
        if not arg.startswith("-"):
            return i
        i += 1
        base = arg.split("=")[0]
        if base in flags_with_value and "=" not in arg:
            i += 1  # skip value token
    return i


def _resolve_as_script(parts: list[str]) -> str | None:
    """Runtime that runs a script: [exe] [-flags] script [args].
    Handles `python -m module` and skips `-c` (inline code, no meaningful name)."""
    i = 1
    while i < len(parts):
        arg = parts[i]
        if arg == "-m" and i + 1 < len(parts):
            return parts[i + 1]
        if arg == "-c":
            return None
        if arg.startswith("-"):
            i += 1
            continue
        return arg
    return None


_UV_FLAGS_WITH_VALUE: frozenset[str] = frozenset({
    "--with", "--package", "-p", "--python", "--from",
    "--extra", "--group", "--only-group", "--directory", "-C",
})


def _resolve_uv(parts: list[str]) -> str | None:
    """uv run / uv tool run / uv tool uvx — resolve the actual command being run."""
    if len(parts) < 3:
        return None
    sub = parts[1]
    if sub == "run":
        i = _skip_flags(parts, 2, _UV_FLAGS_WITH_VALUE)
        return parts[i] if i < len(parts) else None
    if sub == "tool" and len(parts) >= 4 and parts[2] in ("run", "uvx"):
        i = _skip_flags(parts, 3, _UV_FLAGS_WITH_VALUE)
        return parts[i] if i < len(parts) else None
    return None


def _resolve_uvx(parts: list[str]) -> str | None:
    """uvx <cmd> [args] — standalone alias for `uv tool run`."""
    i = _skip_flags(parts, 1, _UV_FLAGS_WITH_VALUE)
    return parts[i] if i < len(parts) else None


def _strip_npm_scope(pkg: str) -> str:
    """Strip npm scope prefix: @scope/name → name."""
    if pkg.startswith("@") and "/" in pkg:
        return pkg.split("/", 1)[1]
    return pkg


_NPM_FLAGS_WITH_VALUE: frozenset[str] = frozenset({"--workspace", "-w"})


def _resolve_npm(parts: list[str]) -> str | None:
    """npm run/exec/x <pkg> [args] — resolve to the actual command."""
    if len(parts) < 3:
        return None
    sub = parts[1]
    if sub in ("exec", "run", "x"):
        i = _skip_flags(parts, 2, _NPM_FLAGS_WITH_VALUE)
        return _strip_npm_scope(parts[i]) if i < len(parts) else None
    return None


def _resolve_npx(parts: list[str]) -> str | None:
    """npx <pkg> [args] — direct package runner."""
    i = _skip_flags(parts, 1)
    return _strip_npm_scope(parts[i]) if i < len(parts) else None


def _resolve_go_run(parts: list[str]) -> str | None:
    """go run [flags] <file/pkg> [args]"""
    if len(parts) < 3 or parts[1] != "run":
        return None
    i = _skip_flags(parts, 2)
    return parts[i] if i < len(parts) else None


_JAVA_FLAGS_WITH_VALUE: frozenset[str] = frozenset({
    "-cp", "-classpath", "--class-path", "-p", "--module-path",
    "--add-modules", "--module", "-m", "--add-opens", "--add-exports",
    "--add-reads", "-javaagent",
})


def _resolve_java(parts: list[str]) -> str | None:
    """java [options] {-jar jarfile | MainClass} [args]"""
    i = 1
    while i < len(parts):
        arg = parts[i]
        if arg == "-jar" and i + 1 < len(parts):
            return parts[i + 1]
        if arg in _JAVA_FLAGS_WITH_VALUE:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        # Fully-qualified class name → take last component
        return arg.split(".")[-1] or arg
    return None


# Built-in launcher resolvers.  For each wrapper exe, a function that parses
# the cmdline parts and returns the real program name (or None if not resolvable).
_LAUNCHER_RESOLVERS: dict[str, Callable[[list[str]], str | None]] = {
    # Python family
    "python":     _resolve_as_script,
    "python2":    _resolve_as_script,
    "python3":    _resolve_as_script,
    "python3.9":  _resolve_as_script,
    "python3.10": _resolve_as_script,
    "python3.11": _resolve_as_script,
    "python3.12": _resolve_as_script,
    "python3.13": _resolve_as_script,
    # Shells (also in generic_parents — both apply)
    "bash":  _resolve_as_script,
    "sh":    _resolve_as_script,
    "dash":  _resolve_as_script,
    "zsh":   _resolve_as_script,
    "fish":  _resolve_as_script,
    # Other runtimes
    "node":  _resolve_as_script,
    "ruby":  _resolve_as_script,
    "perl":  _resolve_as_script,
    # Package/task runners
    "uv":    _resolve_uv,
    "uvx":   _resolve_uvx,
    "npm":   _resolve_npm,
    "npx":   _resolve_npx,
    # JVM
    "java":  _resolve_java,
    # Go
    "go":    _resolve_go_run,
}


# Generic entry-point basenames that are not meaningful as process names.
# When a launcher resolves to one of these, use the parent directory name.
_GENERIC_ENTRYPOINTS: frozenset[str] = frozenset({
    "index.js", "index.ts", "index.mjs", "index.cjs",
    "main.js", "main.ts", "main.py", "__main__.py",
    "cli.js", "cli.ts", "start.js", "run.js", "app.js",
})


def _effective_exe(proc: ProcLike, transparent_runtimes: set[str]) -> str:
    """Get effective exe: resolve launcher wrappers to the actual program being run.

    Checks built-in _LAUNCHER_RESOLVERS first (handles -m, subcommands, flags),
    then falls back to transparent_runtimes (user-configured, simple argv[1] lookup).
    """
    exe = (getattr(proc, "exe", None) or getattr(proc, "name", None) or "").strip()
    if not exe or "/" in exe:
        exe = exe.split("/")[-1] if exe else ""
    exe_lower = exe.lower()

    resolver = _LAUNCHER_RESOLVERS.get(exe_lower)
    if resolver is None and exe_lower in transparent_runtimes:
        resolver = _resolve_as_script

    if resolver:
        cmdline = getattr(proc, "cmdline", None) or ""
        if cmdline:
            parts = cmdline.split()
            if len(parts) >= 2:
                # Secondary dispatch: when the runtime (e.g. node) launched a
                # different known tool as argv[0] (e.g. npm, npx), defer to
                # that tool's resolver instead.  This handles cases like:
                #   exe=node  cmdline="npm exec @upstash/context7-mcp"
                # where _resolve_as_script would return "exec" but
                # _resolve_npm correctly returns "context7-mcp".
                argv0_base = parts[0].split("/")[-1].lower().rstrip(":,;")
                if argv0_base != exe_lower:
                    secondary = _LAUNCHER_RESOLVERS.get(argv0_base)
                    if secondary is not None:
                        resolver = secondary
                result = resolver(parts)
                if result:
                    # If the resolved name is a generic entry point (index.js,
                    # main.py, etc.), use the parent directory name instead so
                    # e.g. "node /path/lean-lsp-mcp/dist/index.js" → "lean-lsp-mcp".
                    base = result.split("/")[-1].lower().rstrip(":,;") if "/" in result else result.lower().rstrip(":,;")
                    if base in _GENERIC_ENTRYPOINTS and "/" in result:
                        parts_path = result.split("/")
                        # Walk back to find first non-generic directory component
                        for part in reversed(parts_path[:-1]):
                            if part and part not in ("dist", "build", "lib", "src", "out", "bin"):
                                base = part.lower().rstrip(":,;")
                                break
                    cleaned = base or exe_lower
                    return cleaned
    return exe_lower


def _normalize_exe(exe: str) -> str:
    """Normalize executable name for matching (lowercase, no path)."""
    if not exe:
        return ""
    return exe.lower().split("/")[-1].rstrip(":,;")


_VERSION_SUFFIX_RE = re.compile(r"[-_.]\d+(\.\d+)*$")


def _strip_version_suffix(exe: str) -> str:
    """Strip version suffix like -30.2 or .3.12 from exe name."""
    return _VERSION_SUFFIX_RE.sub("", exe)


def _match_app(
    effective: str,
    cmdline: str,
    app_patterns: list,
    exe_to_app: dict[str, str],
    desktop_excluded: frozenset[str] = frozenset(),
) -> tuple[str, object] | None:
    """Match process against app patterns. Returns (display_name, pattern) or None.

    desktop_excluded: exe names that should NOT match via exe_to_app (system/generic processes).
    """
    effective_lower = effective.lower()
    effective_base = _strip_version_suffix(effective_lower)
    cmdline_lower = (cmdline or "").lower()
    # Priority: config apps, built-in APP_PATTERNS, desktop exe_to_app
    for pattern in app_patterns:
        exe = getattr(pattern, "exe", "").lower()
        if effective_lower != exe and effective_base != exe:
            continue
        cmdline_pat = getattr(pattern, "cmdline", "") or ""
        if cmdline_pat and cmdline_pat.lower() not in cmdline_lower:
            continue
        return (getattr(pattern, "name", exe), pattern)
    if effective_lower not in desktop_excluded:
        key = effective_lower if effective_lower in exe_to_app else effective_base
        if key in exe_to_app:
            return (exe_to_app[key], None)
    return None


def _match_tool(effective: str, tool_patterns: list) -> tuple[str, str] | None:
    """Match process against tool patterns. Returns (display_name, category) or None."""
    effective_lower = effective.lower()
    for pattern in tool_patterns:
        exe = getattr(pattern, "exe", "").lower()
        if effective_lower == exe:
            return (getattr(pattern, "name", exe), getattr(pattern, "category", "") or "compiler")
    return None


def _match_system_category(
    proc: ProcLike,
    effective: str,
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
    for cat_name, cat_def in SYSTEM_CATEGORIES.items():
        if "match" in cat_def:
            fn = cat_def["match"]
            if callable(fn) and fn(proc):
                return cat_name
            continue
        exe_list_raw = cat_def.get("exe", [])
        exe_prefix_raw = cat_def.get("exe_prefix", [])
        exe_list = [e.lower() for e in (exe_list_raw if isinstance(exe_list_raw, list) else [])]
        exe_prefix = [p.lower() for p in (exe_prefix_raw if isinstance(exe_prefix_raw, list) else [])]
        if effective_lower in exe_list:
            return cat_name
        for prefix in exe_prefix:
            if effective_lower.startswith(prefix):
                return cat_name
    return None


def _ancestor_matches_app(
    pid: int,
    ppid_map: dict[int, int],
    pid_to_proc: dict[int, Any],
    effective_exe_map: dict[int, str],
    app_patterns: list,
    exe_to_app: dict[str, str],
    generic_set: set[str],
    terminal_exes: set[str],
    desktop_excluded: frozenset[str] = frozenset(),
) -> tuple[str, object] | None:
    """Walk up from PARENT; return (app_name, pattern) if any ancestor matches app.

    Starting from the parent (not the process itself) ensures that when a process
    directly matches an app pattern (e.g. codex), its own parent chain is checked
    first — so a Cursor-extension codex is attributed to Cursor, not Codex.
    A terminal exe in the chain cuts off the walk (returns None).
    """
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

    if exe_to_app is None:
        exe_to_app = {}
    generic_parents = getattr(config, "generic_parents", []) or []
    generic_set = {p.lower() for p in generic_parents}
    tr = getattr(config, "transparent_runtimes", None) or []
    transparent_runtimes = {str(r).lower() for r in (tr if isinstance(tr, list) else [])}

    app_patterns = list(getattr(config, "apps", []) or [])
    if not app_patterns:
        app_patterns = list(APP_PATTERNS)
    else:
        builtin_exes = {p.exe.lower() for p in APP_PATTERNS}
        for p in APP_PATTERNS:
            if p.exe.lower() not in {a.exe.lower() for a in app_patterns}:
                app_patterns.append(p)

    tool_patterns = list(getattr(config, "tools", []) or [])
    if not tool_patterns:
        tool_patterns = list(TOOL_PATTERNS)
    else:
        for p in TOOL_PATTERNS:
            if p.exe.lower() not in {t.exe.lower() for t in tool_patterns}:
                tool_patterns.append(p)

    category_overrides = getattr(config, "category_overrides", {}) or {}
    other_cpu_max = getattr(config, "other_cpu_max", 0.1) or 0.1
    other_mem_max = getattr(config, "other_mem_max", 30 << 20) or 30 << 20

    pid_to_proc: dict[int, ProcessInfo] = {p.pid: p for p in processes}
    ppid_map: dict[int, int] = {p.pid: p.ppid for p in processes}
    name_map: dict[int, str] = {}
    for p in processes:
        name_map[p.pid] = (p.exe or p.name or "").lower()
    effective_exe_map: dict[int, str] = {}
    for p in processes:
        effective_exe_map[p.pid] = _effective_exe(p, transparent_runtimes)

    terminal_exes = {
        "wezterm-gui", "alacritty", "kitty", "gnome-terminal",
        "konsole", "xterm",
    }

    # Build set of all exe names claimed by system categories so Layer 1
    # .desktop fallback doesn't steal them (e.g. picom, i3, nm-applet).
    system_exes: set[str] = set()
    for cat_def in SYSTEM_CATEGORIES.values():
        for e in cat_def.get("exe", []):  # type: ignore[union-attr]
            system_exes.add(e.lower())
    desktop_excluded: frozenset[str] = frozenset(system_exes | generic_set)

    # pid -> (layer, group_key)  group_key is "name:uid" or category name
    pid_to_assignment: dict[int, tuple[str, str]] = {}

    def assign(pid: int, layer: str, key: str) -> None:
        pid_to_assignment[pid] = (layer, key)

    def is_assigned(pid: int) -> bool:
        return pid in pid_to_assignment

    # Pids assigned to "agent"-family apps — Layer 2 must not reclaim these
    # as tool groups, so that compilers/builds spawned by TUI agents stay
    # attributed to the agent.
    agent_pids: set[int] = set()

    def _assign_app(pid: int, app_name: str, uid: int, pattern: object) -> None:
        assign(pid, "app", f"{app_name}:{uid}")
        if getattr(pattern, "family", "") == "agent":
            agent_pids.add(pid)

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

        # Ancestor check FIRST: if this process lives inside a known app's
        # subtree (walking up, stopping at terminal boundaries), attribute it
        # to that ancestor app.  This ensures e.g. a Cursor-extension "codex"
        # binary is kept under Cursor rather than stolen by an AppPattern for
        # the standalone Codex CLI.
        ancestor_match = _ancestor_matches_app(
            pid, ppid_map, pid_to_proc, effective_exe_map,
            app_patterns, exe_to_app, generic_set, terminal_exes,
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
                family = getattr(pattern, "family", "") or ""
                if family in ("electron", "chromium"):
                    if _is_electron_child(proc, getattr(pattern, "exe", "").lower()):
                        _assign_app(pid, app_name, uid, pattern)
                        continue
                    root_exe = effective_exe_map.get(pid, exe)
                    if root_exe == getattr(pattern, "exe", "").lower():
                        _assign_app(pid, app_name, uid, pattern)
                        continue
                elif family == "gecko":
                    if _is_gecko_child(proc, getattr(pattern, "exe", "").lower()):
                        _assign_app(pid, app_name, uid, pattern)
                        continue
                    if exe == getattr(pattern, "exe", "").lower():
                        _assign_app(pid, app_name, uid, pattern)
                        continue
            _assign_app(pid, app_name, uid, pattern or object())
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
                _assign_app(pid, root_match[0], uid, root_match[1] or object())
                continue

        if exe in terminal_exes:
            match = _match_app(exe, cmdline, app_patterns, exe_to_app, desktop_excluded)
            if match:
                _assign_app(pid, match[0], uid, match[1] or object())
                continue

    # Layer 2: Tool grouping (reclaims from Layer 1, but not agent app children)
    for proc in processes:
        pid = proc.pid
        if pid in agent_pids:
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
        cat = _match_system_category(proc, exe, category_overrides)
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


def _gecko_type_name(name: str, cmdline: str) -> str:
    """Use process name (comm) for Gecko sub-type."""
    name = (name or "").strip()
    if name:
        return name
    if "-contentproc" in (cmdline or ""):
        return "Web Content"
    return "Other"


def _build_subgroups(
    procs: list,
    key_fn,
    parent_group_key: str,
    user: str,
    category: str,
    ram_total_bytes: int,
) -> list[ProcessGroup]:
    """Build sub-groups from processes using key_fn to classify each proc."""
    by_key: dict[str, list] = {}
    for p in procs:
        k = key_fn(p)
        by_key.setdefault(k, []).append(p)
    children: list[ProcessGroup] = []
    for k, plist in by_key.items():
        cpu = sum(p.cpu_pct for p in plist)
        mem = sum(p.rss_bytes for p in plist)
        mem_pct = 100.0 * mem / ram_total_bytes if ram_total_bytes else 0.0
        sub_name = f"{k} ({len(plist)})" if len(plist) > 1 else k
        children.append(ProcessGroup(
            name=sub_name, proc_count=len(plist), cpu_pct=cpu,
            mem_bytes=mem, mem_pct=mem_pct, user=user,
            category=category, processes=plist, depth=1,
            group_key=f"{parent_group_key}|sub:{str(k).strip().lower()}",
        ))
    return children


def _build_hierarchy(
    groups: list[ProcessGroup],
    ram_total_bytes: int,
    config: object,
) -> list[ProcessGroup]:
    """Build children sub-groups for apps, tools, and system categories."""
    default_expanded = {
        str(x).lower()
        for x in (getattr(config, "default_expanded", None) or [])
    }
    expand_threshold = getattr(config, "expand_threshold", 0) or 0
    tr = getattr(config, "transparent_runtimes", None) or []
    transparent_runtimes: set[str] = {str(r).lower() for r in (tr if isinstance(tr, list) else [])}

    # Agent-family app names (TUI AI agents whose children should be labeled
    # by effective exe, not by Electron process type).
    agent_app_names = {
        p.name.lower() for p in APP_PATTERNS if getattr(p, "family", "") == "agent"
    }

    result: list[ProcessGroup] = []
    for g in groups:
        procs = g.processes or []
        children: list[ProcessGroup] = []

        if g.category == "app" and len(procs) > 1:
            exe_lower = (procs[0].exe or "").lower() if procs else ""
            if any(x in exe_lower for x in ["firefox", "thunderbird", "librewolf"]):
                children = _build_subgroups(
                    procs,
                    lambda p: _gecko_type_name(p.name or "", p.cmdline or ""),
                    g.group_key,
                    g.user, "app", ram_total_bytes,
                )
            elif g.name.lower() in agent_app_names:
                # TUI agents: label children by the actual command they run
                children = _build_subgroups(
                    procs,
                    lambda p, tr=transparent_runtimes: _effective_exe(p, tr) or _normalize_exe(p.exe or p.name or "unknown"),
                    g.group_key,
                    g.user, "app", ram_total_bytes,
                )
            else:
                children = _build_subgroups(
                    procs,
                    lambda p: _electron_type_name(p.cmdline or ""),
                    g.group_key,
                    g.user, "app", ram_total_bytes,
                )

        elif g.category == "tool" and len(procs) > 1:
            children = _build_subgroups(
                procs,
                lambda p: _normalize_exe(p.exe or p.name or "unknown"),
                g.group_key,
                g.user, "tool", ram_total_bytes,
            )

        elif g.category == "system" and len(procs) > 1 and g.name != "Kernel":
            children = _build_subgroups(
                procs,
                lambda p, tr=transparent_runtimes: _effective_exe(p, tr) or _normalize_exe(p.exe or p.name or "unknown"),
                g.group_key,
                g.user, "system", ram_total_bytes,
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
        kept.append(ProcessGroup(
            name=f"other ({n})",
            proc_count=n,
            cpu_pct=sum(g.cpu_pct for g in other),
            mem_bytes=sum(g.mem_bytes for g in other),
            mem_pct=sum(g.mem_pct for g in other),
            user="",
            category="other",
            group_key="other:bucket",
        ))
    return kept
