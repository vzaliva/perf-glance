"""CPU temperature collector via hwmon or sensors."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _read_hwmon() -> float | None:
    """Read CPU temperature from /sys/class/hwmon. Prefer Core/Package/CPU labels."""
    hwmon = Path("/sys/class/hwmon")
    if not hwmon.exists():
        return None

    candidates: list[tuple[float, str]] = []

    for hdir in hwmon.iterdir():
        if not hdir.is_dir():
            continue
        for temp_input in hdir.glob("temp*_input"):
            if not temp_input.exists():
                continue
            try:
                val = int(temp_input.read_text().strip())
                temp_c = val / 1000  # millidegree -> Celsius
            except (ValueError, OSError):
                continue
            label_path = temp_input.with_name(
                temp_input.name.replace("_input", "_label")
            )
            label = ""
            if label_path.exists():
                label = label_path.read_text().strip().lower()
            candidates.append((temp_c, label))

    if not candidates:
        return None

    # Prefer labels containing core, package, cpu
    for temp_c, label in candidates:
        if any(kw in label for kw in ("core", "package", "cpu", "tdie", "tctl")):
            return temp_c

    # Fallback: first (or max) temperature
    return max(c[0] for c in candidates)


def _read_sensors() -> float | None:
    """Fallback: parse output of sensors (lm-sensors) for CPU temp."""
    try:
        out = subprocess.run(
            ["sensors"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if out.returncode != 0:
        return None

    # Look for patterns like "Core 0:       +45.0°C" or "Package id 0:  +50.0°C"
    pattern = re.compile(r"^\s*(?:Core|Package|Tctl|Tdie|CPU).*?([+-]?\d+\.?\d*)\s*°?C", re.I)
    temps: list[float] = []
    for line in out.stdout.splitlines():
        m = re.search(r"([+-]?\d+\.?\d*)\s*°?C", line)
        if m and any(kw in line.lower() for kw in ("core", "package", "cpu", "tdie", "tctl")):
            try:
                temps.append(float(m.group(1)))
            except ValueError:
                pass
    return max(temps) if temps else None


def read_temperature() -> float | None:
    """Read CPU temperature in Celsius. Tries hwmon first, then sensors. Returns None if unavailable."""
    return _read_hwmon() or _read_sensors()
