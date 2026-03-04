"""Tests for process grouping."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest


@dataclass
class MockProcess:
    pid: int
    ppid: int
    name: str
    exe: str
    cpu_pct: float
    rss_bytes: int
    cmdline: str
    uid: int = 0
    starttime_ticks: int = 0


def _minimal_config(
    generic_parents: list[str] | None = None,
    tools: list | None = None,
    force_name_group: list[str] | None = None,
    transparent_runtimes: list[str] | None = None,
    category_overrides: dict[str, str] | None = None,
    default_expanded: list[str] | None = None,
    expand_threshold: int = 0,
) -> SimpleNamespace:
    """Create minimal config for group_processes."""
    return SimpleNamespace(
        generic_parents=generic_parents or ["systemd", "init", "bash", "sh"],
        transparent_runtimes=transparent_runtimes or [],
        apps=[],
        tools=tools or [],
        category_overrides=category_overrides or {},
        other_cpu_max=0.1,
        other_mem_max=30 << 20,
        force_name_group=force_name_group or [],
        default_expanded=default_expanded or [],
        expand_threshold=expand_threshold,
    )


RAM = 1_000_000_000  # 1 GB


# ── Layer 1: App recognition ────────────────────────────────────────────

def test_group_processes_basic() -> None:
    """Basic grouping produces ProcessGroups."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "firefox", "firefox", 5.0, 100_000_000, "firefox"),
        MockProcess(11, 10, "Web Content", "firefox", 3.0, 50_000_000, "firefox -contentproc ..."),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    assert len(groups) >= 1
    assert any("firefox" in g.name.lower() for g in groups)


def test_electron_app_grouped() -> None:
    """Electron app processes (main + utility + renderer) grouped together."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(100, 1, "cursor", "cursor", 2.0, 200_000_000, "/usr/share/cursor/cursor"),
        MockProcess(101, 100, "cursor", "cursor", 1.0, 100_000_000, "cursor --type=renderer --crashpad-handler-pid=100"),
        MockProcess(102, 100, "cursor", "cursor", 0.5, 50_000_000, "cursor --type=utility"),
        MockProcess(103, 100, "cursor", "cursor", 0.5, 50_000_000, "cursor --type=gpu-process"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    cursor_groups = [g for g in groups if "cursor" in g.name.lower()]
    assert len(cursor_groups) == 1
    assert cursor_groups[0].proc_count == 4
    assert cursor_groups[0].cpu_pct == pytest.approx(4.0)


def test_gecko_app_grouped() -> None:
    """Firefox/Gecko processes grouped by -contentproc cmdline."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "firefox", "firefox", 2.0, 200_000_000, "/usr/bin/firefox"),
        MockProcess(11, 10, "Web Content", "firefox", 1.0, 100_000_000, "firefox -contentproc -isForBrowser ..."),
        MockProcess(12, 10, "Isolated Web Co", "firefox", 0.8, 80_000_000, "firefox -contentproc -isForBrowser ..."),
        MockProcess(13, 10, "WebExtensions", "firefox", 0.2, 40_000_000, "firefox -contentproc -isForBrowser ..."),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    ff = [g for g in groups if "firefox" in g.name.lower()]
    assert len(ff) == 1
    assert ff[0].proc_count == 4


def test_desktop_entry_app_match() -> None:
    """App matched via exe_to_app (desktop entry scan) gets proper name."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "my-custom-app", "my-custom-app", 1.0, 50_000_000, "my-custom-app --some-flag"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, exe_to_app={"my-custom-app": "My Custom App"})
    assert any("My Custom App" in g.name for g in groups)


def test_terminal_children_independent() -> None:
    """Terminals (wezterm-gui) don't absorb their shell children."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(100, 1, "wezterm-gui", "wezterm-gui", 0.5, 100_000_000, "wezterm-gui"),
        MockProcess(101, 100, "fish", "fish", 0.1, 10_000_000, "fish"),
        MockProcess(102, 101, "vim", "vim", 0.3, 30_000_000, "vim file.py"),
    ]
    config = _minimal_config(generic_parents=["systemd", "init", "bash", "sh", "fish"])
    groups = group_processes(processes, RAM, config, None)
    wezterm = [g for g in groups if "wezterm" in g.name.lower()]
    assert len(wezterm) == 1
    # vim should NOT be inside the WezTerm group
    assert wezterm[0].proc_count <= 1 or not any(
        p.name == "vim" for p in (wezterm[0].processes or [])
    )


def test_multi_user_same_app() -> None:
    """Same app by different UIDs forms separate groups."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "firefox", "firefox", 5.0, 200_000_000, "firefox", uid=1000),
        MockProcess(20, 1, "firefox", "firefox", 3.0, 150_000_000, "firefox", uid=1001),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    ff = [g for g in groups if "firefox" in g.name.lower()]
    # Should be 2 separate groups (different users)
    assert len(ff) == 2


# ── Layer 2: Tool grouping ──────────────────────────────────────────────

def test_force_name_group() -> None:
    """force_name_group (migrated to tools) groups by exe regardless of tree."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(100, 50, "cc1", "cc1", 10.0, 50_000_000, "cc1"),
        MockProcess(101, 60, "cc1", "cc1", 12.0, 60_000_000, "cc1"),
    ]
    config = _minimal_config(force_name_group=["cc1"])
    groups = group_processes(processes, RAM, config, None)
    assert len(groups) == 1
    assert groups[0].proc_count == 2
    assert groups[0].cpu_pct == 22.0
    assert groups[0].mem_bytes == 110_000_000


def test_tool_reclaim_from_app() -> None:
    """Layer 2 tools reclaim processes from Layer 1 tree."""
    from perf_glance.grouping.process_groups import group_processes

    # cursor (app) -> bash -> lake (tool): lake should go to tool group, not Cursor
    processes = [
        MockProcess(100, 1, "cursor", "cursor", 1.0, 100_000_000, "cursor"),
        MockProcess(101, 100, "bash", "bash", 0.1, 10_000_000, "bash"),
        MockProcess(102, 101, "lake", "lake", 50.0, 200_000_000, "lake build"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    tool_groups = [g for g in groups if g.category == "tool"]
    assert len(tool_groups) >= 1
    assert any("ake" in g.name for g in groups)


def test_tool_build_label() -> None:
    """Multiple tool procs get 'build (N procs)' label."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(i, 1, "lean", "lean", 5.0, 50_000_000, f"lean file{i}.lean")
        for i in range(10, 15)
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    lean = [g for g in groups if "lean" in g.name.lower()]
    assert len(lean) == 1
    assert "build" in lean[0].name.lower()
    assert lean[0].proc_count == 5


def test_lean_coq_ocaml_patterns() -> None:
    """Built-in patterns recognize Lean, Coq/Rocq, OCaml tools."""
    from perf_glance.grouping.patterns import TOOL_PATTERNS

    tool_exes = {p.exe.lower() for p in TOOL_PATTERNS}
    for exe in ["lean", "lake", "leanc", "coqc", "coqtop", "rocq", "rocqc",
                "ocamlopt", "ocamlc", "dune", "opam"]:
        assert exe in tool_exes, f"{exe} not in TOOL_PATTERNS"


# ── Layer 3: System categories ──────────────────────────────────────────

def test_kernel_threads() -> None:
    """Processes with empty cmdline are grouped as Kernel."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(2, 0, "kthreadd", "kthreadd", 0.0, 0, ""),
        MockProcess(10, 2, "kworker/0:0", "", 0.1, 0, ""),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    kernel = [g for g in groups if g.name == "Kernel"]
    assert len(kernel) == 1
    assert kernel[0].proc_count == 2


def test_system_categories() -> None:
    """Processes matching system category exe lists get categorized."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "pipewire", "pipewire", 0.5, 20_000_000, "pipewire"),
        MockProcess(11, 1, "wireplumber", "wireplumber", 0.3, 15_000_000, "wireplumber"),
        MockProcess(20, 1, "NetworkManager", "NetworkManager", 0.2, 30_000_000, "NetworkManager"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    audio = [g for g in groups if g.name == "Audio"]
    network = [g for g in groups if g.name == "Network"]
    assert len(audio) == 1
    assert audio[0].proc_count == 2
    assert len(network) == 1
    assert network[0].proc_count == 1


def test_system_category_prefix_match() -> None:
    """exe_prefix matching (e.g. gvfsd-*) works."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "gvfsd-fuse", "gvfsd-fuse", 0.0, 5_000_000, "gvfsd-fuse"),
        MockProcess(11, 1, "gvfsd-metadata", "gvfsd-metadata", 0.0, 5_000_000, "gvfsd-metadata"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    fs = [g for g in groups if g.name == "File Services"]
    assert len(fs) == 1
    assert fs[0].proc_count == 2


def test_category_override() -> None:
    """category_overrides moves a process to a different category."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "my-daemon", "my-daemon", 0.5, 20_000_000, "my-daemon"),
    ]
    config = _minimal_config(category_overrides={"my-daemon": "Network"})
    groups = group_processes(processes, RAM, config, None)
    network = [g for g in groups if g.name == "Network"]
    assert len(network) == 1


def test_category_override_exclude() -> None:
    """category_overrides with empty string excludes from all categories."""
    from perf_glance.grouping.process_groups import group_processes

    # pipewire normally goes to Audio; override to "" excludes it
    processes = [
        MockProcess(10, 1, "pipewire", "pipewire", 0.5, 20_000_000, "pipewire"),
    ]
    config = _minimal_config(category_overrides={"pipewire": ""})
    groups = group_processes(processes, RAM, config, None)
    audio = [g for g in groups if g.name == "Audio"]
    assert len(audio) == 0


# ── Runtime transparency ────────────────────────────────────────────────

def test_runtime_transparency() -> None:
    """Python/node processes use script name as effective exe."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "myscript", "myscript", 0.5, 20_000_000, "myscript"),
        MockProcess(
            11, 1, "python3", "python3", 1.0, 50_000_000,
            "/usr/bin/python3 /usr/bin/myscript",
        ),
    ]
    config = _minimal_config(transparent_runtimes=["python3", "python"])
    groups = group_processes(processes, RAM, config, None)
    myscript = [g for g in groups if "myscript" in g.name.lower()]
    assert len(myscript) == 1
    assert myscript[0].proc_count == 2


def test_runtime_transparency_system_category() -> None:
    """Python script matched to system category via transparent runtime."""
    from perf_glance.grouping.process_groups import group_processes

    # blueman-tray runs as python3 but should match Bluetooth category
    processes = [
        MockProcess(10, 1, "python3", "python3", 0.1, 10_000_000,
                    "/usr/bin/python3 /usr/bin/blueman-tray"),
    ]
    config = _minimal_config(transparent_runtimes=["python3"])
    groups = group_processes(processes, RAM, config, None)
    bt = [g for g in groups if g.name == "Bluetooth"]
    assert len(bt) == 1


# ── Post-processing ─────────────────────────────────────────────────────

def test_dedup_same_name_same_user() -> None:
    """Groups with same name and user are merged."""
    from perf_glance.grouping.process_groups import group_processes

    # Two separate process trees that both resolve to the same catch-all exe name
    processes = [
        MockProcess(10, 1, "myapp", "myapp", 5.0, 100_000_000, "myapp instance1"),
        MockProcess(20, 1, "myapp", "myapp", 3.0, 80_000_000, "myapp instance2"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    myapp = [g for g in groups if "myapp" in g.name.lower()]
    assert len(myapp) == 1
    assert myapp[0].proc_count == 2
    assert myapp[0].cpu_pct == pytest.approx(8.0)


def test_other_bucket() -> None:
    """Low-activity catch-all processes bucketed into 'other (N)'."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "tiny1", "tiny1", 0.01, 1_000_000, "tiny1"),
        MockProcess(11, 1, "tiny2", "tiny2", 0.02, 2_000_000, "tiny2"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    other = [g for g in groups if g.name.startswith("other")]
    assert len(other) == 1
    assert other[0].proc_count == 2


# ── Hierarchy building ──────────────────────────────────────────────────

def test_app_hierarchy_electron() -> None:
    """Electron app group has children by subprocess type."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(100, 1, "cursor", "cursor", 2.0, 200_000_000, "/usr/share/cursor/cursor"),
        MockProcess(101, 100, "cursor", "cursor", 1.0, 100_000_000, "cursor --type=renderer"),
        MockProcess(102, 100, "cursor", "cursor", 0.5, 50_000_000, "cursor --type=utility"),
        MockProcess(103, 100, "cursor", "cursor", 0.3, 30_000_000, "cursor --type=gpu-process"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    cursor = [g for g in groups if "cursor" in g.name.lower()]
    assert len(cursor) == 1
    assert len(cursor[0].children) >= 3  # Main, Web Content, Utility, GPU


def test_app_hierarchy_gecko() -> None:
    """Gecko app group has children by process name."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "firefox", "firefox", 2.0, 200_000_000, "firefox"),
        MockProcess(11, 10, "Web Content", "firefox", 1.0, 100_000_000, "firefox -contentproc"),
        MockProcess(12, 10, "Web Content", "firefox", 1.5, 80_000_000, "firefox -contentproc"),
        MockProcess(13, 10, "WebExtensions", "firefox", 0.2, 40_000_000, "firefox -contentproc"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    ff = [g for g in groups if "firefox" in g.name.lower()]
    assert len(ff) == 1
    assert len(ff[0].children) >= 2  # Web Content, WebExtensions (+firefox main)
    child_names = {c.name.split(" (")[0] for c in ff[0].children}
    assert "Web Content" in child_names or any("Web Content" in n for n in child_names)


def test_tool_hierarchy() -> None:
    """Tool groups with multiple procs get children by exe."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "lean", "lean", 10.0, 100_000_000, "lean file1.lean"),
        MockProcess(11, 1, "lean", "lean", 8.0, 80_000_000, "lean file2.lean"),
        MockProcess(12, 1, "lake", "lake", 1.0, 20_000_000, "lake build"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    tool = [g for g in groups if g.category == "tool"]
    # lean and lake should be in tool groups (possibly merged)
    assert len(tool) >= 1
    # At least one tool group should have children
    has_children = any(len(g.children) > 0 for g in tool)
    assert has_children


def test_system_hierarchy() -> None:
    """System category with multiple procs gets children by exe."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "pipewire", "pipewire", 0.5, 20_000_000, "pipewire"),
        MockProcess(11, 1, "wireplumber", "wireplumber", 0.3, 15_000_000, "wireplumber"),
        MockProcess(12, 1, "pipewire-pulse", "pipewire-pulse", 0.2, 10_000_000, "pipewire-pulse"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    audio = [g for g in groups if g.name == "Audio"]
    assert len(audio) == 1
    assert len(audio[0].children) == 3


def test_group_keys_present_for_top_level_and_children() -> None:
    """Grouping assigns stable group_key to top-level rows and hierarchy children."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(100, 1, "cursor", "cursor", 2.0, 200_000_000, "/usr/share/cursor/cursor"),
        MockProcess(101, 100, "cursor", "cursor", 1.0, 100_000_000, "cursor --type=renderer"),
        MockProcess(102, 100, "cursor", "cursor", 0.5, 50_000_000, "cursor --type=utility"),
    ]
    config = _minimal_config()
    groups = group_processes(processes, RAM, config, None)
    assert len(groups) >= 1
    for g in groups:
        assert g.group_key
        for c in g.children:
            assert c.group_key
            assert c.group_key.startswith(g.group_key + "|sub:")


def test_default_expanded_config() -> None:
    """Groups named in default_expanded start expanded."""
    from perf_glance.grouping.process_groups import group_processes

    processes = [
        MockProcess(10, 1, "pipewire", "pipewire", 0.5, 20_000_000, "pipewire"),
        MockProcess(11, 1, "wireplumber", "wireplumber", 0.3, 15_000_000, "wireplumber"),
    ]
    config = _minimal_config(default_expanded=["audio"])
    groups = group_processes(processes, RAM, config, None)
    audio = [g for g in groups if g.name == "Audio"]
    assert len(audio) == 1
    assert audio[0].expanded is True


# ── Desktop entry scanning ──────────────────────────────────────────────

def test_parse_exec_basic() -> None:
    """_parse_exec extracts exe basename."""
    from perf_glance.grouping.desktop_entries import _parse_exec

    assert _parse_exec("/usr/bin/firefox %u") == "firefox"
    assert _parse_exec("/usr/share/cursor/cursor %U") == "cursor"
    assert _parse_exec("env VAR=1 /usr/bin/myapp") == "myapp"
    assert _parse_exec("") == ""


def test_parse_exec_env_prefix() -> None:
    """_parse_exec handles env VAR=value prefixes."""
    from perf_glance.grouping.desktop_entries import _parse_exec

    assert _parse_exec('GDK_BACKEND=x11 /usr/bin/slack %U') == "slack"


def test_scan_desktop_entries_nonexistent_dir() -> None:
    """Scanning a nonexistent directory returns empty dict."""
    from perf_glance.grouping.desktop_entries import scan_desktop_entries

    result = scan_desktop_entries(["/nonexistent/path/12345"])
    assert result == {}


def test_scan_desktop_entries_real(tmp_path) -> None:
    """Scanning a directory with .desktop files returns exe->name mapping."""
    from perf_glance.grouping.desktop_entries import scan_desktop_entries

    desktop = tmp_path / "test.desktop"
    desktop.write_text(
        "[Desktop Entry]\nName=Test App\nExec=/usr/bin/testapp %F\nType=Application\n"
    )
    result = scan_desktop_entries([str(tmp_path)])
    assert "testapp" in result
    assert result["testapp"] == "Test App"


# ── Flatten / expand helpers ────────────────────────────────────────────

def test_flatten_collapsed() -> None:
    """Collapsed groups only show top level."""
    from perf_glance.widgets.process_section import _flatten_groups
    from perf_glance.grouping.process_groups import ProcessGroup

    parent = ProcessGroup(
        name="Firefox", proc_count=5, cpu_pct=3.0, mem_bytes=100,
        mem_pct=1.0, children=[
            ProcessGroup(name="Web Content", proc_count=3, cpu_pct=2.0, mem_bytes=60, mem_pct=0.6),
            ProcessGroup(name="GPU", proc_count=1, cpu_pct=0.5, mem_bytes=20, mem_pct=0.2),
        ],
        expanded=False,
    )
    flat = _flatten_groups([parent])
    assert len(flat) == 1
    assert flat[0][0].name == "Firefox"
    assert flat[0][1] == 0  # depth


def test_flatten_expanded() -> None:
    """Expanded groups show children."""
    from perf_glance.widgets.process_section import _flatten_groups
    from perf_glance.grouping.process_groups import ProcessGroup

    parent = ProcessGroup(
        name="Firefox", proc_count=5, cpu_pct=3.0, mem_bytes=100,
        mem_pct=1.0, children=[
            ProcessGroup(name="Web Content", proc_count=3, cpu_pct=2.0, mem_bytes=60, mem_pct=0.6),
            ProcessGroup(name="GPU", proc_count=1, cpu_pct=0.5, mem_bytes=20, mem_pct=0.2),
        ],
        expanded=True,
    )
    flat = _flatten_groups([parent])
    assert len(flat) == 3
    assert flat[0][0].name == "Firefox"
    assert flat[0][1] == 0
    assert flat[1][0].name == "Web Content"
    assert flat[1][1] == 1
    assert flat[2][0].name == "GPU"
    assert flat[2][1] == 1


def test_flatten_text_filter() -> None:
    """Text filter narrows visible rows."""
    from perf_glance.widgets.process_section import _flatten_groups
    from perf_glance.grouping.process_groups import ProcessGroup

    groups = [
        ProcessGroup(name="Firefox", proc_count=5, cpu_pct=3.0, mem_bytes=100, mem_pct=1.0),
        ProcessGroup(name="Cursor", proc_count=3, cpu_pct=1.0, mem_bytes=50, mem_pct=0.5),
    ]
    flat = _flatten_groups(groups, text_filter="fire")
    assert len(flat) == 1
    assert flat[0][0].name == "Firefox"


# ── Config parsing ──────────────────────────────────────────────────────

def test_parse_bytes() -> None:
    """_parse_bytes handles M/G/K suffixes."""
    from perf_glance.config import _parse_bytes

    assert _parse_bytes("30M") == 30 << 20
    assert _parse_bytes("1G") == 1 << 30
    assert _parse_bytes("512K") == 512 << 10
    assert _parse_bytes("1024") == 1024
    assert _parse_bytes("") == 30 << 20  # default


def test_config_grouping_defaults() -> None:
    """Default GroupingConfig has expected values."""
    from perf_glance.config import GroupingConfig, DEFAULT_GENERIC_PARENTS, DEFAULT_TRANSPARENT_RUNTIMES

    gc = GroupingConfig()
    assert "bash" in gc.generic_parents
    assert "python3" in gc.transparent_runtimes
    assert gc.other_cpu_max == 0.1


# ── Effective exe resolution ────────────────────────────────────────────

def test_effective_exe_normal() -> None:
    """Non-runtime exe returns as-is (lowercased)."""
    from perf_glance.grouping.process_groups import _effective_exe

    proc = MockProcess(1, 0, "firefox", "firefox", 0, 0, "firefox")
    assert _effective_exe(proc, set()) == "firefox"


def test_effective_exe_transparent_runtime() -> None:
    """Transparent runtime resolves to script name."""
    from perf_glance.grouping.process_groups import _effective_exe

    proc = MockProcess(1, 0, "python3", "python3", 0, 0, "/usr/bin/python3 /usr/bin/blueman-tray")
    assert _effective_exe(proc, {"python3"}) == "blueman-tray"


def test_effective_exe_runtime_no_args() -> None:
    """Transparent runtime with no script arg returns runtime name."""
    from perf_glance.grouping.process_groups import _effective_exe

    proc = MockProcess(1, 0, "python3", "python3", 0, 0, "python3")
    assert _effective_exe(proc, {"python3"}) == "python3"
