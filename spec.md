# perf-glance — Specification

A terminal-based system utilization monitor for Linux, written in Python.
Inspired by `btop` but focused on high-level, grouped process views rather than raw process lists.

---

## Goals

- Quick at-a-glance overview of system health: CPU, memory, and what's actually consuming resources
- Group similar/related processes into logical units rather than listing every PID
- Readable in a standard 80-column terminal; scales up gracefully on wider terminals
- Color and ANSI graphics when the terminal supports it; degrades cleanly otherwise

---

## Layout

Single-screen TUI, refreshed on a configurable interval (default: 2s).

```
┌─────────────────────────────────────────────────────────────────────┐
│ CPU  3.8GHz                                          Temp:  61°C   │
│  0 [████████░░░░░░░░░░░░]  42%    4 [██░░░░░░░░░░░░░░░░░░░]  12%   │
│  1 [█████░░░░░░░░░░░░░░░]  28%    5 [████████████░░░░░░░░░]  61%   │
│  2 [███████████░░░░░░░░░]  56%    6 [███░░░░░░░░░░░░░░░░░░]  18%   │
│  3 [█████████████░░░░░░░]  67%    7 [█████░░░░░░░░░░░░░░░░]  27%   │
│100%┤                                                          ╭─╮   │
│    │                                              ╭──╮   ╭───╯ │   │
│    │          ╭─╮      ╭──╮       ╭──╮      ╭────╯  ╰───╯     │   │
│  0%┴──────────╯ ╰──────╯  ╰───────╯  ╰──────╯                 ╰── │
│    ←——————————————————————— ~5 min ———————————————————————————→    │
├─────────────────────────────────────────────────────────────────────┤
│ Memory                                                               │
│ RAM  [██████████████░░░░░░░░░░░░░░░░]  11.2 / 31.4 GiB  (36%)      │
│ Swap [███░░░░░░░░░░░░░░░░░░░░░░░░░░░]   1.1 /  8.0 GiB  (14%)      │
├─────────────────────────────────────────────────────────────────────┤
│ Processes                                         [CPU%]  MEM%  MEM  │
│ firefox                               [12 procs]   8.4   3.2  1.0G  │
│ code (VSCode)                          [8 procs]   6.1   4.8  1.5G  │
│ python / python3                       [5 procs]   3.0   1.2  380M  │
│ cc1 / g++ (compiler)                   [4 procs]  22.0   0.8  250M  │
│ postgres                               [6 procs]   1.2   2.1  660M  │
│ Xorg / Wayland compositor              [2 procs]   2.0   0.6  190M  │
│ systemd services                      [34 procs]   0.5   1.0  320M  │
│ [other]                               [18 procs]   0.9   0.4  130M  │
└─────────────────────────────────────────────────────────────────────┘
 q quit   r refresh   +/- interval   s sort   ? help
```

---

## CPU Section

- One bar per logical CPU, arranged in two columns (or more, based on terminal width)
- Bar shows utilization with filled/empty block characters (`█`, `░`)
- Color coding: green < 50%, yellow 50–80%, red > 80%
- **Clock frequency** shown as a single global value in the CPU section header (average or
  max across cores, matching btop convention). Read from
  `/sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq` (fallback: `cpuinfo_cur_freq`),
  averaged across all cores. Shown in GHz. Hidden gracefully if sysfs path is absent (e.g., inside a VM).
- **Temperature** shown in the CPU section header. Sources tried in order:
  1. `hwmon` via `/sys/class/hwmon/hwmon*/temp*_input` — preferred, no external deps
  2. `sensors` (lm-sensors) output — fallback if hwmon labels are ambiguous
  - Temp color coding: normal (≤ 70°C) green, warm (70–85°C) orange, hot (> 85°C) red
  - Hidden if no thermal sensor is detected rather than showing an error
- **Historical graph** — scrolling line graph of aggregate CPU utilization (all cores averaged)
  shown below the per-core bars:
  - Y axis: 0–100%, labeled on the left edge
  - X axis: time, scrolling right-to-left; newest sample at the right edge
  - Width fills available terminal width; each column = one sample interval
  - History depth: enough samples to fill the width (e.g. ~5 minutes at 2s interval = 150 samples)
  - Rendered with Braille Unicode block characters (`⣀⣄⣆⣇⡇` etc.) for sub-character vertical resolution,
    falling back to `▁▂▃▄▅▆▇█` eighth-block characters, falling back to plain ASCII (`_.-'|`) if
    the terminal cannot render Unicode
  - Graph is in-memory only; history resets on restart

## Memory Section

- RAM bar: used / total, percentage
- Swap bar: used / total, percentage (hidden if no swap configured)
- Bar segments can distinguish used vs. cached (muted color for cached/buffers)
- Values shown in human-readable units (MiB / GiB)

---

## Process Grouping — Core Feature

The process list is the distinguishing feature of this tool. Instead of showing raw PIDs, processes are aggregated into logical groups with summed CPU% and memory.

### Grouping Strategy

Grouping uses a two-tier approach:

**Tier 1 — Process tree grouping (primary)**
Group by process tree: find the "root" of a related subtree and collapse all descendants under it.
- Walk `/proc/<pid>/status` (PPid field) or use `pstree`/`procs` to get the tree
- A group root is identified as the highest ancestor that is not a generic process manager (kernel threads, `systemd`, `init`, shell, `sudo`, `su`, etc.)
- All children/grandchildren collapse under the group root

**Tier 2 — Binary name grouping (secondary, for independent forks)**
Some processes are spawned independently (not via a shared parent) but are logically the same workload. Examples:
- Compiler workers (`cc1`, `g++`, `rustc`) launched by different build systems
- Multiple terminal emulator instances
- Worker scripts launched by cron

When multiple processes share the same binary name but have no common non-generic ancestor, they are grouped by binary name.

**Configurable exceptions** (via config file or command-line):
- Force binary-name grouping for specified executables regardless of tree (e.g., `cc1`, `rustc`)
- Force tree grouping even if binary name would suggest splitting
- Exclude certain binaries from grouping entirely

### Group Display

Each group row shows:
- Group name (derived from root process name or binary name)
- Process count in brackets
- Summed CPU%
- Summed memory (RSS), shown as % of total RAM and absolute value

The list is flat — no expand/collapse. What you see is the full view.

### Sorting

Default sort: CPU% descending. Toggle with `s` to cycle through sort columns:
- CPU% (default)
- Memory (RSS)

The active sort column header is highlighted — shown in a distinct color when color is available,
or wrapped in brackets `[CPU%]` when not. Plain-text fallback brackets are always present so the
indicator works even in monochrome/dumb terminals.

---

## Data Sources

| Data | Source |
|------|--------|
| CPU utilization | `/proc/stat` (delta between reads) |
| CPU frequency (avg) | `/sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq` (fallback: `cpuinfo_cur_freq`) |
| CPU temperature | `/sys/class/hwmon/hwmon*/temp*_input` + label files |
| Memory | `/proc/meminfo` |
| Process list | `/proc/<pid>/stat`, `/proc/<pid>/status`, `/proc/<pid>/cmdline` |
| Process tree | PPid from `/proc/<pid>/status` |

Optional external tools (used if available, for richer data):
- `procs` — structured JSON output for process info
- `pstree` — visual tree (informational, not primary data source)
- `ps` — fallback if `/proc` parsing is insufficient
- `sensors` (lm-sensors) — fallback for temperature if hwmon labels are ambiguous

---

## Configuration

Config file: `~/.config/perf-glance/config.toml` (created with defaults on first run).

```toml
[display]
refresh_interval = 2          # seconds
color = "auto"                # "auto" | "always" | "never"
cpu_layout = "auto"           # "auto" | "1col" | "2col"
show_swap = true
show_cpu_freq = true
show_cpu_temp = true          # always displayed in °C

[grouping]
# Executables always grouped by binary name regardless of parent tree
force_name_group = ["cc1", "g++", "gcc", "rustc", "clang", "clang++", "as", "ld", "lean", "lake"]

# Generic ancestors — do not use these as group roots
generic_parents = ["systemd", "init", "kthreadd", "bash", "sh", "zsh", "fish",
                   "sudo", "su", "login", "sshd", "tmux", "screen"]

[theme]
# Colors as ANSI named colors or truecolor hex strings.
# Named colors respect the terminal's own palette (good for themed terminals).
# Hex values are used as-is when the terminal reports truecolor support.

# CPU utilization bars — classic traffic-light progression
cpu_low    = "#00e676"        # bright green   (< 50%)
cpu_mid    = "#ffb300"        # amber           (50–80%)
cpu_high   = "#f44336"        # red             (> 80%)

# CPU history graph — teal/cyan to distinguish from per-core bars
cpu_graph  = "#00bcd4"

# Temperature — green → orange → red (orange feels more thermal than yellow)
temp_low   = "#00e676"        # bright green   (<= 70°C)
temp_mid   = "#ff6d00"        # deep orange     (70–85°C)
temp_high  = "#f44336"        # red             (> 85°C)

# Memory
mem_used   = "#00bcd4"        # cyan
mem_cached = "#1565c0"        # dim blue (same hue, lower brightness = less critical)
mem_swap   = "#ab47bc"        # magenta/purple — visually alarming, swap = pressure

# Process list
proc_sort_active = "bold"     # active sort column: bold bright white; brackets as fallback
proc_count       = "#4dd0e1"  # dim cyan for [N procs] badges
```

---

## Command-line Interface

```
perf-glance [OPTIONS]

Options:
  -i, --interval SECONDS   Refresh interval (default: 2)
  -n, --iterations N       Exit after N refreshes (useful for scripting)
  --config PATH            Use alternate config file
  -h, --help               Show help
```

---

## Keyboard Shortcuts (interactive mode)

| Key | Action |
|-----|--------|
| `q` / `Ctrl-C` | Quit |
| `r` | Force refresh |
| `+` / `-` | Increase / decrease refresh interval |
| `s` | Cycle sort order |
| `↑` / `↓` | Scroll process list |
| `?` | Help overlay |

---

## Terminal Compatibility

- Color and capability detection handled by Textual/Rich automatically
- Minimum supported width: 80 columns; minimum height: 24 rows
- Resize (`SIGWINCH`) handled by Textual; layout reflows immediately

---

## Dependencies

**Required:**
- Python 3.11+
- `textual` — full-screen TUI framework (layout, keyboard input, refresh loop, resize)
- `rich` — styled text, bars, and tables; renders directly inside Textual widgets

**Optional runtime tools** (detected at startup, used if present):
- `procs` — richer process metadata
- `ps` / `psmisc` (`pstree`) — fallback process tree

**Development extras:**
- `pytest`
- `textual-dev` (Textual devtools — live reload, DOM inspector)
- `pyright` — static type checker; run in default mode initially, graduate to `strict`

---

## Packaging & Distribution

The tool is packaged as a standard Python package and distributed via PyPI, designed for use with `uv`/`uvx`.

**Run without installing:**
```sh
uvx perf-glance
```

**Install globally as a tool:**
```sh
uv tool install perf-glance
```

**Local development workflow:**
```sh
# First time setup — creates .venv and installs deps + project in editable mode
uv sync

# Run from source (no activation needed)
uv run perf-glance

# Add a dependency
uv add textual

# Add a dev-only dependency
uv add --dev pyright
```

Editable install means source changes are reflected immediately — no reinstall needed between runs.

**Project layout** follows `uv` conventions:
- `pyproject.toml` as the single source of truth (metadata, dependencies, scripts)
- Entry point declared as a `[project.scripts]` target so `uvx` can invoke it directly
- No `setup.py` or `requirements.txt`

---

## Non-Goals

- Not a full process manager (no kill/renice from UI — v1)
- Not a network monitor (future extension)
- Not a disk I/O monitor (future extension)
- Not Windows/macOS support
