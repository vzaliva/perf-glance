# Process Grouping Redesign Proposal

## Problem with Current Approach

The current two-tier algorithm (tree-walk + `force_name_group` exe matching) has
several limitations:

1. **Tree-walk is fragile**: depends on ppid chains that break across session
   boundaries (snaps, flatpaks, `setsid`, D-Bus activation).
2. **force_name_group is flat**: a single list of executables with no semantic
   meaning — `lean` and `gcc` are treated identically.
3. **Humanization is ad-hoc**: hard-coded `if "code" in exe` / `if "firefox"`
   checks don't scale.
4. **No hierarchy**: the flat list forces aggressive bucketing ("user services",
   "other (N)") that hides useful information.
5. **No user distinction**: if two users run Firefox, they merge into one group.

## Observed Process Landscape (this machine)

| Category | Examples | Count |
|---|---|---|
| Desktop apps | Cursor (18 procs), Firefox (30+), Slack (8), Discord (7), Signal (8) | ~80 |
| Build tools | lean (24), lake, make, uv | ~30 |
| Terminal / shell | wezterm-gui, fish, bash, sh | ~15 |
| Desktop environment | Xorg, i3, i3bar, picom, py3status, dunst | ~10 |
| Audio | pipewire, pipewire-pulse, wireplumber | ~4 |
| System daemons | systemd, journald, udevd, logind, cron, rsyslog | ~15 |
| Network | NetworkManager, wpa_supplicant, resolved, protonvpn | ~5 |
| File services | gvfsd-*, udisksd, dropbox | ~10 |
| Kernel threads | kworker, ksoftirqd, migration, rcu_* | ~350 |
| User agents | gnome-keyring, gpg-agent, dbus-daemon, at-spi | ~10 |

Key observations:
- Electron apps (Cursor, Discord, Slack, Signal) spawn ~7–18 child processes
  each — all share the same exe or use `--type=renderer/utility/gpu-process`.
- Firefox (Gecko) uses `-contentproc` with labels like `Isolated Web Co`,
  `Web Content`, `WebExtensions`, `RDD Process`.
- Build tool parallelism (24 concurrent `lean` processes) needs grouping by exe
  but with a meaningful label ("lean (mathlib build)" not just "lean").
- System services are best understood by *function* (audio, network, display)
  not by process tree.

## Proposed Algorithm: Four-Layer Grouping

### Overview

```
  Input: list[ProcessInfo]
    │
    ▼
  Layer 0 — Desktop Entry Scan         (once at startup, cached)
    │  Scans .desktop files to build exe→app-name mapping
    │  Merged with built-in patterns and user config
    │
    ▼
  Layer 1 — Application Recognition   (user-launched apps)
    │  Assigns: "Firefox", "Cursor", "Slack", ...
    │  Method:  .desktop + known-app patterns + Electron/Gecko detection + tree walk
    │
    ▼
  Layer 2 — Build / Tool Grouping      (compiler swarms, dev tools)
    │  Assigns: "Lean build", "GCC compile", ...
    │  Method:  exe matching against tool patterns
    │  Note:    tools spawned BY an app (e.g. Cursor→lean) stay with the tool,
    │           not the app — Layer 2 claims them from Layer 1's tree
    │
    ▼
  Layer 3 — System Semantic Categories  (kernel, audio, network, ...)
    │  Assigns: "Kernel", "Audio", "Network Services", ...
    │  Method:  exe/cgroup/unit pattern matching
    │
    ▼
  Layer 4 — Catch-all                   (remaining uncategorized)
    │  Assigns: group by exe name
    │
    ▼
  Post-processing: user split, stats aggregation, hierarchy construction
```

Each layer claims processes not yet assigned by a previous layer, with one
exception: Layer 2 can **reclaim** processes from Layer 1's tree-walk children
(see "Cross-layer interaction" below).

### Layer 0: Desktop Entry Scan

On startup (and optionally on config reload), scan `.desktop` files to build an
exe-to-app-name mapping. This provides automatic recognition of installed
applications without maintaining a manual pattern list.

#### Scan paths (configurable)

```
/usr/share/applications/*.desktop
/usr/local/share/applications/*.desktop
~/.local/share/applications/*.desktop
/var/lib/snapd/desktop/applications/*.desktop
/var/lib/flatpak/exports/share/applications/*.desktop
~/.local/share/flatpak/exports/share/applications/*.desktop
```

#### Parsing

From each `.desktop` file, extract:
- `Exec=` line → base executable name (strip `%u`, `%F`, env prefixes, paths)
- `Name=` line → human-readable display name
- `StartupWMClass=` → secondary exe match key (useful for Electron apps)

Example: `cursor.desktop` contains `Exec=/usr/share/cursor/cursor %U` and
`Name=Cursor` → maps exe `cursor` to display name "Cursor".

#### Merge order (highest priority first)

1. User config `[[grouping.apps]]` — explicit overrides always win
2. Built-in `APP_PATTERNS` — curated, tested patterns with family info
3. `.desktop` file scan — automatic discovery, broadest coverage

If the same exe appears in multiple sources, the highest-priority source wins.
The `.desktop` scan fills in apps that neither the built-in list nor user
config cover.

### Layer 1: Application Recognition

Goal: identify processes that belong to a **user-launched application** (the
kind of thing with a window, an icon, a name the user typed or clicked).

#### 1a. Known App Pattern Database

A table mapping exe/cmdline patterns to human-readable app names. These serve
as curated overrides for `.desktop` scan results (e.g., providing `family`
metadata that `.desktop` files lack):

```python
APP_PATTERNS = [
    # Electron apps — match main exe, children auto-grouped
    AppPattern(exe="cursor",         name="Cursor",         family="electron"),
    AppPattern(exe="code",           name="VS Code",        family="electron"),
    AppPattern(exe="slack",          name="Slack",           family="electron"),
    AppPattern(exe="discord",        name="Discord",        family="electron"),
    AppPattern(exe="signal-desktop", name="Signal",         family="electron"),
    AppPattern(exe="teams",          name="Teams",          family="electron"),
    AppPattern(exe="spotify",        name="Spotify",        family="electron"),
    AppPattern(exe="obsidian",       name="Obsidian",       family="electron"),

    # Gecko (Firefox-based)
    AppPattern(exe="firefox",        name="Firefox",        family="gecko"),
    AppPattern(exe="thunderbird",    name="Thunderbird",    family="gecko"),
    AppPattern(exe="librewolf",      name="LibreWolf",      family="gecko"),

    # Chromium-based (non-Electron)
    AppPattern(exe="chrome",         name="Chrome",         family="chromium"),
    AppPattern(exe="chromium",       name="Chromium",       family="chromium"),
    AppPattern(exe="brave",          name="Brave",          family="chromium"),
    AppPattern(exe="vivaldi",        name="Vivaldi",        family="chromium"),
    AppPattern(exe="opera",          name="Opera",          family="chromium"),

    # Native GUI apps
    AppPattern(exe="emacs",          name="Emacs"),
    AppPattern(exe="gimp",           name="GIMP"),
    AppPattern(exe="blender",        name="Blender"),
    AppPattern(exe="inkscape",       name="Inkscape"),
    AppPattern(exe="libreoffice",    name="LibreOffice"),
    AppPattern(exe="vlc",            name="VLC"),
    AppPattern(exe="mpv",            name="mpv"),
    AppPattern(exe="steam",          name="Steam",          family="electron"),
    AppPattern(exe="dropbox",        name="Dropbox"),

    # Terminals (GUI process only — children are independent, see Decisions §1)
    AppPattern(exe="wezterm-gui",    name="WezTerm"),
    AppPattern(exe="alacritty",      name="Alacritty"),
    AppPattern(exe="kitty",          name="Kitty"),
    AppPattern(exe="gnome-terminal", name="GNOME Terminal"),
    AppPattern(exe="konsole",        name="Konsole"),
    AppPattern(exe="xterm",          name="xterm"),
]
```

#### 1b. Multi-process app detection

For apps in the `electron` family, child process detection:
- Any process whose cmdline contains `--type=renderer`, `--type=gpu-process`,
  `--type=utility`, `--type=zygote`, `--crashpad-handler` **and** whose
  cmdline or exe matches the parent app pattern → belongs to that app.
- Tree-walk from child to parent: if any ancestor matches an app pattern, the
  child belongs to that app.

For `gecko` family:
- Any process whose cmdline contains `-contentproc` and whose exe matches the
  app's exe → belongs to that app.

For other apps:
- Standard tree-walk (current algorithm): walk ppid chain, skip generic parents.

#### 1c. User distinction

If the same app pattern matches processes owned by different UIDs, they form
**separate groups** with the user column distinguishing them:

```
Firefox                    lord     32    4.2   8.3   2.1G
Firefox                    guest     8    1.1   2.0   512M
```

Groups are keyed by `(app_name, uid)`. No per-session splitting — just per-user.

### Cross-Layer Interaction: Apps That Spawn Tools

A Layer 1 app (e.g., Cursor) may spawn Layer 2 tool processes (e.g., `lean`,
`make`, `gcc`). The question: does `lean` belong to "Cursor" or to "Lean build"?

**Decision: tools are always claimed by Layer 2, not by the parent app.**

Rationale: users think "my Lean build is using 85% CPU" not "Cursor is using
85% CPU". The build tools are the interesting resource consumers. Cursor's own
processes (renderer, GPU, utility) stay in Layer 1.

Implementation: Layer 2 runs after Layer 1 and can **reclaim** processes that
Layer 1 assigned via tree-walk. Specifically:
1. Layer 1 assigns Cursor's own processes (those matching Electron patterns).
2. Layer 1's tree-walk also tentatively claims child processes like shells,
   `lake`, `lean`, etc.
3. Layer 2 scans all processes (including Layer 1 tentative claims) and reclaims
   any that match tool patterns.

This means the process tree:
```
cursor (pid 3719008)
  └─ cursor --type=utility (pid 3719198)  ← stays in Cursor (Layer 1)
       └─ cursor (extension host)         ← stays in Cursor (Layer 1)
            └─ bash                       ← terminal process (generic, unclaimed)
                 └─ lake build            ← reclaimed by Layer 2 → "Lean build"
                      ├─ lean file1.lean  ← Layer 2 → "Lean build"
                      ├─ lean file2.lean  ← Layer 2 → "Lean build"
                      └─ lean file3.lean  ← Layer 2 → "Lean build"
```

Produces:
```
Cursor                     lord    15    2.0   3.5   900M
Lean build                 lord    25   85.0   4.2   1.4G
```

### Layer 2: Build / Tool Grouping

Goal: group parallel invocations of compilers, build systems, and dev tools.

```python
TOOL_PATTERNS = [
    # Lean ecosystem
    ToolPattern(exe="lean",      name="Lean",       category="compiler"),
    ToolPattern(exe="lake",      name="Lake",       category="build"),
    ToolPattern(exe="leanc",     name="Lean",       category="compiler"),

    # Coq / Rocq ecosystem
    ToolPattern(exe="coqc",      name="Coq",        category="compiler"),
    ToolPattern(exe="coqtop",    name="Coq",        category="compiler"),
    ToolPattern(exe="coqchk",    name="Coq",        category="compiler"),
    ToolPattern(exe="coqidetop", name="Coq",        category="compiler"),
    ToolPattern(exe="rocq",      name="Rocq",       category="compiler"),
    ToolPattern(exe="rocqc",     name="Rocq",       category="compiler"),
    ToolPattern(exe="dune",      name="Dune",       category="build"),

    # OCaml ecosystem
    ToolPattern(exe="ocamlopt",  name="OCaml",      category="compiler"),
    ToolPattern(exe="ocamlc",    name="OCaml",      category="compiler"),
    ToolPattern(exe="ocamlfind", name="OCaml",      category="build"),
    ToolPattern(exe="ocamldep",  name="OCaml",      category="compiler"),
    ToolPattern(exe="ocamllex",  name="OCaml",      category="compiler"),
    ToolPattern(exe="ocamlyacc", name="OCaml",      category="compiler"),
    ToolPattern(exe="opam",      name="opam",       category="build"),

    # C/C++ toolchain
    ToolPattern(exe="gcc",       name="GCC",        category="compiler"),
    ToolPattern(exe="g++",       name="GCC",        category="compiler"),
    ToolPattern(exe="cc1",       name="GCC",        category="compiler"),
    ToolPattern(exe="cc1plus",   name="GCC",        category="compiler"),
    ToolPattern(exe="clang",     name="Clang",      category="compiler"),
    ToolPattern(exe="clang++",   name="Clang",      category="compiler"),
    ToolPattern(exe="ld",        name="Linker",     category="compiler"),
    ToolPattern(exe="ld.lld",    name="Linker",     category="compiler"),
    ToolPattern(exe="ld.gold",   name="Linker",     category="compiler"),
    ToolPattern(exe="as",        name="Assembler",  category="compiler"),

    # Rust toolchain
    ToolPattern(exe="rustc",     name="Rust",       category="compiler"),
    ToolPattern(exe="cargo",     name="Cargo",      category="build"),
    ToolPattern(exe="rust-analyzer", name="Rust",   category="lsp"),

    # Go toolchain
    ToolPattern(exe="go",        name="Go",         category="compiler"),
    ToolPattern(exe="gopls",     name="Go",         category="lsp"),

    # Build systems
    ToolPattern(exe="make",      name="Make",       category="build"),
    ToolPattern(exe="ninja",     name="Ninja",      category="build"),
    ToolPattern(exe="cmake",     name="CMake",      category="build"),
    ToolPattern(exe="meson",     name="Meson",      category="build"),
    ToolPattern(exe="bazel",     name="Bazel",      category="build"),
    ToolPattern(exe="scons",     name="SCons",      category="build"),

    # Haskell toolchain
    ToolPattern(exe="ghc",       name="GHC",        category="compiler"),
    ToolPattern(exe="cabal",     name="Cabal",      category="build"),
    ToolPattern(exe="stack",     name="Stack",      category="build"),

    # JVM
    ToolPattern(exe="javac",     name="Java",       category="compiler"),
    ToolPattern(exe="java",      name="Java",       category="runtime"),
    ToolPattern(exe="gradle",    name="Gradle",     category="build"),
    ToolPattern(exe="mvn",       name="Maven",      category="build"),
]
```

**Note on interpreted runtimes (Python, Node, Ruby, etc.):** these are not
tool patterns. `python3`, `node`, `ruby` are transparent runtimes — the
identity of the process is the *script* they run, not the interpreter.
See "Runtime transparency" below.

#### Runtime transparency

When a process exe is a known runtime (`python`, `python3`, `node`, `ruby`,
`perl`, etc.), we look through the runtime to the actual script/module:

```python
TRANSPARENT_RUNTIMES = ["python", "python3", "python3.11", "python3.12",
                        "python3.13", "node", "ruby", "perl"]
```

For a process with exe `python3` and cmdline
`/usr/bin/python3 /usr/bin/blueman-tray`, the effective identity is
`blueman-tray`. This identity is then matched against Layer 1 app patterns
and Layer 3 system categories like any other exe.

Implementation: in `ProcessInfo` post-processing, if `exe` is in
`TRANSPARENT_RUNTIMES`, extract the script basename from `cmdline` argv[1]
and use it as the effective `exe` for grouping purposes. The original `exe`
is preserved for display in expanded process details.

Multiple processes with same tool pattern are merged. Display name includes
context when available:

```
Lean build (24 procs)      lord     25   85.0   4.2   1.4G
GCC                        lord      6   12.0   0.3   180M
```

**Smart merging**: if a tool's tree-root is another tool (e.g., `lake` spawns
`lean`), merge them under the more numerous/interesting child:
`lake` + 24×`lean` → "Lean build (25 procs)".

### Layer 3: System Semantic Categories

Goal: group system processes by **function** so the user can see at a glance
how much CPU/memory the kernel, audio stack, or network stack is consuming.

```python
SYSTEM_CATEGORIES = {
    "Kernel": {
        "match": lambda p: not p.cmdline,  # kernel threads have empty cmdline
    },
    "Display Server": {
        "exe": ["Xorg", "Xwayland", "mutter", "kwin", "sway", "hyprland",
                "wlroots", "gnome-shell"],
    },
    "Window Manager": {
        "exe": ["i3", "i3bar", "i3status", "py3status", "polybar",
                "bspwm", "openbox", "picom", "compton", "dunst", "waybar",
                "rofi", "dmenu"],
    },
    "Audio": {
        "exe": ["pipewire", "pipewire-pulse", "wireplumber",
                "pulseaudio", "alsa", "speech-dispatch",
                "sd_espeak-ng", "sd_dummy", "sd_openjtalk"],
    },
    "Network": {
        "exe": ["NetworkManager", "wpa_supplicant", "systemd-resolved",
                "openvpn", "wireguard", "protonvpn", "protonvpn-app",
                "dnsmasq", "avahi-daemon"],
    },
    "Bluetooth": {
        "exe": ["bluetoothd", "blueman-applet", "blueman-tray",
                "blueman-manager", "obexd"],
    },
    "Printing": {
        "exe": ["cupsd", "cups-browsed", "cups-lpd"],
    },
    "File Services": {
        "exe_prefix": ["gvfsd", "gvfs-"],
        "exe": ["udisksd", "tracker-miner", "tracker-extract", "baloo"],
    },
    "Security / Auth": {
        "exe": ["polkitd", "gnome-keyring-d", "gpg-agent",
                "ssh-agent", "pam", "at-spi-bus-laun",
                "at-spi2-registr", "xdg-permission-", "xdg-document-po"],
    },
    "Session / Desktop": {
        "exe": ["systemd", "dbus-daemon", "dconf-service", "xdg-desktop-por",
                "snapd-desktop-i", "goa-daemon", "goa-identity-se",
                "xss-lock", "xautolock", "flameshot", "nm-applet",
                "colord"],
    },
    "Logging / Monitoring": {
        "exe": ["rsyslogd", "systemd-journal", "kerneloops", "abrtd"],
    },
    "Virtualization": {
        "exe": ["libvirtd", "virtlogd", "virtlockd", "qemu", "catatonit",
                "containerd", "dockerd", "podman"],
    },
}
```

Each category aggregates all matching processes into one group.
Fine-grained breakdown is available on expansion (see Hierarchical Expansion).

**Note on ambiguity**: a process like `dbus-daemon` could be a user session bus
or the system bus. We resolve this by UID: system dbus (uid=0 or
messagebus) → "Session / Desktop"; user dbus (uid=1000) → left
uncategorized or grouped with the owning session.

### Layer 4: Catch-all

Processes not matched by any previous layer are grouped by **normalized exe
name**. If a group has very low activity (below configured thresholds), it is
bucketed into "other (N)" as today. But the threshold is configurable and the
"other" bucket is **expandable** (see below).

### Post-Processing

1. **User split**: groups are keyed by `(category, uid)` — same app run by
   different users stays separate.
2. **Dedup by name**: merge groups with identical display names and same user.
3. **No more blind bucketing**: instead of "user services" catching everything
   small, we now have semantic categories. The catch-all bucket only contains
   truly uncategorized processes.

## Hierarchical Expansion (Tree Traversal)

### Data Model

```python
@dataclass
class ProcessGroup:
    name: str
    proc_count: int
    cpu_pct: float
    mem_bytes: int
    mem_pct: float
    user: str = ""
    category: str = ""          # "app", "tool", "system", "other"
    children: list[ProcessGroup] = field(default_factory=list)
    processes: list[ProcessInfo] = field(default_factory=list)
    expanded: bool = False      # UI state
    depth: int = 0              # nesting level for rendering
```

### Expansion Levels

```
▶ Firefox                     lord    32    4.2   8.3   2.1G   ← collapsed (default)
```
Press Enter/Right to expand:
```
▼ Firefox                     lord    32    4.2   8.3   2.1G
    Web Content (12)                  12    2.1   4.0   1.0G
    Isolated Web Co (15)              15    1.5   3.2   800M
    WebExtensions                      1    0.3   0.5   120M
    RDD Process                        1    0.1   0.2    60M
    GPU Process                        1    0.1   0.2    50M
    Socket Process                     1    0.0   0.1    30M
    Main Process                       1    0.1   0.1    40M
```
Expand further on a sub-group:
```
▼ Firefox                     lord    32    4.2   8.3   2.1G
  ▼ Web Content (12)                  12    2.1   4.0   1.0G
      PID 3835524  -contentproc ...         0.3   0.4   100M
      PID 3835752  -contentproc ...         0.2   0.3    90M
      ...
    Isolated Web Co (15)              15    1.5   3.2   800M
    ...
```

### Expansion for System Categories

```
▶ Kernel                      root   350    0.1   0.0     0B   ← collapsed
▶ Audio                       lord     4    0.2   0.1    40M
▶ Network                     root     5    0.0   0.1    60M
```
Expand "Audio":
```
▼ Audio                       lord     4    0.2   0.1    40M
    pipewire                           1    0.1   0.0    15M
    pipewire-pulse                     1    0.0   0.0    10M
    wireplumber                        1    0.1   0.0    10M
    speech-dispatcher                  1    0.0   0.0     5M
```

### UI Interaction

| Key | Action |
|---|---|
| Enter / → | Expand selected group |
| ← / Backspace | Collapse selected group |
| ↑ / ↓ | Move selection |
| s | Cycle sort (cpu → mem → count) |
| u | Toggle user filter |

The current scroll-based model changes to a **cursor-based selection model**:
- A visible cursor (highlighted row) tracks the selected group
- Scroll follows the cursor when it moves out of the visible area
- Expansion/collapse happens at the cursor position

## Decisions (resolved)

1. **Terminals do not include their children.** WezTerm/Alacritty/etc. are
   grouped as a Layer 1 app containing only the terminal GUI process itself.
   Shells and programs launched inside the terminal are independent — they get
   grouped by their own identity (Layer 1 app, Layer 2 tool, or Layer 4
   catch-all). Users think "my Firefox" and "my Lean build" as separate from
   the terminal window.

2. **Runtimes (python, node, ruby, etc.) are transparent.** `python3` is not
   a grouping identity — it is a runtime, like a path component. The process
   `python3 /usr/bin/blueman-tray` is identified as `blueman-tray` and matched
   against Layer 1/Layer 3 patterns normally. Multiple unrecognized python
   scripts are grouped individually by script name, not lumped into "Python".

3. **Per-user grouping only.** Same app by different UIDs → separate groups.
   No per-session splitting.

## Configuration Reference

All pattern lists and paths are configurable. Built-in defaults provide
reasonable coverage; user config overrides or extends them.

### Full config.toml syntax

```toml
[display]
refresh_interval = 3          # seconds between updates
color = "auto"                # "auto" | "always" | "never"
cpu_layout = "auto"           # "auto" | "1col" | "2col"
show_swap = true
show_cpu_freq = true
show_cpu_temp = true

# ─── Grouping ──────────────────────────────────────────────────────────

[grouping]
# Paths to scan for .desktop files (Layer 0)
# Default shown below; set to [] to disable .desktop scanning
desktop_dirs = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "~/.local/share/applications",
    "/var/lib/snapd/desktop/applications",
    "/var/lib/flatpak/exports/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
]

# Processes whose exe matches these are treated as transparent wrappers:
# grouping looks through to the first real (non-generic, non-runtime) ancestor/child.
generic_parents = [
    "systemd", "init", "kthreadd",
    "bash", "dash", "sh", "zsh", "fish",
    "sudo", "su", "login", "sshd",
    "tmux", "screen", "env", "start-stop-daemon",
]

# Interpreter runtimes — the process identity comes from argv[1], not the exe.
transparent_runtimes = [
    "python", "python3", "python3.11", "python3.12", "python3.13",
    "node", "ruby", "perl",
]

# Catch-all thresholds (Layer 4 → "other" bucket)
other_cpu_max = 0.1           # % CPU below which a group is considered idle
other_mem_max = "30M"         # memory below which a group is considered small

# Expansion defaults
default_expanded = []         # list of group names to start expanded
expand_threshold = 0          # auto-expand groups with ≤ N processes (0 = off)


# ─── Layer 1: App Patterns ────────────────────────────────────────────

# Each [[grouping.apps]] entry defines an application pattern.
# These are merged with built-in APP_PATTERNS (user entries take priority).
# Fields:
#   exe     (required) — executable name to match (case-insensitive)
#   name    (required) — human-readable display name
#   family  (optional) — "electron" | "gecko" | "chromium" | unset
#                        Controls multi-process child detection strategy.
#   cmdline (optional) — substring to match in cmdline (for ambiguous exes)

# Example: add a custom Electron app
[[grouping.apps]]
exe = "my-electron-app"
name = "My App"
family = "electron"

# Example: match a java app by cmdline
[[grouping.apps]]
exe = "java"
name = "IntelliJ IDEA"
cmdline = "idea.main"

# Example: override a built-in pattern
[[grouping.apps]]
exe = "firefox"
name = "Firefox ESR"
family = "gecko"


# ─── Layer 2: Tool Patterns ───────────────────────────────────────────

# Each [[grouping.tools]] entry defines a build/dev tool pattern.
# Merged with built-in TOOL_PATTERNS (user entries take priority).
# Fields:
#   exe      (required) — executable name to match (case-insensitive)
#   name     (required) — human-readable display name
#   category (optional) — "compiler" | "build" | "lsp" | "runtime"
#                         Tools in the same `name` group are merged.

# Example: add a project-specific build tool
[[grouping.tools]]
exe = "my-compiler"
name = "My Compiler"
category = "compiler"


# ─── Layer 3: System Category Overrides ────────────────────────────────

# Move specific executables into (or out of) system categories.
# Keys are exe names; values are category names from SYSTEM_CATEGORIES.
# Set value to "" to exclude an exe from all categories (→ falls to Layer 4).
[grouping.category_overrides]
"protonvpn-app" = "Network"
"my-custom-daemon" = "Logging / Monitoring"
# "picom" = ""   # uncomment to remove picom from "Window Manager" category


# ─── Theme ─────────────────────────────────────────────────────────────

[theme]
cpu_low    = "#00e676"
cpu_mid    = "#ffb300"
cpu_high   = "#f44336"
cpu_graph  = "#00bcd4"
temp_low   = "#00e676"
temp_mid   = "#ff6d00"
temp_high  = "#f44336"
mem_used   = "#00bcd4"
mem_cached = "#1565c0"
mem_swap   = "#ab47bc"
proc_sort_active = "bold"
proc_count       = "#4dd0e1"
```

### Pattern matching rules

- **exe matching** is case-insensitive and matches the basename only
  (no path component). `exe = "firefox"` matches `/snap/firefox/.../firefox`,
  `/usr/bin/firefox`, etc.
- **cmdline matching** (when specified) is a case-insensitive substring match
  against the full cmdline string.
- **family** determines how child processes are detected:
  - `electron`: children with `--type=renderer|utility|gpu-process|zygote` or
    `--crashpad-handler` in cmdline, same exe in cmdline path.
  - `gecko`: children with `-contentproc` in cmdline, same exe.
  - `chromium`: same as `electron` (Chromium's multi-process model is identical).
  - unset: standard tree-walk only.
- **exe_prefix** (Layer 3 only): matches if the exe starts with the prefix.
  E.g., `"gvfsd"` matches `gvfsd-fuse`, `gvfsd-metadata`, etc.

### Config dataclass changes

```python
@dataclass
class GroupingConfig:
    """Process grouping configuration."""
    desktop_dirs: list[str] = field(default_factory=lambda: [...])
    generic_parents: list[str] = field(default_factory=lambda: [...])
    transparent_runtimes: list[str] = field(default_factory=lambda: [...])
    apps: list[AppPattern] = field(default_factory=list)
    tools: list[ToolPattern] = field(default_factory=list)
    category_overrides: dict[str, str] = field(default_factory=dict)
    other_cpu_max: float = 0.1
    other_mem_max: int = 30 << 20
    default_expanded: list[str] = field(default_factory=list)
    expand_threshold: int = 0
```

## Implementation Plan

### Phase 1: App Recognition + Semantic Categories (no hierarchy yet)
1. Add `AppPattern`, `ToolPattern` dataclasses and built-in pattern tables to a
   new `grouping/patterns.py` module.
2. Add `.desktop` file scanner to `grouping/desktop_entries.py` — runs once at
   startup, produces `dict[str, str]` (exe → display name).
3. Add runtime transparency logic to `collectors/processes.py` — resolve
   effective exe for python/node/ruby processes.
4. Rewrite `group_processes()` to apply the four layers sequentially.
5. Keep the flat `ProcessGroup` output — existing widget works unchanged.
6. Update `config.py` to parse new `GroupingConfig` fields.
7. Update tests.

### Phase 2: Hierarchical Expansion
1. Add `children`, `expanded`, `depth` fields to `ProcessGroup`.
2. Build sub-group hierarchy during grouping (Electron subprocess types,
   Firefox content process labels, per-exe breakdown for system categories).
3. Rewrite `ProcessSection` to support cursor-based selection and
   expand/collapse.
4. Add keybindings in `app.py`.
5. Update CSS for indented rows and expand/collapse indicators.

### Phase 3: Polish
1. Cgroup-based grouping as a supplementary signal (systemd slice → service name).
2. "Search/filter" mode (type to filter process list).
3. Persist expansion state across refreshes.

## Migration

- The current `force_name_group` config key maps directly to Layer 2 tool
  patterns — existing configs continue to work (parsed as shorthand for
  `[[grouping.tools]]` with `name = exe`).
- `generic_parents` is preserved with the same semantics.
- The "user services" bucket is replaced by semantic categories — no more
  mystery bucket.
