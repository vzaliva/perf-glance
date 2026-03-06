# Process Grouping

How perf-glance groups processes into a hierarchical, categorized view.

For rule customization (`app`, `tool`, `launcher`, category overrides, and list
patches), see [Grouping Rules](rules.md).

## Overview

Processes flow through four layers. Each layer claims processes not yet
assigned; Layer 2 can **reclaim** from Layer 1 (tools spawned by apps are
grouped under the tool, not the app).

```
  Input: list[ProcessInfo]
    │
    ▼
  Layer 0 — Desktop Entry Scan         (once at startup)
    │  .desktop files → exe→display-name mapping
    ▼
  Layer 1 — Application Recognition   (user-launched apps)
    │  Firefox, Cursor, Slack, Emacs, ...
    ▼
  Layer 2 — Build / Tool Grouping      (compilers, build systems)
    │  GCC build, Make, Cargo, ...
    ▼
  Layer 3 — System Categories          (kernel, audio, network, ...)
    │  Kernel, Audio, Window Manager, Session / Desktop
    ▼
  Layer 4 — Catch-all                  (group by exe)
    │  Low-activity groups → "other (N)"
```

## Key Heuristics

### Launchers and Wrappers

Many processes run behind a launcher. We resolve to the **actual program**:

- **Interpreters**: `python3 myscript.py` → *myscript*, `node server.js` → *server*
- **`python -m module`** → *module*
- **uv / uvx**: `uv run mytool` → *mytool*; `uvx perf-glance` → *perf-glance*
- **npm / npx**: `npm exec @scope/pkg` → *pkg*
- **java**: `java -jar app.jar` → *app*
- **go run**: `go run main.go` → *main*
- **Shells** (bash, sh, fish, etc.): `bash ./start.sh` → *start*

If the resolved name is a **generic entrypoint** (`index.js`, `main.py`,
`__main__.py`, etc.), we use the parent directory name so
`node /path/lean-lsp-mcp/dist/index.js` → *lean-lsp-mcp*.

### Generic Parents (Transparent Wrappers)

Processes like `systemd`, `bash`, `sudo`, `tmux` are treated as transparent:
when walking the process tree, we skip over them and keep going. They never
become group roots themselves. Defaults include systemd, init, bash, sh, zsh,
fish, sudo, tmux, screen, etc., and can be adjusted via `rules.d`.

### Parent Tracing (Ancestor Walk)

For Layer 1 (apps), we walk **up** from a process's parent. If any ancestor
matches an app pattern, the process is attributed to that app. This keeps
Cursor-extension binaries under Cursor, not under a standalone "Codex" group.
The walk stops when it hits a **terminal** (WezTerm, Alacritty, etc.) — programs
launched in a terminal are independent.

### Tree-Root Walk

When direct match and ancestor walk fail, we find the **tree root**: walk up
the `ppid` chain, skipping generic parents and same-name parents. If the root
matches an app, we attribute the whole subtree to that app.

## Layer Details

### Layer 0: Desktop Entry Scan

Scans `.desktop` files in configurable directories (e.g. `/usr/share/applications`,
`~/.local/share/applications`, snap/flatpak paths). Extracts `Exec` → exe
basename, `Name` → display name, `StartupWMClass` → secondary match for Electron.
Merge order: user config > built-in patterns > desktop scan.

### Layer 1: Application Recognition

Apps are identified by exe + optional cmdline pattern. **Families** control
child detection:

- **electron** / **chromium**: children with `--type=renderer`, `--type=utility`,
  `--type=gpu-process`, `--type=zygote`, `--crashpad-handler` in cmdline, same
  exe in path → grouped under the app
- **gecko**: children with `-contentproc` in cmdline, same exe
- **agent**: TUI AI agents (Claude, Codex, Cursor Agent) — their subprocesses stay with
  the agent; Layer 2 does **not** reclaim them
- unset: standard tree-walk only

Groups are keyed by `(name, uid)` — same app run by different users → separate
groups.

### Layer 2: Build / Tool Grouping

Exe match against built-in and user-configured tool patterns. Tools **reclaim**
from Layer 1 in general (for example under non-agent apps such as Firefox).
Exception: processes under AI host apps (Claude, Codex, Cursor, Cursor Agent)
are not reclaimed.

### Layer 3: System Categories

Exe list, `exe_prefix` (e.g. `gvfsd` matches `gvfsd-fuse`, `gvfsd-metadata`),
or a match function (Kernel: empty cmdline). Categories include Kernel, Display
Server, Window Manager, Audio, Network, Bluetooth, File Services, Security /
Auth, Session / Desktop, Logging / Monitoring, Virtualization.

`category_override` rules in `rules.d` can move an exe into a category or
exclude it (empty string → Layer 4).

### Layer 4: Catch-all

Remaining processes grouped by effective exe. Groups below `other_cpu_max` and
`other_mem_max` are bucketed into "other (N)".

## Hierarchy and Expansion

Groups with multiple processes get **deep hierarchical sub-trees** that follow
actual `ppid` relationships, not just flat exe-keyed buckets. The algorithm:

1. **Local tree construction** — build a tree from ppid links within the group.
2. **Transparent node skipping** — nodes whose key is in `skip_keys`
   (generic parents + transparent runtimes: shells, systemd, forkserver, python,
   node, etc.) are removed; their children are promoted to the parent level.
   Additionally, `skip_root_keys` removes nodes only at the sub-tree root
   (e.g. the app's own exe for Gecko, "Main Process" for Electron).
3. **Sibling merging** — at each level, processes with the same key are merged
   into a single node, their child pools combined.
4. **Chain collapse** — if a child has the same key as its parent, it is
   absorbed into the parent and its children are promoted (repeats until no
   same-key children remain).
5. **Recursion** — different-key children become nested sub-groups.

### Key functions per family

- **Electron/Chromium**: key = `--type=` flag (Utility, GPU Process, etc.) or
  effective exe; `skip_root_keys = {"Main Process"}`.
- **Gecko** (Firefox): key = process comm name (with truncation fixup for
  kernel's 15-char limit); `skip_root_keys = {app_exe}`.
- **Agent** apps: key = effective exe (via launcher rules).
- **Tools / System**: key = effective exe (via launcher rules).

### Gecko comm fixup

The kernel truncates `comm` to 15 characters. Well-known Gecko names are
corrected in code (e.g. "Isolated Web Co" → "Isolated Web Content").

### "other" bucket

Low-activity ungrouped processes are bucketed into "other (N)". This group
is expandable — its children are the original per-exe groups.

### UI controls

Expand/collapse with Enter/→ and ←/Backspace. Expansion state is persisted.

## Configuration

Rule customization is in `rules.d` files. See [Grouping Rules](rules.md) for
schema, precedence, and examples.

`config.toml` still controls non-rule knobs under `[grouping]`:

```toml
[grouping]
desktop_dirs = ["/usr/share/applications", "~/.local/share/applications", ...]
other_cpu_max = 0.1
other_mem_max = "30M"
default_expanded = []
expand_threshold = 0
```

Exe matching in rules is case-insensitive and basename-based (no path).
