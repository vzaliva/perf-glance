# perf-glance

A terminal-based system utilization monitor for Linux/MacOS. Instead of
hundreds of raw process names, you see **Firefox** (35 procs, 13G),
**Cursor** (29 procs), **Slack**, **Discord** - apps, build tools, and
system services grouped by category in an expandable hierarchy. Expand
Firefox to see "Isolated Web Co (24)", "WebExtensions", "RDD Process";
expand Cursor for "Main Process", "Zygote", "Utility". `.desktop` files and
known patterns recognize apps automatically; interpreters like Python
and Node are transparent - `python myscript.py` shows *myscript*, not
*python3*.

See [docs/grouping.md](docs/grouping.md) for grouping internals and
[docs/rules.md](docs/rules.md) for user-configurable grouping rules.

Screenshot: **perf-glance** (left) vs **top** (right):
![perf-glance (left) vs top (right)](docs/perf-glance-vs-top.png)
Additional screenshots: [linux](docs/linux_screenshot.png), [mac](docs/mac_screenshot.png)

## Features

- CPU utilization with per-core bars and historical graph
- CPU frequency and temperature (when available)
- Memory (RAM and swap) with used/cached distinction
- Hierarchical process grouping with expand/collapse
- Configurable grouping rules via `rules.d`
- Process table `Cum%` column: cumulative CPU share since reset
- Configurable refresh interval, sorting, and theme

## Quick Start

**Rust version** (from source):

```sh
cargo build --release
./target/release/perf-glance
```

Or run directly: `cargo run --release`

**Python version** (requires [uv](https://docs.astral.sh/uv/)):

**1. uvx** (recommended):

```sh
uvx --from 'git+https://github.com/vzaliva/perf-glance' perf-glance
```

**2. uv tool install** (using uv):

```sh
uv tool install --from 'git+https://github.com/vzaliva/perf-glance' perf-glance
perf-glance
```

**3. Curl fallback** (requires uv installed; fetches wrapper script, which uses uv on first run):

```sh
curl -O https://raw.githubusercontent.com/vzaliva/perf-glance/main/perf-glance
chmod +x perf-glance
./perf-glance
```

## Contributing

**1. Rules contributions** - We can't anticipate every process or app.
If you don't like how something is grouped on your machine, the easiest
way to tweak it is via `rules.d` (see [docs/rules.md](docs/rules.md)) -
no coding required. To share your rules, submit a PR with new rule files
in `rules/builtin.d/`.

AI coding agents like Claude Code work well for generating rules. Example
prompt:

> Run `perf-glance --dump-groups` and examine its output for grouping
> improvements. For unrecognized processes, look up system package info and web
> documentation to suggest better grouping. Do not modify Python code - only
> produce new `.toml` files in `rules/builtin.d/`. Files load in lexicographic
> order, so name them to fit alongside existing definitions.

**2. Code contributions** - See [docs/TODO.md](docs/TODO.md) for potential
enhancements and [docs/dev.md](docs/dev.md) for development hints. Pull
requests welcome.

## Configuration

Config file: `~/.config/perf-glance/config.toml` (created with defaults on first run).
Grouping rules: `~/.config/perf-glance/rules.d/*.toml` (see [docs/rules.md](docs/rules.md)).

## Disclaimers

1. UI was inspired by [btop](https://github.com/aristocratos/btop)

2. I vibe-coded this app with AI. I know enough Python to implement it
   myself, but my goal was not to write some beautiful code. My
   objectives were utilitarian: 1) to build a tool I wanted to have
   personally, 2) to explore an idea of user-friendly process
   classification. However, I take full responsibility for this code
   and I will maintain it, fix bugs, and welcome pull requests.
