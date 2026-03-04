"""App and tool pattern definitions for process grouping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AppPattern:
    """Application pattern for Layer 1 recognition.

    family: "electron" | "gecko" | "chromium" for multi-process detection, or unset.
    cmdline: optional substring to match in cmdline (for ambiguous exes like java).
    """

    exe: str
    name: str
    family: str = ""
    cmdline: str = ""


@dataclass(frozen=True)
class ToolPattern:
    """Build/dev tool pattern for Layer 2 grouping.

    category: "compiler" | "build" | "lsp" | "runtime" — tools with same name merge.
    """

    exe: str
    name: str
    category: str = ""


# Interpreter runtimes — process identity comes from argv[1], not the exe.
TRANSPARENT_RUNTIMES = [
    "python",
    "python3",
    "python3.11",
    "python3.12",
    "python3.13",
    "node",
    "ruby",
    "perl",
]

APP_PATTERNS = [
    # Electron apps — match main exe, children auto-grouped
    AppPattern(exe="cursor", name="Cursor", family="electron"),
    AppPattern(exe="code", name="VS Code", family="electron"),
    AppPattern(exe="slack", name="Slack", family="electron"),
    AppPattern(exe="discord", name="Discord", family="electron"),
    AppPattern(exe="signal-desktop", name="Signal", family="electron"),
    AppPattern(exe="teams", name="Teams", family="electron"),
    AppPattern(exe="spotify", name="Spotify", family="electron"),
    AppPattern(exe="obsidian", name="Obsidian", family="electron"),
    # Gecko (Firefox-based)
    AppPattern(exe="firefox", name="Firefox", family="gecko"),
    AppPattern(exe="thunderbird", name="Thunderbird", family="gecko"),
    AppPattern(exe="librewolf", name="LibreWolf", family="gecko"),
    # Chromium-based (non-Electron)
    AppPattern(exe="chrome", name="Chrome", family="chromium"),
    AppPattern(exe="chromium", name="Chromium", family="chromium"),
    AppPattern(exe="brave", name="Brave", family="chromium"),
    AppPattern(exe="vivaldi", name="Vivaldi", family="chromium"),
    AppPattern(exe="opera", name="Opera", family="chromium"),
    # Native GUI apps
    AppPattern(exe="emacs", name="Emacs"),
    AppPattern(exe="gimp", name="GIMP"),
    AppPattern(exe="blender", name="Blender"),
    AppPattern(exe="inkscape", name="Inkscape"),
    AppPattern(exe="libreoffice", name="LibreOffice"),
    AppPattern(exe="vlc", name="VLC"),
    AppPattern(exe="mpv", name="mpv"),
    AppPattern(exe="steam", name="Steam", family="electron"),
    AppPattern(exe="dropbox", name="Dropbox"),
    # Terminals (GUI process only — children are independent)
    AppPattern(exe="wezterm-gui", name="WezTerm"),
    AppPattern(exe="alacritty", name="Alacritty"),
    AppPattern(exe="kitty", name="Kitty"),
    AppPattern(exe="gnome-terminal", name="GNOME Terminal"),
    AppPattern(exe="konsole", name="Konsole"),
    AppPattern(exe="xterm", name="xterm"),
]

TOOL_PATTERNS = [
    # Lean ecosystem
    ToolPattern(exe="lean", name="Lean", category="compiler"),
    ToolPattern(exe="lake", name="Lake", category="build"),
    ToolPattern(exe="leanc", name="Lean", category="compiler"),
    # Coq / Rocq ecosystem
    ToolPattern(exe="coqc", name="Coq", category="compiler"),
    ToolPattern(exe="coqtop", name="Coq", category="compiler"),
    ToolPattern(exe="coqchk", name="Coq", category="compiler"),
    ToolPattern(exe="coqidetop", name="Coq", category="compiler"),
    ToolPattern(exe="rocq", name="Rocq", category="compiler"),
    ToolPattern(exe="rocqc", name="Rocq", category="compiler"),
    ToolPattern(exe="dune", name="Dune", category="build"),
    # OCaml ecosystem
    ToolPattern(exe="ocamlopt", name="OCaml", category="compiler"),
    ToolPattern(exe="ocamlc", name="OCaml", category="compiler"),
    ToolPattern(exe="ocamlfind", name="OCaml", category="build"),
    ToolPattern(exe="ocamldep", name="OCaml", category="compiler"),
    ToolPattern(exe="ocamllex", name="OCaml", category="compiler"),
    ToolPattern(exe="ocamlyacc", name="OCaml", category="compiler"),
    ToolPattern(exe="opam", name="opam", category="build"),
    # C/C++ toolchain
    ToolPattern(exe="gcc", name="GCC", category="compiler"),
    ToolPattern(exe="g++", name="GCC", category="compiler"),
    ToolPattern(exe="cc1", name="GCC", category="compiler"),
    ToolPattern(exe="cc1plus", name="GCC", category="compiler"),
    ToolPattern(exe="clang", name="Clang", category="compiler"),
    ToolPattern(exe="clang++", name="Clang", category="compiler"),
    ToolPattern(exe="ld", name="Linker", category="compiler"),
    ToolPattern(exe="ld.lld", name="Linker", category="compiler"),
    ToolPattern(exe="ld.gold", name="Linker", category="compiler"),
    ToolPattern(exe="as", name="Assembler", category="compiler"),
    # Rust toolchain
    ToolPattern(exe="rustc", name="Rust", category="compiler"),
    ToolPattern(exe="cargo", name="Cargo", category="build"),
    ToolPattern(exe="rust-analyzer", name="Rust", category="lsp"),
    # Go toolchain
    ToolPattern(exe="go", name="Go", category="compiler"),
    ToolPattern(exe="gopls", name="Go", category="lsp"),
    # Build systems
    ToolPattern(exe="make", name="Make", category="build"),
    ToolPattern(exe="ninja", name="Ninja", category="build"),
    ToolPattern(exe="cmake", name="CMake", category="build"),
    ToolPattern(exe="meson", name="Meson", category="build"),
    ToolPattern(exe="bazel", name="Bazel", category="build"),
    ToolPattern(exe="scons", name="SCons", category="build"),
    # Haskell toolchain
    ToolPattern(exe="ghc", name="GHC", category="compiler"),
    ToolPattern(exe="cabal", name="Cabal", category="build"),
    ToolPattern(exe="stack", name="Stack", category="build"),
    # JVM
    ToolPattern(exe="javac", name="Java", category="compiler"),
    ToolPattern(exe="java", name="Java", category="runtime"),
    ToolPattern(exe="gradle", name="Gradle", category="build"),
    ToolPattern(exe="mvn", name="Maven", category="build"),
]


def _kernel_match(proc: object) -> bool:
    """Kernel threads have empty cmdline."""
    return not getattr(proc, "cmdline", None)


# System categories: exe lists, exe_prefix lists, or special match.
# Kernel uses a match function; others use exe/exe_prefix.
SystemCategoryDef = dict[str, list[str] | Callable[[object], bool]]

SYSTEM_CATEGORIES: dict[str, SystemCategoryDef] = {
    "Kernel": {"match": _kernel_match},
    "Display Server": {
        "exe": [
            "Xorg",
            "Xwayland",
            "mutter",
            "kwin",
            "sway",
            "hyprland",
            "wlroots",
            "gnome-shell",
        ],
    },
    "Window Manager": {
        "exe": [
            "i3",
            "i3bar",
            "i3status",
            "py3status",
            "polybar",
            "bspwm",
            "openbox",
            "picom",
            "compton",
            "dunst",
            "waybar",
            "rofi",
            "dmenu",
        ],
    },
    "Audio": {
        "exe": [
            "pipewire",
            "pipewire-pulse",
            "wireplumber",
            "pulseaudio",
            "alsa",
            "speech-dispatch",
            "sd_espeak-ng",
            "sd_dummy",
            "sd_openjtalk",
        ],
    },
    "Network": {
        "exe": [
            "NetworkManager",
            "wpa_supplicant",
            "systemd-resolved",
            "openvpn",
            "wireguard",
            "protonvpn",
            "protonvpn-app",
            "dnsmasq",
            "avahi-daemon",
        ],
    },
    "Bluetooth": {
        "exe": [
            "bluetoothd",
            "blueman-applet",
            "blueman-tray",
            "blueman-manager",
            "obexd",
        ],
    },
    "Printing": {
        "exe": ["cupsd", "cups-browsed", "cups-lpd"],
    },
    "File Services": {
        "exe_prefix": ["gvfsd", "gvfs-"],
        "exe": ["udisksd", "tracker-miner", "tracker-extract", "baloo"],
    },
    "Security / Auth": {
        "exe": [
            "polkitd",
            "gnome-keyring-d",
            "gpg-agent",
            "ssh-agent",
            "pam",
            "at-spi-bus-laun",
            "at-spi2-registr",
            "xdg-permission-",
            "xdg-document-po",
        ],
    },
    "Session / Desktop": {
        "exe": [
            "systemd",
            "dbus-daemon",
            "dconf-service",
            "xdg-desktop-por",
            "snapd-desktop-i",
            "goa-daemon",
            "goa-identity-se",
            "xss-lock",
            "xautolock",
            "flameshot",
            "nm-applet",
            "colord",
        ],
    },
    "Logging / Monitoring": {
        "exe": ["rsyslogd", "systemd-journal", "kerneloops", "abrtd"],
    },
    "Virtualization": {
        "exe": [
            "libvirtd",
            "virtlogd",
            "virtlockd",
            "qemu",
            "catatonit",
            "containerd",
            "dockerd",
            "podman",
        ],
    },
}
