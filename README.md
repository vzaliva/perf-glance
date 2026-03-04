# perf-glance

A terminal-based system utilization monitor for Linux. Instead of hundreds of
raw process names, you see **Firefox** (35 procs, 13G), **Cursor** (29 procs),
**Slack**, **Discord** — apps, build tools, and system services grouped by
category in an expandable hierarchy. Expand Firefox to see "Isolated Web Co
(24)", "WebExtensions", "RDD Process"; expand Cursor for Main Process, Zygote,
Utility. `.desktop` files and known patterns recognize apps automatically;
interpreters like Python and Node are transparent — `python myscript.py` shows
*myscript*, not *python3*.

![perf-glance (left) vs top (right)](docs/perf-glance-vs-top.png)

## Features

- CPU utilization with per-core bars and historical graph
- CPU frequency and temperature (when available)
- Memory (RAM and swap) with used/cached distinction
- Hierarchical process grouping with expand/collapse
- Configurable refresh interval, sorting, and theme


## Quick Start

**One-liner (no install):** download the wrapper script and run:

```sh
curl -O https://raw.githubusercontent.com/vzaliva/perf-glance/main/perf-glance
chmod +x perf-glance
./perf-glance
```

The script uses [uv](https://docs.astral.sh/uv/) to fetch and run perf-glance from GitHub on first use.

Or via uvx / install:

```sh
uvx perf-glance
```

```sh
uv tool install perf-glance
perf-glance
```

## Testing / Debugging

To dump the process group tree (fully expanded, as displayed) to stdout:

```sh
perf-glance --dump-groups
perf-glance --dump-groups --dump-sort mem   # sort by memory
perf-glance --dump-groups > output.txt      # redirect if needed
```

## Configuration

Config file: `~/.config/perf-glance/config.toml` (created with defaults on first run).

## Disclaimers

0. Linux-only; developed on Ubuntu - some behavior may be Ubuntu-specific

1. UI was inspired by [btop](https://github.com/aristocratos/btop)

2. I vibe-coded this app with Claude Code. My goal was utilitarian: a tool I
   needed plus an exploration of user-friendly process classification - not
   polished code. However, I take full responsibility: I will maintain it, fix
   bugs, and welcome pull requests.

