# Grouping Rules (`rules.d`)

Use `rules.d` to customize how perf-glance groups processes into apps, tools,
and system categories.

This is a user guide for writing local overrides.

## What `rules.d` controls

`rules.d` controls process-identification rules:

1. App rules (`[[app]]`)
2. Tool rules (`[[tool]]`)
3. System categories (`[[system_category]]`)
4. Category overrides (`[[category_override]]`)
5. Launcher parsing (`[[launcher]]`)
6. List tweaks (`[list_patch]`) for `generic_parents` and `transparent_runtimes`

`rules.d` does not replace display/theme settings in `config.toml`.

## Rule directories and precedence

perf-glance loads rules from these directories, in this order:

1. Built-in: `rules/builtin.d/`
2. System-wide: `/etc/perf-glance/rules.d/` (optional)
3. User: `~/.config/perf-glance/rules.d/`

Inside each directory, files are loaded in lexicographic order.

Later files win. Later directories also win.

Example names:

1. `10-core-apps.toml`
2. `20-core-tools.toml`
3. `30-system.toml`
4. `90-local.toml`

## File format

Each file is TOML and must start with:

```toml
schema_version = 1
```

Supported top-level sections:

1. `[[app]]`
2. `[[tool]]`
3. `[[system_category]]`
4. `[[category_override]]`
5. `[[launcher]]`
6. `[list_patch]`

Unknown sections/keys are ignored with a warning.

## Glossary

1. `group`: one process-table row that aggregates one or more processes.
2. `launcher`: wrapper executable that starts another command (`python`, `uv`, `npm`, `java`, etc.).
3. `effective exe`: command identity after launcher parsing (`python foo.py` -> `foo.py`).
4. `transparent runtime`: runtime that should usually resolve to the launched target.
5. `generic parent`: wrapper parent skipped during tree walk (`bash`, `systemd`, `tmux`, etc.).
6. `reclaim`: tool grouping taking a process that app grouping would otherwise keep.

## Merge and disable behavior

Every rule entry (`app`, `tool`, `system_category`, `category_override`, `launcher`)
uses an `id`.

Merge behavior:

1. First `id` creates the rule.
2. Later rule with same `id` fully replaces earlier one.
3. `enabled = false` disables that rule id.

This is how you override built-ins safely.

## Rule types

### `[[app]]`

Use for user-facing app identity in Layer 1.

Required fields:

1. `id`
2. `exe`
3. `name`

Optional fields:

1. `enabled` (default `true`)
2. `family`: `""`, `electron`, `chromium`, `gecko`, `agent`
3. `cmdline`: case-insensitive substring filter
4. `no_tool_reclaim`: if `true`, Layer 2 tools will not reclaim this app's subtree

```toml
[[app]]
id = "app.cursor"
exe = "cursor"
name = "Cursor"
family = "electron"
no_tool_reclaim = true
```

### `[[tool]]`

Use for build/dev/runtime tools in Layer 2.

Required fields:

1. `id`
2. `exe`
3. `name`

Optional fields:

1. `enabled` (default `true`)
2. `category` (metadata only: `compiler`, `build`, `lsp`, `runtime`, ...)

```toml
[[tool]]
id = "build.lake"
exe = "lake"
name = "Lake"
category = "build"
```

### `[[system_category]]`

Use for Layer 3 system buckets.

Required fields:

1. `id`
2. `name`
3. at least one of `exe` or `exe_prefix`

Optional fields:

1. `enabled` (default `true`)

```toml
[[system_category]]
id = "sys.audio"
name = "Audio"
exe = ["pipewire", "wireplumber"]
exe_prefix = ["gvfsd"]
```

### `[[category_override]]`

Use to force one executable into a system category (or exclude it).

Required fields:

1. `id`
2. `exe`
3. `category`

Optional fields:

1. `enabled` (default `true`)

Notes:

1. `category = ""` means "exclude this exe from system categories".

```toml
[[category_override]]
id = "override.mydaemon"
exe = "mydaemon"
category = "Session / Desktop"
```

### `[[launcher]]`

Use to map wrapper/runtime processes to the real launched command.

Required fields:

1. `id`
2. `exe`
3. one or more `[[launcher.step]]`

Optional fields:

1. `enabled` (default `true`)
2. `[launcher.match]`
3. `[launcher.transform]`

#### `[launcher.match]`

Rule gate:

1. `argv_prefix` (exact tokens after `argv[0]`)
2. `argv1_in`
3. `min_argv`

#### `[[launcher.step]]`

Extraction pipeline (first successful step wins).

Supported `kind` values:

1. `next_after_flag`
2. `first_non_flag`
3. `argv_at`
4. `first_non_flag_after_prefix`

Common step options:

1. `start_index`
2. `stop_at_double_dash`
3. `flags_with_value`
4. `module_flag`
5. `abort_flags`
6. `flag`
7. `index`

#### `[launcher.transform]`

Post-processing options:

1. `basename`
2. `lowercase`
3. `strip_trailing_punct`
4. `strip_npm_scope`
5. `java_class_tail`
6. `generic_entrypoint_fallback`

Minimal example:

```toml
[[launcher]]
id = "launcher.python3"
exe = "python3"

[[launcher.step]]
kind = "first_non_flag"
start_index = 1
module_flag = "-m"
abort_flags = ["-c"]
```

### `[list_patch]`

Use this for small add/remove changes to built-in list behavior.

Supported targets:

1. `generic_parents_add`
2. `generic_parents_remove`
3. `transparent_runtimes_add`
4. `transparent_runtimes_remove`

Apply order inside each file:

1. remove first
2. add second

Duplicates are removed while preserving first-seen order.

```toml
[list_patch]
generic_parents_add = ["my-wrapper"]
transparent_runtimes_add = ["bun"]
```

Decision rule:

1. Use `[list_patch]` for add/remove list membership.
2. Use `[[launcher]]` when parsing behavior must change.

## Complete user example

`~/.config/perf-glance/rules.d/90-local.toml`

```toml
schema_version = 1

[[app]]
id = "ai.claude"
exe = "claude"
name = "Claude"
family = "agent"
no_tool_reclaim = true

[[tool]]
id = "build.mytool"
exe = "my-build-tool"
name = "My Tool"
category = "build"

[[category_override]]
id = "override.proton"
exe = "protonvpn-app"
category = "Network"

[list_patch]
generic_parents_add = ["my-shell-wrapper"]

[[launcher]]
id = "launcher.bun"
exe = "bun"

[[launcher.step]]
kind = "first_non_flag"
start_index = 1
```

## Troubleshooting

1. Invalid rules do not stop startup; they are skipped with warnings.
2. If `schema_version` is missing/invalid, the whole file is skipped.
3. If a rule does nothing, confirm file location and filename order.

