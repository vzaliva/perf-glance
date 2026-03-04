# perf-glance

A terminal-based system utilization monitor for Linux. Presents a holistic,
hierarchical view of system activity, grouping processes by category (apps,
build tools, system services) rather than raw process lists.

## Features

- CPU utilization with per-core bars and historical graph
- CPU frequency and temperature (when available)
- Memory (RAM and swap) with used/cached distinction
- Process grouping: tree-based and binary-name grouping
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

