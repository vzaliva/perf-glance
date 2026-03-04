"""Cgroup parsing for systemd unit names."""

from __future__ import annotations

import re
from pathlib import Path


def get_cgroup_unit(pid: int) -> str | None:
    """Read /proc/<pid>/cgroup and extract systemd unit name if available.

    Returns e.g. "user@1000.service", "session-2.scope", or None.
    """
    path = Path(f"/proc/{pid}/cgroup")
    if not path.exists():
        return None
    try:
        content = path.read_text()
    except OSError:
        return None

    # cgroup v2: single line like "0::/user.slice/user-1000.slice/user@1000.service/..."
    # cgroup v1: multiple lines, we look for systemd
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 3:
            continue
        _, _, cpath = parts[0], parts[1], parts[2]
        if not cpath.startswith("/"):
            continue

        # Extract last non-empty segment that looks like a unit
        segments = [s for s in cpath.split("/") if s]
        for seg in reversed(segments):
            if "." in seg and re.match(r"^[a-z0-9@_.-]+\.(service|scope|slice)$", seg):
                return seg
            if seg.endswith(".service") or seg.endswith(".scope"):
                return seg
    return None
