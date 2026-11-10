//! Configuration loading and defaults

use std::path::{Path, PathBuf};

const DEFAULT_CONFIG_TOML: &str = r##"# perf-glance configuration
# Config file: ~/.config/perf-glance/config.toml

[display]
refresh_interval = 5
color = "auto"
cpu_layout = "auto"
show_swap = true
show_cpu_freq = true
show_cpu_temp = true

[grouping]
desktop_dirs = ["/usr/share/applications", "/usr/local/share/applications", "~/.local/share/applications", "/var/lib/snapd/desktop/applications", "/var/lib/flatpak/exports/share/applications", "~/.local/share/flatpak/exports/share/applications"]
other_cpu_max = 0.1
other_mem_max = "30M"
default_expanded = []
expand_threshold = 0

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
"##;

/// Config directory path
pub fn config_dir() -> PathBuf {
    directories::ProjectDirs::from("", "", "perf-glance")
        .map(|d| d.config_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from(".config/perf-glance"))
}

/// Default config file path
pub fn default_config_path() -> PathBuf {
    config_dir().join("config.toml")
}

/// Ensure config directory and file exist, creating defaults if needed
pub fn ensure_config_file(path: &Path) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if !path.exists() {
        std::fs::write(path, DEFAULT_CONFIG_TOML)?;
    }
    Ok(())
}

fn parse_bytes(s: &str) -> u64 {
    let s = s.trim();
    if s.is_empty() {
        return 30 << 20;
    }
    let num_str: String = s.chars().take_while(|c| c.is_ascii_digit()).collect();
    let num: u64 = num_str.parse().unwrap_or(30);
    let unit = s
        .trim_start_matches(|c: char| c.is_ascii_digit())
        .trim()
        .to_lowercase();
    match unit.as_str() {
        "" | "b" => num,
        u if u.starts_with('k') => num << 10,
        u if u.starts_with('m') => num << 20,
        u if u.starts_with('g') => num << 30,
        _ => num,
    }
}

fn get_nested<'a>(d: &'a toml::Value, keys: &[&str]) -> Option<&'a toml::Value> {
    let mut current = d;
    for key in keys {
        current = current.get(key)?;
    }
    Some(current)
}

#[derive(Debug, Clone)]
pub struct DisplayConfig {
    pub refresh_interval: u64,
    pub color: String,
    pub cpu_layout: String,
    pub show_swap: bool,
    pub show_cpu_freq: bool,
    pub show_cpu_temp: bool,
}

impl Default for DisplayConfig {
    fn default() -> Self {
        Self {
            refresh_interval: 5,
            color: "auto".into(),
            cpu_layout: "auto".into(),
            show_swap: true,
            show_cpu_freq: true,
            show_cpu_temp: true,
        }
    }
}

pub static DEFAULT_DESKTOP_DIRS: &[&str] = &[
    "/usr/share/applications",
    "/usr/local/share/applications",
    "~/.local/share/applications",
    "/var/lib/snapd/desktop/applications",
    "/var/lib/flatpak/exports/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
];

#[derive(Debug, Clone)]
pub struct GroupingConfig {
    pub desktop_dirs: Vec<String>,
    pub other_cpu_max: f64,
    pub other_mem_max: u64,
    pub default_expanded: Vec<String>,
    pub expand_threshold: u32,
}

impl Default for GroupingConfig {
    fn default() -> Self {
        Self {
            desktop_dirs: DEFAULT_DESKTOP_DIRS.iter().map(|s| s.to_string()).collect(),
            other_cpu_max: 0.1,
            other_mem_max: 30 << 20,
            default_expanded: vec![],
            expand_threshold: 0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ThemeConfig {
    pub cpu_low: String,
    pub cpu_mid: String,
    pub cpu_high: String,
    pub cpu_graph: String,
    pub temp_low: String,
    pub temp_mid: String,
    pub temp_high: String,
    pub mem_used: String,
    pub mem_cached: String,
    pub mem_swap: String,
    pub proc_sort_active: String,
    pub proc_count: String,
}

impl Default for ThemeConfig {
    fn default() -> Self {
        Self {
            cpu_low: "#00e676".into(),
            cpu_mid: "#ffb300".into(),
            cpu_high: "#f44336".into(),
            cpu_graph: "#00bcd4".into(),
            temp_low: "#00e676".into(),
            temp_mid: "#ff6d00".into(),
            temp_high: "#f44336".into(),
            mem_used: "#00bcd4".into(),
            mem_cached: "#1565c0".into(),
            mem_swap: "#ab47bc".into(),
            proc_sort_active: "bold".into(),
            proc_count: "#4dd0e1".into(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct Config {
    pub display: DisplayConfig,
    pub grouping: GroupingConfig,
    pub theme: ThemeConfig,
}

impl Config {
    pub fn load(path: Option<&Path>) -> std::io::Result<Self> {
        let default_path = default_config_path();
        let path = path.unwrap_or(&default_path);
        ensure_config_file(path)?;
        let content = std::fs::read_to_string(path)?;
        let raw: toml::Value = toml::from_str(&content).map_err(|e| {
            std::io::Error::new(std::io::ErrorKind::InvalidData, e.to_string())
        })?;

        let empty_table = toml::Value::Table(toml::map::Map::new());
        let display = {
            let d = get_nested(&raw, &["display"]).unwrap_or(&empty_table);
            DisplayConfig {
                refresh_interval: d.get("refresh_interval").and_then(|v| v.as_integer()).unwrap_or(5) as u64,
                color: d.get("color").and_then(|v| v.as_str()).unwrap_or("auto").to_string(),
                cpu_layout: d.get("cpu_layout").and_then(|v| v.as_str()).unwrap_or("auto").to_string(),
                show_swap: d.get("show_swap").and_then(|v| v.as_bool()).unwrap_or(true),
                show_cpu_freq: d.get("show_cpu_freq").and_then(|v| v.as_bool()).unwrap_or(true),
                show_cpu_temp: d.get("show_cpu_temp").and_then(|v| v.as_bool()).unwrap_or(true),
            }
        };

        let grouping = {
            let g = get_nested(&raw, &["grouping"]).unwrap_or(&empty_table);
            // Legacy keys (apps, tools, generic_parents, etc.) are ignored;
            // grouping rules come from rules.d. Same config path, backwards compatible.
            let desktop_dirs: Vec<String> = g
                .get("desktop_dirs")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_else(|| DEFAULT_DESKTOP_DIRS.iter().map(|s| s.to_string()).collect());
            let other_mem_str = g.get("other_mem_max").and_then(|v| v.as_str()).unwrap_or("30M");
            GroupingConfig {
                desktop_dirs,
                other_cpu_max: g.get("other_cpu_max").and_then(|v| v.as_float()).unwrap_or(0.1) as f64,
                other_mem_max: parse_bytes(other_mem_str),
                default_expanded: g
                    .get("default_expanded")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_string()))
                            .collect()
                    })
                    .unwrap_or_default(),
                expand_threshold: g.get("expand_threshold").and_then(|v| v.as_integer()).unwrap_or(0) as u32,
            }
        };

        let theme = {
            let t = get_nested(&raw, &["theme"]).unwrap_or(&empty_table);
            ThemeConfig {
                cpu_low: t.get("cpu_low").and_then(|v| v.as_str()).unwrap_or("#00e676").to_string(),
                cpu_mid: t.get("cpu_mid").and_then(|v| v.as_str()).unwrap_or("#ffb300").to_string(),
                cpu_high: t.get("cpu_high").and_then(|v| v.as_str()).unwrap_or("#f44336").to_string(),
                cpu_graph: t.get("cpu_graph").and_then(|v| v.as_str()).unwrap_or("#00bcd4").to_string(),
                temp_low: t.get("temp_low").and_then(|v| v.as_str()).unwrap_or("#00e676").to_string(),
                temp_mid: t.get("temp_mid").and_then(|v| v.as_str()).unwrap_or("#ff6d00").to_string(),
                temp_high: t.get("temp_high").and_then(|v| v.as_str()).unwrap_or("#f44336").to_string(),
                mem_used: t.get("mem_used").and_then(|v| v.as_str()).unwrap_or("#00bcd4").to_string(),
                mem_cached: t.get("mem_cached").and_then(|v| v.as_str()).unwrap_or("#1565c0").to_string(),
                mem_swap: t.get("mem_swap").and_then(|v| v.as_str()).unwrap_or("#ab47bc").to_string(),
                proc_sort_active: t.get("proc_sort_active").and_then(|v| v.as_str()).unwrap_or("bold").to_string(),
                proc_count: t.get("proc_count").and_then(|v| v.as_str()).unwrap_or("#4dd0e1").to_string(),
            }
        };

        Ok(Config {
            display,
            grouping,
            theme,
        })
    }
}
