"""CPU temperature collector via psutil sensors API."""

from __future__ import annotations

import psutil


def _read_psutil_sensors() -> float | None:
    """Read CPU temperature from psutil.sensors_temperatures()."""
    try:
        data = psutil.sensors_temperatures()
    except Exception:
        return None

    if not data:
        return None

    keys_pref = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")
    temps: list[float] = []

    for key in keys_pref:
        for item in data.get(key, []):
            label = (item.label or "").lower()
            if any(kw in label for kw in ("core", "package", "cpu", "tdie", "tctl")):
                temps.append(float(item.current))
            elif not label:
                temps.append(float(item.current))

    if not temps:
        for entries in data.values():
            for item in entries:
                label = (item.label or "").lower()
                if any(kw in label for kw in ("core", "package", "cpu", "tdie", "tctl")):
                    temps.append(float(item.current))

    if not temps:
        for entries in data.values():
            for item in entries:
                temps.append(float(item.current))

    return max(temps) if temps else None


def read_temperature() -> float | None:
    """Read CPU temperature in Celsius via psutil. Returns None if unavailable."""
    return _read_psutil_sensors()
