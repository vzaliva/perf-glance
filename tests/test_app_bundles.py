"""Tests for macOS .app bundle name resolution."""

from __future__ import annotations

import plistlib
from pathlib import Path
from types import SimpleNamespace


def _make_bundle(base: Path, bundle_name: str, bundle_display: str = "", exe: str = "app") -> Path:
    """Create a minimal .app bundle under base. Returns the MacOS exe path."""
    contents = base / f"{bundle_name}.app" / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    plist: dict = {"CFBundleExecutable": exe}
    if bundle_display:
        plist["CFBundleName"] = bundle_display
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump(plist, f)
    exe_path = macos / exe
    exe_path.touch()
    return exe_path


def _clear_cache() -> None:
    from perf_glance.grouping import app_bundles
    app_bundles._bundle_cache.clear()


def test_bundle_name_from_exe_path_reads_plist(tmp_path: Path) -> None:
    """Reads CFBundleName from Info.plist."""
    _clear_cache()
    exe_path = _make_bundle(tmp_path, "Firefox", bundle_display="Firefox")
    from perf_glance.grouping.app_bundles import bundle_name_from_exe_path
    assert bundle_name_from_exe_path(str(exe_path)) == "Firefox"


def test_bundle_name_falls_back_to_dir_name(tmp_path: Path) -> None:
    """Falls back to bundle directory name when plist has no CFBundleName."""
    _clear_cache()
    contents = tmp_path / "MyApp.app" / "Contents" / "MacOS"
    contents.mkdir(parents=True)
    # Plist without CFBundleName
    with (tmp_path / "MyApp.app" / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleExecutable": "myapp"}, f)
    from perf_glance.grouping.app_bundles import bundle_name_from_exe_path
    result = bundle_name_from_exe_path(str(contents / "myapp"))
    assert result == "MyApp"


def test_bundle_name_returns_none_for_non_bundle(tmp_path: Path) -> None:
    """Returns None for paths not inside a .app bundle."""
    _clear_cache()
    from perf_glance.grouping.app_bundles import bundle_name_from_exe_path
    assert bundle_name_from_exe_path("/usr/bin/python3") is None
    assert bundle_name_from_exe_path("") is None


def test_bundle_name_handles_appex(tmp_path: Path) -> None:
    """Handles .appex extension bundles (app extensions)."""
    _clear_cache()
    contents = tmp_path / "Helper.appex" / "Contents" / "MacOS"
    contents.mkdir(parents=True)
    with (tmp_path / "Helper.appex" / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleExecutable": "helper", "CFBundleName": "My Helper"}, f)
    from perf_glance.grouping.app_bundles import bundle_name_from_exe_path
    assert bundle_name_from_exe_path(str(contents / "helper")) == "My Helper"


def test_bundle_name_is_cached(tmp_path: Path) -> None:
    """Second call for same bundle path uses cache, not filesystem."""
    _clear_cache()
    exe_path = _make_bundle(tmp_path, "Cached", bundle_display="Cached App")
    from perf_glance.grouping import app_bundles

    first = app_bundles.bundle_name_from_exe_path(str(exe_path))
    # Delete plist — second call must still succeed from cache
    (tmp_path / "Cached.app" / "Contents" / "Info.plist").unlink()
    second = app_bundles.bundle_name_from_exe_path(str(exe_path))
    assert first == second == "Cached App"


def test_update_bundle_map_adds_entries(tmp_path: Path) -> None:
    """update_bundle_map populates mapping from process exe_paths."""
    _clear_cache()
    exe_path = _make_bundle(tmp_path, "Firefox", bundle_display="Firefox", exe="firefox")
    proc = SimpleNamespace(exe="firefox", exe_path=str(exe_path))

    from perf_glance.grouping.app_bundles import update_bundle_map
    mapping: dict[str, str] = {}
    update_bundle_map([proc], mapping)
    assert mapping.get("firefox") == "Firefox"


def test_update_bundle_map_does_not_overwrite(tmp_path: Path) -> None:
    """Existing mapping entries (TOML rules) are not overwritten."""
    _clear_cache()
    exe_path = _make_bundle(tmp_path, "Firefox", bundle_display="Firefox", exe="firefox")
    proc = SimpleNamespace(exe="firefox", exe_path=str(exe_path))

    from perf_glance.grouping.app_bundles import update_bundle_map
    mapping = {"firefox": "Mozilla Firefox"}  # pre-existing rule
    update_bundle_map([proc], mapping)
    assert mapping["firefox"] == "Mozilla Firefox"


def test_update_bundle_map_skips_no_exe_path(tmp_path: Path) -> None:
    """Processes without exe_path are silently skipped."""
    _clear_cache()
    proc = SimpleNamespace(exe="somebinary", exe_path="")
    from perf_glance.grouping.app_bundles import update_bundle_map
    mapping: dict[str, str] = {}
    update_bundle_map([proc], mapping)
    assert mapping == {}
