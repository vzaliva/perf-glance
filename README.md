# perf-glance

A terminal-based system utilization monitor for Linux, inspired by btop but focused on high-level, grouped process views rather than raw process lists.

## Features

- CPU utilization with per-core bars and historical graph
- CPU frequency and temperature (when available)
- Memory (RAM and swap) with used/cached distinction
- Process grouping: tree-based and binary-name grouping
- Configurable refresh interval, sorting, and theme

## Quick Start

```sh
uvx perf-glance
```

Or install and run:

```sh
uv tool install perf-glance
perf-glance
```

## Configuration

Config file: `~/.config/perf-glance/config.toml` (created with defaults on first run).

## Development

```sh
uv sync
uv run perf-glance
uv run pytest
```
