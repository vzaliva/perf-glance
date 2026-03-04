"""Tests for rules.d loading and merge semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from perf_glance.grouping.rules_loader import load_grouping_rules


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_builtin_rules_present(tmp_path) -> None:
    rules = load_grouping_rules(
        system_rules_dir=tmp_path / "system",
        user_rules_dir=tmp_path / "user",
    )
    assert any(a.exe == "firefox" for a in rules.apps)
    assert any(t.exe == "lake" for t in rules.tools)
    assert any(c.name == "Audio" for c in rules.system_categories)
    assert "bash" in rules.generic_parents
    assert "python3" in rules.transparent_runtimes
    assert "uv" in rules.launchers_by_exe


def test_merge_override_and_disable(tmp_path) -> None:
    builtin = tmp_path / "builtin"
    system = tmp_path / "system"
    user = tmp_path / "user"

    _write(
        builtin / "10-base.toml",
        """schema_version = 1
[[tool]]
id = "tool.a"
exe = "aaa"
name = "AAA"
category = "build"
""",
    )
    _write(
        system / "20-system.toml",
        """schema_version = 1
[[tool]]
id = "tool.a"
exe = "aaa"
name = "AAA2"
category = "compiler"
""",
    )
    _write(
        user / "90-user.toml",
        """schema_version = 1
[[tool]]
id = "tool.a"
enabled = false
exe = "aaa"
name = "ignored"
""",
    )

    rules = load_grouping_rules(user_rules_dir=user, system_rules_dir=system, builtin_rules_dir=builtin)
    assert not any(t.exe == "aaa" for t in rules.tools)


def test_list_patch_order(tmp_path) -> None:
    builtin = tmp_path / "builtin"
    system = tmp_path / "system"
    user = tmp_path / "user"

    _write(
        builtin / "10-base.toml",
        """schema_version = 1
[list_patch]
transparent_runtimes_add = ["python3", "node"]
""",
    )
    _write(
        system / "20-system.toml",
        """schema_version = 1
[list_patch]
transparent_runtimes_remove = ["node"]
transparent_runtimes_add = ["bun"]
""",
    )
    _write(
        user / "90-user.toml",
        """schema_version = 1
[list_patch]
transparent_runtimes_add = ["python3", "deno"]
""",
    )

    rules = load_grouping_rules(user_rules_dir=user, system_rules_dir=system, builtin_rules_dir=builtin)
    assert rules.transparent_runtimes == ["python3", "bun", "deno"]


def test_legacy_grouping_keys_fail_fast(tmp_path) -> None:
    from perf_glance.config import load_config

    cfg = tmp_path / "config.toml"
    _write(
        cfg,
        """[display]
refresh_interval = 5

[grouping]
generic_parents = ["bash"]
""",
    )

    with pytest.raises(ValueError, match="legacy"):
        load_config(cfg)
