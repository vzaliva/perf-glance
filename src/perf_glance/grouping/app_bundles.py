"""macOS .app bundle name resolution from process exe paths."""

from __future__ import annotations

import plistlib
import re
from pathlib import Path

# Matches the bundle directory component in an exe path, e.g.:
#   /Applications/Firefox.app/Contents/MacOS/firefox
#   /Library/Foo/Bar.appex/Contents/MacOS/helper
_APP_BUNDLE_RE = re.compile(r"/([^/]+\.app(?:ex)?)/Contents/")

# Cache: absolute bundle path → display name (empty string = no name found)
_bundle_cache: dict[str, str] = {}


def bundle_name_from_exe_path(exe_path: str) -> str | None:
    """Extract the app display name from a macOS exe path.

    Finds the .app or .appex bundle component, reads CFBundleName from
    Info.plist (result cached per bundle path), and falls back to the
    bundle directory name without the extension.

    Returns None if exe_path is not inside a recognisable bundle.
    """
    if not exe_path:
        return None
    m = _APP_BUNDLE_RE.search(exe_path)
    if not m:
        return None

    bundle_dir = m.group(1)  # e.g. "Firefox.app"
    bundle_path = exe_path[: m.start() + 1 + len(bundle_dir)]  # "/Applications/Firefox.app"

    if bundle_path in _bundle_cache:
        return _bundle_cache[bundle_path] or None

    display = ""
    try:
        plist_path = Path(bundle_path) / "Contents" / "Info.plist"
        if plist_path.exists():
            with plist_path.open("rb") as f:
                info = plistlib.load(f)
            display = (
                info.get("CFBundleName")
                or info.get("CFBundleDisplayName")
                or ""
            )
    except Exception:
        pass

    if not display:
        ext_len = 6 if bundle_dir.endswith(".appex") else 4
        display = bundle_dir[:-ext_len]

    _bundle_cache[bundle_path] = display
    return display or None


def update_bundle_map(processes: list, mapping: dict[str, str]) -> None:
    """Populate mapping with exe→display-name for processes inside .app bundles.

    Only adds entries for exe keys not already present — explicit TOML rules
    (which pre-populate mapping before this is called) take priority.
    Mutates mapping in-place; safe to call every tick (cached after first lookup).
    """
    for proc in processes:
        exe_path = getattr(proc, "exe_path", "")
        if not exe_path:
            continue
        exe_key = (getattr(proc, "exe", "") or "").strip().lower()
        if not exe_key or exe_key in mapping:
            continue
        name = bundle_name_from_exe_path(exe_path)
        if name:
            mapping[exe_key] = name
