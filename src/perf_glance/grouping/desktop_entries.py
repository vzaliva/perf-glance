"""Scan .desktop files to build exe -> display name mapping."""

from __future__ import annotations

import re
from pathlib import Path


def _expand_path(path: str) -> Path:
    """Expand ~ to home directory."""
    if path.startswith("~"):
        return Path(path).expanduser()
    return Path(path)


def _parse_exec(exec_line: str) -> str:
    """Extract executable basename from Exec= line.

    Strips: %u, %F, %f, %i, %c, %k, env VAR=value prefix, path.
    """
    if not exec_line or not exec_line.strip():
        return ""
    # Strip "env" command prefix (e.g. "env VAR=1 /usr/bin/app")
    remaining = exec_line.strip()
    if remaining.split()[0] in ("env", "/usr/bin/env"):
        remaining = remaining.split(None, 1)[1] if " " in remaining else ""
    # Strip env vars at start (VAR=value VAR2=value2 command)
    while remaining:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)", remaining)
        if match:
            value = match.group(2)
            # Value may be quoted
            if value.startswith('"') and '"' in value[1:]:
                end = value.index('"', 1) + 1
                remaining = value[end:].lstrip()
            elif value.startswith("'") and "'" in value[1:]:
                end = value.index("'", 1) + 1
                remaining = value[end:].lstrip()
            else:
                parts = value.split(None, 1)
                remaining = parts[1] if len(parts) > 1 else ""
            continue
        break
    # First token is the command (possibly with path)
    parts = remaining.split()
    if not parts:
        return ""
    cmd = parts[0]
    # Strip desktop file placeholders
    cmd = re.sub(r"%[uUfFdDnNikvc]", "", cmd)
    cmd = cmd.strip()
    if not cmd:
        return ""
    # Basename only
    if "/" in cmd:
        cmd = cmd.split("/")[-1]
    return cmd


def _parse_desktop_file(path: Path) -> tuple[str, str, str] | None:
    """Parse a .desktop file, return (exe_basename, display_name, startup_wm_class) or None."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_desktop_entry = False
    exec_val = ""
    name_val = ""
    wmclass_val = ""
    for line in content.splitlines():
        line = line.strip()
        if line == "[Desktop Entry]":
            in_desktop_entry = True
            continue
        if in_desktop_entry and line.startswith("["):
            break
        if not in_desktop_entry:
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip().lower()
            val = val.strip()
            if key == "exec":
                exec_val = val
            elif key == "name":
                name_val = val
            elif key == "startupwmclass":
                wmclass_val = val
    exe = _parse_exec(exec_val)
    if not exe:
        return None
    display = name_val or exe
    # Return exe, display, and optionally StartupWMClass for secondary mapping
    return (exe.lower(), display, wmclass_val.lower() if wmclass_val else "")


def scan_desktop_entries(dirs: list[str]) -> dict[str, str]:
    """Scan .desktop files in given directories.

    Returns dict mapping exe basename (lowercase) -> human-readable display name.
    Later files override earlier ones for the same exe.
    """
    result: dict[str, str] = {}
    seen_dirs: set[Path] = set()
    for dir_spec in dirs:
        base = _expand_path(dir_spec)
        if not base.is_dir() or base in seen_dirs:
            continue
        seen_dirs.add(base)
        for path in base.glob("*.desktop"):
            if not path.is_file():
                continue
            parsed = _parse_desktop_file(path)
            if parsed:
                exe, display, wmclass = parsed
                result[exe] = display
                if path.stem.lower() != exe:
                    result[path.stem.lower()] = display
                if wmclass:
                    result[wmclass] = display
    return result
