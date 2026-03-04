"""Snapshot-style regression test for group/dump behavior."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from perf_glance.dump_groups import dump_group_tree
from perf_glance.grouping.patterns import AppPattern, ToolPattern
from perf_glance.grouping.rules_loader import (
    LauncherMatch,
    LauncherRule,
    LauncherStep,
    LauncherTransform,
    SystemCategory,
)
from perf_glance.grouping.process_groups import group_processes
import perf_glance.grouping.process_groups as process_groups_mod


def _fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "dump_groups_snapshot.json"


def _load_fixture() -> dict:
    path = _fixture_path()
    if not path.exists():
        pytest.skip(
            "Local dump-groups fixture not found. "
            "Generate it with: uv run python tests/record_dump_groups_fixture.py --sort mem"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _build_grouping_config(raw: dict) -> SimpleNamespace:
    apps = [
        AppPattern(
            exe=str(item.get("exe", "")),
            name=str(item.get("name", "")),
            family=str(item.get("family", "")),
            cmdline=str(item.get("cmdline", "")),
        )
        for item in raw.get("apps", [])
    ]
    tools = [
        ToolPattern(
            exe=str(item.get("exe", "")),
            name=str(item.get("name", "")),
            category=str(item.get("category", "")),
        )
        for item in raw.get("tools", [])
    ]

    system_categories = [
        SystemCategory(
            id=str(item.get("id", "")),
            name=str(item.get("name", "")),
            exe=tuple(str(x).lower() for x in item.get("exe", [])),
            exe_prefix=tuple(str(x).lower() for x in item.get("exe_prefix", [])),
        )
        for item in raw.get("system_categories", [])
    ]

    launchers_by_exe: dict[str, list[LauncherRule]] = {}
    for exe, rules in (raw.get("launchers_by_exe", {}) or {}).items():
        launchers_by_exe[str(exe)] = []
        for rule in rules:
            launchers_by_exe[str(exe)].append(
                LauncherRule(
                    id=str(rule.get("id", "")),
                    exe=str(rule.get("exe", "")),
                    match=LauncherMatch(
                        argv_prefix=tuple(str(x) for x in rule.get("match", {}).get("argv_prefix", [])),
                        argv1_in=tuple(str(x) for x in rule.get("match", {}).get("argv1_in", [])),
                        min_argv=int(rule.get("match", {}).get("min_argv", 0)),
                    ),
                    steps=tuple(
                        LauncherStep(
                            kind=str(step.get("kind", "")),
                            start_index=int(step.get("start_index", 1)),
                            stop_at_double_dash=bool(step.get("stop_at_double_dash", True)),
                            flags_with_value=tuple(str(x) for x in step.get("flags_with_value", [])),
                            module_flag=str(step.get("module_flag", "")),
                            abort_flags=tuple(str(x) for x in step.get("abort_flags", [])),
                            flag=str(step.get("flag", "")),
                            index=int(step.get("index", -1)),
                        )
                        for step in rule.get("steps", [])
                    ),
                    transform=LauncherTransform(
                        basename=bool(rule.get("transform", {}).get("basename", False)),
                        lowercase=bool(rule.get("transform", {}).get("lowercase", False)),
                        strip_trailing_punct=bool(rule.get("transform", {}).get("strip_trailing_punct", False)),
                        strip_npm_scope=bool(rule.get("transform", {}).get("strip_npm_scope", False)),
                        java_class_tail=bool(rule.get("transform", {}).get("java_class_tail", False)),
                        generic_entrypoint_fallback=bool(
                            rule.get("transform", {}).get("generic_entrypoint_fallback", False)
                        ),
                    ),
                )
            )

    return SimpleNamespace(
        generic_parents=list(raw.get("generic_parents", [])),
        transparent_runtimes=list(raw.get("transparent_runtimes", [])),
        apps=apps,
        tools=tools,
        system_categories=system_categories,
        category_overrides=dict(raw.get("category_overrides", {})),
        launchers_by_exe=launchers_by_exe,
        other_cpu_max=float(raw.get("other_cpu_max", 0.1)),
        other_mem_max=int(raw.get("other_mem_max", 30 << 20)),
        default_expanded=list(raw.get("default_expanded", [])),
        expand_threshold=int(raw.get("expand_threshold", 0)),
    )


def _build_processes(raw: list[dict]) -> list[SimpleNamespace]:
    return [SimpleNamespace(**item) for item in raw]


def test_dump_groups_snapshot(monkeypatch) -> None:
    data = _load_fixture()
    cfg = _build_grouping_config(data["grouping_config"])
    processes = _build_processes(data["processes"])

    current_uid = int(data["current_uid"])
    uid_to_user = {str(k): str(v) for k, v in data["uid_to_user"].items()}

    monkeypatch.setattr(process_groups_mod.os, "getuid", lambda: current_uid)
    monkeypatch.setattr(
        process_groups_mod,
        "_uid_to_user",
        lambda uid, m=uid_to_user: m.get(str(uid), str(uid)),
    )

    groups = group_processes(
        processes,
        int(data["ram_total_bytes"]),
        cfg,
        dict(data.get("exe_to_app", {})),
    )
    buf = io.StringIO()
    dump_group_tree(groups, file=buf, sort_by=str(data["sort_by"]))

    assert buf.getvalue().rstrip() == str(data["expected_dump"]).rstrip()
