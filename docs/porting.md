# Python vs Rust: User-visible Differences

Functional differences that users will notice, grouped by platform.

---

## 1. Platform-independent

- **Color mode** (`display.color`): Python honors "auto" / "always" / "never"; Rust always uses colors [OK]
- **CPU layout** (`display.cpu_layout`): Python honors "1col" / "2col" / "auto"; Rust has fixed layout [OK]
- **Legacy config**: Python errors on old `[grouping]` keys, forces migration; Rust accepts old config, ignores legacy keys [OK]
- **Filter input**: Python has dedicated input widget, live-as-you-type; Rust uses inline filter bar [OK]
- **Help**: Python `--help` shows usage; Rust has no `--help` 

---

## 2. Linux

- **Footer key labels**: Python shows "k kill" and "K kill-9" separately; Rust shows "k/K kill" combined [OK]
- **Per-core frequency**: Python e.g. "3.2G"; Rust e.g. "0.6G" (different scale or source)
---

## 3. Mac

- **App names** (e.g. "Firefox" instead of "firefox"): Python resolves `.app` bundle names from Info.plist; Rust shows raw executable names
- **Process popup** (Enter): Python shows State, Threads, exe path, cwd, age; Rust shows "?" or "[unavailable]" for State/Threads/exe/cwd/age
- **Temperature**: Python shows CPU temp when available; Rust does not show it
- **User names**: Python resolved from UID; Rust shows numeric UID
