# Process Grouping

How perf-glance groups processes into a hierarchical, categorized view.

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
become group roots themselves. Configurable via `generic_parents` (default
includes systemd, init, bash, sh, zsh, fish, sudo, tmux, screen, etc.).

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
- **agent**: TUI AI agents (Codex, Cursor Agent) — their subprocesses stay with
  the agent; Layer 2 does **not** reclaim them
- unset: standard tree-walk only

Groups are keyed by `(name, uid)` — same app run by different users → separate
groups.

### Layer 2: Build / Tool Grouping

Exe match against built-in and user-configured tool patterns. Tools **reclaim**
from Layer 1: e.g. `lake` and `lean` spawned by Cursor appear as "Lean build",
not under Cursor. Exception: processes under `agent`-family apps are not
reclaimed.

### Layer 3: System Categories

Exe list, `exe_prefix` (e.g. `gvfsd` matches `gvfsd-fuse`, `gvfsd-metadata`),
or a match function (Kernel: empty cmdline). Categories include Kernel, Display
Server, Window Manager, Audio, Network, Bluetooth, File Services, Security /
Auth, Session / Desktop, Logging / Monitoring, Virtualization.

`category_overrides` in config can move an exe into a category or exclude it
(empty string → Layer 4).

### Layer 4: Catch-all

Remaining processes grouped by effective exe. Groups below `other_cpu_max` and
`other_mem_max` are bucketed into "other (N)".

## Hierarchy and Expansion

App groups with multiple processes get sub-groups:

- **Electron/Chromium**: Main Process, Zygote, Utility, Web Content, GPU Process
- **Gecko** (Firefox): uses process name (comm) — Isolated Web Co, Web
  Content, WebExtensions, RDD Process, etc.
- **Agent** apps: sub-groups by effective exe (e.g. lean-lsp-mcp, context7-mcp)
- **Tools**: sub-groups by exe when > 1 process
- **System**: sub-groups by effective exe

Expand/collapse with Enter/→ and ←/Backspace. Expansion state is persisted.

## Configuration (Representative)

```toml
[grouping]
desktop_dirs = ["/usr/share/applications", "~/.local/share/applications", ...]
generic_parents = ["systemd", "init", "bash", "sh", "zsh", "fish", "sudo", "tmux", ...]
transparent_runtimes = ["python", "python3", "node", "ruby", "perl"]
other_cpu_max = 0.1
other_mem_max = "30M"

# Add or override app
[[grouping.apps]]
exe = "my-app"
name = "My App"
family = "electron"   # optional: electron | gecko | chromium | agent

# Add or override tool
[[grouping.tools]]
exe = "my-compiler"
name = "My Compiler"
category = "compiler"

# Move exe to category, or "" to exclude
[grouping.category_overrides]
"protonvpn-app" = "Network"
```

Exe matching is case-insensitive, basename only (no path). `cmdline` on app
patterns is an optional substring match (e.g. `java` + `cmdline = "idea.main"`).
