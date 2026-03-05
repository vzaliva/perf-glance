"""CPU temperature collector — macOS. Returns None (no unprivileged API)."""

from __future__ import annotations


def read_temperature() -> float | None:
    """Read CPU temperature. Not available on macOS without elevated privileges."""
    return None
