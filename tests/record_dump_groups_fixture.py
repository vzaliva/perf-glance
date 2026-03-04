"""Record a deterministic dump-groups fixture from current system state.

Usage:
    PYTHONPATH=src .venv/bin/python tests/record_dump_groups_fixture.py
"""

from __future__ import annotations

import argparse
import io
import json
import os
import pwd
from datetime import datetime, timezone
from pathlib import Path

from perf_glance.collectors import get_aggregate_cpu_times, read_memory, read_processes
from perf_glance.config import load_config
from perf_glance.dump_groups import dump_group_tree
from perf_glance.grouping import group_processes
from perf_glance.grouping.desktop_entries import scan_desktop_entries
from perf_glance.grouping.rules_loader import LauncherRule, SystemCategory


def _serialize_grouping_config(cfg: object) -> dict:
    apps = []
    for p in getattr(cfg, "apps", []) or []:
        apps.append({
            "exe": str(getattr(p, "exe", "")),
            "name": str(getattr(p, "name", "")),
            "family": str(getattr(p, "family", "")),
            "cmdline": str(getattr(p, "cmdline", "")),
        })

    tools = []
    for p in getattr(cfg, "tools", []) or []:
        tools.append({
            "exe": str(getattr(p, "exe", "")),
            "name": str(getattr(p, "name", "")),
            "category": str(getattr(p, "category", "")),
        })

    system_categories = []
    for c in getattr(cfg, "system_categories", []) or []:
        if not isinstance(c, SystemCategory):
            continue
        system_categories.append({
            "id": c.id,
            "name": c.name,
            "exe": list(c.exe),
            "exe_prefix": list(c.exe_prefix),
        })

    launchers: dict[str, list[dict]] = {}
    for exe, rules in (getattr(cfg, "launchers_by_exe", {}) or {}).items():
        launchers[str(exe)] = []
        for rule in rules:
            if not isinstance(rule, LauncherRule):
                continue
            launchers[str(exe)].append({
                "id": rule.id,
                "exe": rule.exe,
                "match": {
                    "argv_prefix": list(rule.match.argv_prefix),
                    "argv1_in": list(rule.match.argv1_in),
                    "min_argv": rule.match.min_argv,
                },
                "steps": [
                    {
                        "kind": step.kind,
                        "start_index": step.start_index,
                        "stop_at_double_dash": step.stop_at_double_dash,
                        "flags_with_value": list(step.flags_with_value),
                        "module_flag": step.module_flag,
                        "abort_flags": list(step.abort_flags),
                        "flag": step.flag,
                        "index": step.index,
                    }
                    for step in rule.steps
                ],
                "transform": {
                    "basename": rule.transform.basename,
                    "lowercase": rule.transform.lowercase,
                    "strip_trailing_punct": rule.transform.strip_trailing_punct,
                    "strip_npm_scope": rule.transform.strip_npm_scope,
                    "java_class_tail": rule.transform.java_class_tail,
                    "generic_entrypoint_fallback": rule.transform.generic_entrypoint_fallback,
                },
            })

    return {
        "generic_parents": list(getattr(cfg, "generic_parents", []) or []),
        "transparent_runtimes": list(getattr(cfg, "transparent_runtimes", []) or []),
        "apps": apps,
        "tools": tools,
        "system_categories": system_categories,
        "category_overrides": dict(getattr(cfg, "category_overrides", {}) or {}),
        "launchers_by_exe": launchers,
        "other_cpu_max": float(getattr(cfg, "other_cpu_max", 0.1) or 0.1),
        "other_mem_max": int(getattr(cfg, "other_mem_max", 30 << 20) or (30 << 20)),
        "default_expanded": list(getattr(cfg, "default_expanded", []) or []),
        "expand_threshold": int(getattr(cfg, "expand_threshold", 0) or 0),
    }


def _serialize_process(p: object) -> dict:
    return {
        "pid": int(getattr(p, "pid", 0)),
        "ppid": int(getattr(p, "ppid", 0)),
        "name": str(getattr(p, "name", "")),
        "exe": str(getattr(p, "exe", "")),
        "cpu_pct": float(getattr(p, "cpu_pct", 0.0)),
        "rss_bytes": int(getattr(p, "rss_bytes", 0)),
        "cmdline": str(getattr(p, "cmdline", "")),
        "uid": int(getattr(p, "uid", 0)),
        "starttime_ticks": int(getattr(p, "starttime_ticks", 0)),
    }


def _uid_map(processes: list[object]) -> dict[str, str]:
    out: dict[str, str] = {}
    for uid in sorted({int(getattr(p, "uid", 0)) for p in processes}):
        try:
            out[str(uid)] = pwd.getpwuid(uid).pw_name
        except (KeyError, OverflowError):
            out[str(uid)] = str(uid)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Record dump-groups fixture")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/dump_groups_snapshot.json"),
        help="Output fixture path",
    )
    parser.add_argument(
        "--sort",
        choices=("cpu", "mem", "count"),
        default="mem",
        help="Sort mode for expected dump",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional config.toml path",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    dirs = getattr(config.grouping, "desktop_dirs", []) or []
    exe_to_app = scan_desktop_entries(dirs) if dirs else {}

    cpu_total = get_aggregate_cpu_times()
    processes, _ = read_processes(0.0, cpu_total, None)
    processes = sorted(processes, key=lambda p: (p.pid, p.starttime_ticks))
    memory = read_memory()

    groups = group_processes(
        processes,
        memory.ram_total_bytes,
        config.grouping,
        exe_to_app,
    )
    buf = io.StringIO()
    dump_group_tree(groups, buf, sort_by=args.sort)

    data = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "sort_by": args.sort,
        "current_uid": os.getuid(),
        "uid_to_user": _uid_map(processes),
        "ram_total_bytes": memory.ram_total_bytes,
        "grouping_config": _serialize_grouping_config(config.grouping),
        "exe_to_app": exe_to_app,
        "processes": [_serialize_process(p) for p in processes],
        "expected_dump": buf.getvalue(),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote fixture: {args.output}")
    print(f"Processes captured: {len(processes)}")
    print(f"Groups dumped: {len(groups)}")


if __name__ == "__main__":
    main()
