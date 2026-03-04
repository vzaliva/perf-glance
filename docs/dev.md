# Developer Notes

## Debugging with Dump-Tree (`--dump-groups`)

Use the one-shot tree dump to inspect grouping behavior without opening the TUI.

From repo root:

```bash
uv run perf-glance --dump-groups
```

Useful variants:

```bash
# Stable ordering by memory usage
uv run perf-glance --dump-groups --dump-sort mem

# Use an alternate config file
uv run perf-glance --dump-groups --config /path/to/config.toml
```

What this gives you:

1. Fully expanded group tree
2. Deterministic text output suitable for quick diffs
3. Fast feedback when tuning rules in `rules.d`

## Local Dump-Tree Regression Harness

This project includes a local replay test for grouping behavior based on a real
snapshot from your machine.

### Why local-only

The fixture contains real process data and full command lines, which can include
machine-specific or sensitive information. Do not commit it.

Ignored file:

- `tests/fixtures/dump_groups_snapshot.json`

### Files

- Recorder script: `tests/record_dump_groups_fixture.py`
- Replay test: `tests/test_dump_groups_snapshot.py`
- Local fixture output: `tests/fixtures/dump_groups_snapshot.json`

### Record a fresh fixture

From repo root:

```bash
uv run python tests/record_dump_groups_fixture.py --sort mem
```

This captures:

1. Current processes (`pid`, `ppid`, `exe`, `cmdline`, CPU%, RSS, uid)
2. Effective grouping config used for grouping
3. Desktop-entry app mapping (`exe_to_app`)
4. Expected `dump_group_tree` output text

### Run replay test

```bash
uv run pytest tests/test_dump_groups_snapshot.py -q
```

If the fixture file is missing, the test auto-skips.

### Recommended workflow during grouping/rules refactors

1. Record baseline fixture before refactor.
2. Implement changes.
3. Re-run replay test.
4. If behavior changed intentionally, re-record fixture and review the diff in
   `expected_dump` carefully.

### Notes

- Keep `--sort mem` for consistency with existing fixture style.
- This harness complements unit tests; it does not replace targeted tests for
  specific heuristics.

## Running Unit Tests

Run all tests:

```bash
uv run pytest
```

Run a single test file:

```bash
uv run pytest tests/test_grouping.py
```

Run one test:

```bash
uv run pytest tests/test_grouping.py::test_force_name_group
```

Run only the local dump-groups snapshot replay:

```bash
uv run pytest tests/test_dump_groups_snapshot.py -q
```

## Type Checking

Run pyright:

```bash
uv run pyright src/
```
