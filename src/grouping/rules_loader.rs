//! Load grouping rules from builtin/system/user rules.d directories

use crate::grouping::patterns::{AppPattern, ToolPattern};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct SystemCategory {
    pub id: String,
    pub name: String,
    pub exe: Vec<String>,
    pub exe_prefix: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct LauncherMatch {
    pub argv_prefix: Vec<String>,
    pub argv1_in: Vec<String>,
    pub min_argv: usize,
}

#[derive(Debug, Clone)]
pub struct LauncherStep {
    pub kind: String,
    pub start_index: usize,
    pub stop_at_double_dash: bool,
    pub flags_with_value: Vec<String>,
    pub module_flag: String,
    pub abort_flags: Vec<String>,
    pub flag: String,
    pub index: i32,
}

#[derive(Debug, Clone)]
pub struct LauncherTransform {
    pub basename: bool,
    pub lowercase: bool,
    pub strip_trailing_punct: bool,
    pub strip_npm_scope: bool,
    pub java_class_tail: bool,
    pub generic_entrypoint_fallback: bool,
}

#[derive(Debug, Clone)]
pub struct LauncherRule {
    pub id: String,
    pub exe: String,
    pub match_: LauncherMatch,
    pub steps: Vec<LauncherStep>,
    pub transform: LauncherTransform,
}

#[derive(Debug, Clone)]
pub struct CompiledRules {
    pub apps: Vec<AppPattern>,
    pub tools: Vec<ToolPattern>,
    pub system_categories: Vec<SystemCategory>,
    pub category_overrides: std::collections::HashMap<String, String>,
    pub launchers_by_exe: std::collections::HashMap<String, Vec<LauncherRule>>,
    pub generic_parents: Vec<String>,
    pub transparent_runtimes: Vec<String>,
}

fn norm_key(s: &str) -> String {
    s.trim().to_lowercase()
}

fn builtin_rules_dir() -> PathBuf {
    // Development: rules next to Cargo.toml
    if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
        let p = PathBuf::from(manifest_dir).join("rules").join("builtin.d");
        if p.is_dir() {
            return p;
        }
    }
    // Installed: common paths
    let candidates = [
        PathBuf::from("/usr/share/perf-glance/rules/builtin.d"),
        PathBuf::from("/usr/local/share/perf-glance/rules/builtin.d"),
    ];
    for c in &candidates {
        if c.is_dir() {
            return c.clone();
        }
    }
    // Fallback
    PathBuf::from("rules/builtin.d")
}

fn iter_rule_files(base: &Path) -> Vec<PathBuf> {
    if !base.is_dir() {
        return vec![];
    }
    let mut files: Vec<PathBuf> = std::fs::read_dir(base)
        .into_iter()
        .flatten()
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.is_file() && p.extension().map_or(false, |e| e == "toml"))
        .collect();
    files.sort();
    files
}

fn as_str_list(value: &toml::Value) -> Vec<String> {
    value
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.trim().to_string()))
                .filter(|s| !s.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

fn parse_app(entry: &toml::Value) -> Option<AppPattern> {
    let t = entry.as_table()?;
    let id = t.get("id")?.as_str()?.trim();
    let exe = norm_key(t.get("exe")?.as_str()?);
    let name = t.get("name")?.as_str()?.trim();
    if id.is_empty() || exe.is_empty() || name.is_empty() {
        return None;
    }
    Some(AppPattern {
        exe,
        name: name.to_string(),
        family: t.get("family").and_then(|v| v.as_str()).unwrap_or("").trim().to_lowercase(),
        cmdline: t.get("cmdline").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        no_tool_reclaim: t.get("no_tool_reclaim").and_then(|v| v.as_bool()).unwrap_or(false),
    })
}

fn parse_tool(entry: &toml::Value) -> Option<ToolPattern> {
    let t = entry.as_table()?;
    let id = t.get("id")?.as_str()?.trim();
    let exe = norm_key(t.get("exe")?.as_str()?);
    let name = t.get("name")?.as_str()?.trim();
    if id.is_empty() || exe.is_empty() || name.is_empty() {
        return None;
    }
    Some(ToolPattern {
        exe,
        name: name.to_string(),
        category: t.get("category").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        cmdline: t.get("cmdline").and_then(|v| v.as_str()).unwrap_or("").trim().to_string(),
        build: t.get("build").and_then(|v| v.as_bool()).unwrap_or(true),
    })
}

fn parse_system_category(entry: &toml::Value) -> Option<SystemCategory> {
    let t = entry.as_table()?;
    let id = t.get("id")?.as_str()?.trim();
    let name = t.get("name")?.as_str()?.trim();
    if id.is_empty() || name.is_empty() {
        return None;
    }
    let exe: Vec<String> = as_str_list(t.get("exe").unwrap_or(&toml::Value::Array(vec![])))
        .into_iter()
        .map(|s| norm_key(&s))
        .collect();
    let exe_prefix: Vec<String> = as_str_list(t.get("exe_prefix").unwrap_or(&toml::Value::Array(vec![])))
        .into_iter()
        .map(|s| norm_key(&s))
        .collect();
    if exe.is_empty() && exe_prefix.is_empty() {
        return None;
    }
    Some(SystemCategory {
        id: id.to_string(),
        name: name.to_string(),
        exe,
        exe_prefix,
    })
}

fn parse_category_override(entry: &toml::Value) -> Option<(String, String)> {
    let t = entry.as_table()?;
    let exe = norm_key(t.get("exe")?.as_str()?);
    let category = t.get("category")?.as_str()?.to_string();
    if exe.is_empty() {
        return None;
    }
    Some((exe, category))
}

fn parse_launcher_step(step: &toml::Value) -> Option<LauncherStep> {
    let t = step.as_table()?;
    let kind = t.get("kind")?.as_str()?.trim();
    if !["next_after_flag", "first_non_flag", "argv_at", "first_non_flag_after_prefix"].contains(&kind) {
        return None;
    }
    Some(LauncherStep {
        kind: kind.to_string(),
        start_index: t.get("start_index").and_then(|v| v.as_integer()).unwrap_or(1) as usize,
        stop_at_double_dash: t.get("stop_at_double_dash").and_then(|v| v.as_bool()).unwrap_or(true),
        flags_with_value: as_str_list(t.get("flags_with_value").unwrap_or(&toml::Value::Array(vec![]))),
        module_flag: t.get("module_flag").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        abort_flags: as_str_list(t.get("abort_flags").unwrap_or(&toml::Value::Array(vec![]))),
        flag: t.get("flag").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        index: t.get("index").and_then(|v| v.as_integer()).unwrap_or(-1) as i32,
    })
}

fn parse_launcher_match(m: &toml::Value) -> LauncherMatch {
    let empty = toml::map::Map::new();
    let t = m.as_table().unwrap_or(&empty);
    LauncherMatch {
        argv_prefix: as_str_list(t.get("argv_prefix").unwrap_or(&toml::Value::Array(vec![]))),
        argv1_in: as_str_list(t.get("argv1_in").unwrap_or(&toml::Value::Array(vec![]))),
        min_argv: t.get("min_argv").and_then(|v| v.as_integer()).unwrap_or(0) as usize,
    }
}

fn parse_launcher_transform(t: &toml::Value) -> LauncherTransform {
    let empty = toml::map::Map::new();
    let tab = t.as_table().unwrap_or(&empty);
    LauncherTransform {
        basename: tab.get("basename").and_then(|v| v.as_bool()).unwrap_or(false),
        lowercase: tab.get("lowercase").and_then(|v| v.as_bool()).unwrap_or(false),
        strip_trailing_punct: tab.get("strip_trailing_punct").and_then(|v| v.as_bool()).unwrap_or(false),
        strip_npm_scope: tab.get("strip_npm_scope").and_then(|v| v.as_bool()).unwrap_or(false),
        java_class_tail: tab.get("java_class_tail").and_then(|v| v.as_bool()).unwrap_or(false),
        generic_entrypoint_fallback: tab.get("generic_entrypoint_fallback").and_then(|v| v.as_bool()).unwrap_or(false),
    }
}

fn parse_launcher(entry: &toml::Value) -> Option<LauncherRule> {
    let t = entry.as_table()?;
    let id = t.get("id")?.as_str()?.trim();
    let exe = norm_key(t.get("exe")?.as_str()?);
    if id.is_empty() || exe.is_empty() {
        return None;
    }
    let steps_arr = t.get("step")?.as_array()?;
    let mut steps = Vec::new();
    for s in steps_arr {
        if let Some(step) = parse_launcher_step(s) {
            steps.push(step);
        }
    }
    if steps.is_empty() {
        return None;
    }
    let match_ = parse_launcher_match(t.get("match").unwrap_or(&toml::Value::Table(toml::map::Map::new())));
    let transform = parse_launcher_transform(t.get("transform").unwrap_or(&toml::Value::Table(toml::map::Map::new())));
    Some(LauncherRule {
        id: id.to_string(),
        exe,
        match_,
        steps,
        transform,
    })
}

struct RawState {
    apps: std::collections::HashMap<String, AppPattern>,
    tools: std::collections::HashMap<String, ToolPattern>,
    system_categories: std::collections::HashMap<String, SystemCategory>,
    category_overrides: std::collections::HashMap<String, String>,
    launchers: std::collections::HashMap<String, LauncherRule>,
    generic_parents: Vec<String>,
    transparent_runtimes: Vec<String>,
}

impl Default for RawState {
    fn default() -> Self {
        Self {
            apps: std::collections::HashMap::new(),
            tools: std::collections::HashMap::new(),
            system_categories: std::collections::HashMap::new(),
            category_overrides: std::collections::HashMap::new(),
            launchers: std::collections::HashMap::new(),
            generic_parents: vec!["systemd".into(), "init".into(), "bash".into(), "sh".into()],
            transparent_runtimes: vec![
                "python".into(), "python3".into(), "python2".into(),
                "node".into(), "nodejs".into(),
                "ruby".into(), "perl".into(),
                "java".into(), "kotlin".into(),
            ],
        }
    }
}

fn load_file(path: &Path, state: &mut RawState) {
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return,
    };
    let raw: toml::Value = match toml::from_str(&content) {
        Ok(v) => v,
        Err(_) => return,
    };
    let schema = raw.get("schema_version").and_then(|v| v.as_integer()).unwrap_or(0);
    if schema != 1 {
        return;
    }

    for entry in raw.get("app").and_then(|v| v.as_array()).unwrap_or(&vec![]) {
        if let toml::Value::Table(t) = entry {
            if let Some(app) = parse_app(&toml::Value::Table(t.clone())) {
                let id = t.get("id").and_then(|v| v.as_str()).unwrap_or("").trim();
                state.apps.insert(if id.is_empty() { app.exe.clone() } else { id.to_string() }, app);
            }
        }
    }

    for entry in raw.get("tool").and_then(|v| v.as_array()).unwrap_or(&vec![]) {
        if let toml::Value::Table(t) = entry {
            if let Some(tool) = parse_tool(&toml::Value::Table(t.clone())) {
                state.tools.insert(tool.exe.clone(), tool);
            }
        }
    }

    for entry in raw.get("system_category").and_then(|v| v.as_array()).unwrap_or(&vec![]) {
        if let toml::Value::Table(t) = entry {
            if let Some(cat) = parse_system_category(&toml::Value::Table(t.clone())) {
                state.system_categories.insert(cat.id.clone(), cat);
            }
        }
    }

    for entry in raw.get("category_override").and_then(|v| v.as_array()).unwrap_or(&vec![]) {
        if let toml::Value::Table(t) = entry {
            if let Some((exe, cat)) = parse_category_override(&toml::Value::Table(t.clone())) {
                state.category_overrides.insert(exe, cat);
            }
        }
    }

    for entry in raw.get("launcher").and_then(|v| v.as_array()).unwrap_or(&vec![]) {
        if let toml::Value::Table(t) = entry {
            if let Some(rule) = parse_launcher(&toml::Value::Table(t.clone())) {
                let id = t.get("id").and_then(|v| v.as_str()).unwrap_or("").trim();
                state.launchers.insert(if id.is_empty() { rule.id.clone() } else { id.to_string() }, rule);
            }
        }
    }

    if let Some(patch) = raw.get("list_patch").and_then(|v| v.as_table()) {
        for x in as_str_list(patch.get("generic_parents_add").unwrap_or(&toml::Value::Array(vec![]))) {
            let x = norm_key(&x);
            if !state.generic_parents.contains(&x) {
                state.generic_parents.push(x);
            }
        }
        let remove: Vec<String> = as_str_list(patch.get("generic_parents_remove").unwrap_or(&toml::Value::Array(vec![])))
            .into_iter().map(|s| norm_key(&s)).collect();
        state.generic_parents.retain(|p| !remove.contains(p));

        let tr_remove: Vec<String> = as_str_list(patch.get("transparent_runtimes_remove").unwrap_or(&toml::Value::Array(vec![])))
            .into_iter().map(|s| norm_key(&s)).collect();
        state.transparent_runtimes.retain(|p| !tr_remove.contains(p));
        for x in as_str_list(patch.get("transparent_runtimes_add").unwrap_or(&toml::Value::Array(vec![]))) {
            let x = norm_key(&x);
            if !state.transparent_runtimes.contains(&x) {
                state.transparent_runtimes.push(x);
            }
        }
    }
}

fn compile(state: RawState) -> CompiledRules {
    let launchers_by_exe: std::collections::HashMap<String, Vec<LauncherRule>> = {
        let mut m: std::collections::HashMap<String, Vec<LauncherRule>> = std::collections::HashMap::new();
        for rule in state.launchers.into_values() {
            m.entry(rule.exe.clone()).or_default().push(rule);
        }
        m
    };
    CompiledRules {
        apps: state.apps.into_values().collect(),
        tools: state.tools.into_values().collect(),
        system_categories: state.system_categories.into_values().collect(),
        category_overrides: state.category_overrides,
        launchers_by_exe,
        generic_parents: state.generic_parents,
        transparent_runtimes: state.transparent_runtimes,
    }
}

static RULES: once_cell::sync::OnceCell<CompiledRules> = once_cell::sync::OnceCell::new();

/// Load grouping rules from builtin, system, and user directories
pub fn load_grouping_rules() -> CompiledRules {
    RULES.get_or_init(|| {
        let builtin_dir = builtin_rules_dir();
        if !builtin_dir.is_dir() {
            return compile(RawState::default());
        }
        let system_dir = PathBuf::from("/etc/perf-glance/rules.d");
        let user_dir = config_dir().join("rules.d");
        let dirs = [&builtin_dir, &system_dir, &user_dir];

        let mut state = RawState::default();
        for dir in dirs {
            for path in iter_rule_files(dir) {
                load_file(&path, &mut state);
            }
        }
        compile(state)
    }).clone()
}

fn config_dir() -> PathBuf {
    crate::config::config_dir()
}
