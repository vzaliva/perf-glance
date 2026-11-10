//! Four-layer process grouping: apps, tools, system categories, catch-all

use crate::collectors::ProcessInfo;
use crate::config::GroupingConfig;
use crate::grouping::rules_loader::{load_grouping_rules, LauncherRule};
use crate::grouping::patterns::{AppPattern, ToolPattern};
use crate::grouping::rules_loader::SystemCategory;
use std::collections::{HashMap, HashSet};

#[derive(Clone, Debug)]
pub struct ProcessGroup {
    pub name: String,
    pub proc_count: usize,
    pub cpu_pct: f32,
    pub mem_bytes: u64,
    pub mem_pct: f32,
    pub user: String,
    pub category: String,
    pub children: Vec<ProcessGroup>,
    pub processes: Vec<ProcessInfo>,
    pub expanded: bool,
    pub depth: u32,
    pub group_key: String,
}

fn uid_to_user(uid: u32) -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(user) = nix::unistd::User::from_uid(nix::unistd::Uid::from_raw(uid)) {
            if let Some(u) = user {
                return u.name;
            }
        }
    }
    uid.to_string()
}

fn normalize_exe(exe: &str) -> String {
    if exe.is_empty() {
        return String::new();
    }
    exe.to_lowercase()
        .rsplit('/')
        .next()
        .unwrap_or(exe)
        .trim_end_matches(|c: char| c == ':' || c == ';' || c == ',')
        .to_string()
}

fn effective_exe(
    proc: &ProcessInfo,
    transparent_runtimes: &HashSet<String>,
    launchers_by_exe: &HashMap<String, Vec<LauncherRule>>,
) -> String {
    let exe = if !proc.exe.is_empty() {
        &proc.exe
    } else {
        &proc.name
    };
    let exe_lower = normalize_exe(exe);
    if exe_lower.is_empty() {
        return String::new();
    }
    let parts: Vec<&str> = proc.cmdline.split_whitespace().collect();
    // Single-element argv is still resolved: runtimes whose process title was
    // rewritten (e.g. node CLIs) only expose the title as argv[0].
    if parts.is_empty() {
        return exe_lower;
    }
    let argv0_base = normalize_exe(parts[0]);
    let mut candidates = Vec::new();
    if !argv0_base.is_empty() && argv0_base != exe_lower && launchers_by_exe.contains_key(&argv0_base) {
        candidates.push(&argv0_base);
    }
    if launchers_by_exe.contains_key(&exe_lower) {
        candidates.push(&exe_lower);
    }
    for cand in candidates {
        if let Some(rules) = launchers_by_exe.get(cand) {
            for rule in rules {
                if let Some(resolved) = resolve_launcher(&parts, rule) {
                    return normalize_exe(&resolved);
                }
            }
        }
    }
    if transparent_runtimes.contains(&exe_lower) {
        if let Some(script) = resolve_script_fallback(&parts) {
            return script;
        }
    }
    exe_lower
}

fn resolve_launcher(parts: &[&str], rule: &LauncherRule) -> Option<String> {
    if rule.match_.min_argv > 0 && parts.len() < rule.match_.min_argv {
        return None;
    }
    if !rule.match_.argv1_in.is_empty() {
        if parts.len() < 2 || !rule.match_.argv1_in.contains(&parts[1].to_string()) {
            return None;
        }
    }
    if !rule.match_.argv_prefix.is_empty() {
        let prefix_len = rule.match_.argv_prefix.len();
        if parts.len() < 1 + prefix_len {
            return None;
        }
        for (i, p) in rule.match_.argv_prefix.iter().enumerate() {
            if parts.get(1 + i) != Some(&p.as_str()) {
                return None;
            }
        }
    }
    for step in &rule.steps {
        let extracted = match step.kind.as_str() {
            "argv_at" => {
                let idx = if step.index >= 0 { step.index as usize } else { step.start_index };
                parts.get(idx).map(|s| (*s).to_string())
            }
            "first_non_flag" => {
                let mut i = step.start_index;
                while i < parts.len() {
                    let arg = parts[i];
                    if step.stop_at_double_dash && arg == "--" {
                        i += 1;
                        break;
                    }
                    if step.abort_flags.contains(&arg.to_string()) {
                        return None;
                    }
                    if !step.module_flag.is_empty() && arg == step.module_flag {
                        return parts.get(i + 1).map(|s| (*s).to_string());
                    }
                    if !arg.starts_with('-') {
                        return Some(arg.to_string());
                    }
                    i += 1;
                }
                parts.get(i).map(|s| (*s).to_string())
            }
            _ => None,
        };
        if let Some(mut val) = extracted {
            if rule.transform.strip_npm_scope && val.starts_with('@') {
                if let Some((_, rest)) = val.split_once('/') {
                    val = rest.to_string();
                }
            }
            if rule.transform.basename {
                val = val.rsplit('/').next().unwrap_or(&val).to_string();
            }
            if rule.transform.strip_trailing_punct {
                val = val.trim_end_matches(|c: char| c == ':' || c == ';' || c == ',').to_string();
            }
            if rule.transform.lowercase {
                val = val.to_lowercase();
            }
            let norm = normalize_exe(&val);
            if !norm.is_empty() {
                return Some(norm);
            }
        }
    }
    None
}

fn resolve_script_fallback(parts: &[&str]) -> Option<String> {
    let mut i = 1;
    while i < parts.len() {
        let arg = parts[i];
        if arg == "-m" && i + 1 < parts.len() {
            return Some(normalize_exe(parts[i + 1]));
        }
        if arg == "-c" && i + 1 < parts.len() {
            return Some(normalize_exe(parts[i + 1]));
        }
        if !arg.starts_with('-') {
            return Some(normalize_exe(arg));
        }
        i += 1;
    }
    None
}

fn strip_version_suffix(exe: &str) -> String {
    regex::Regex::new(r"[-_.]\d+(\.\d+)*$")
        .unwrap()
        .replace(exe, "")
        .into_owned()
}

fn match_app(
    effective: &str,
    cmdline: &str,
    app_patterns: &[AppPattern],
    exe_to_app: &HashMap<String, String>,
    desktop_excluded: &HashSet<String>,
) -> Option<(String, Option<AppPattern>)> {
    let effective_lower = effective.to_lowercase();
    let effective_base = strip_version_suffix(&effective_lower);
    let cmdline_lower = cmdline.to_lowercase();
    for pattern in app_patterns {
        let exe = pattern.exe.to_lowercase();
        if effective_lower != exe && effective_base != exe {
            continue;
        }
        if !pattern.cmdline.is_empty() && !cmdline_lower.contains(&pattern.cmdline.to_lowercase()) {
            continue;
        }
        return Some((pattern.name.clone(), Some(pattern.clone())));
    }
    if !desktop_excluded.contains(&effective_lower) {
        let key = if exe_to_app.contains_key(&effective_lower) {
            &effective_lower
        } else {
            &effective_base
        };
        if let Some(name) = exe_to_app.get(key) {
            return Some((name.clone(), None));
        }
    }
    None
}

/// Match a process against tool patterns. Patterns with a cmdline filter
/// (case-insensitive substring) take precedence over exe-only patterns.
/// Returns (name, category, build).
fn match_tool(effective: &str, cmdline: &str, tool_patterns: &[ToolPattern]) -> Option<(String, String, bool)> {
    let effective_lower = effective.to_lowercase();
    let cmdline_lower = cmdline.to_lowercase();
    let mut fallback: Option<(String, String, bool)> = None;
    for pattern in tool_patterns {
        if effective_lower != pattern.exe {
            continue;
        }
        let result = (pattern.name.clone(), pattern.category.clone(), pattern.build);
        if !pattern.cmdline.is_empty() {
            if cmdline_lower.contains(&pattern.cmdline.to_lowercase()) {
                return Some(result);
            }
        } else if fallback.is_none() {
            fallback = Some(result);
        }
    }
    fallback
}

fn match_system_category(
    proc: &ProcessInfo,
    effective: &str,
    categories: &[SystemCategory],
    overrides: &HashMap<String, String>,
) -> Option<String> {
    let effective_lower = effective.to_lowercase();
    let proc_exe = normalize_exe(if proc.exe.is_empty() { &proc.name } else { &proc.exe });
    let proc_exe = if proc_exe.is_empty() { &effective_lower } else { &proc_exe };
    if let Some(o) = overrides.get(&effective_lower).or_else(|| overrides.get(proc_exe)) {
        if o.is_empty() {
            return None;
        }
        return Some(o.clone());
    }
    for cat in categories {
        if cat.exe.iter().any(|e| e == &effective_lower) {
            return Some(cat.name.clone());
        }
        if cat.exe_prefix.iter().any(|p| effective_lower.starts_with(p)) {
            return Some(cat.name.clone());
        }
    }
    None
}

fn is_electron_child(proc: &ProcessInfo, parent_exe: &str) -> bool {
    let cmdline = proc.cmdline.to_lowercase();
    let exe = proc.exe.to_lowercase();
    if cmdline.is_empty() && exe.is_empty() {
        return false;
    }
    let markers = [
        "--type=renderer",
        "--type=gpu-process",
        "--type=utility",
        "--type=zygote",
        "--crashpad-handler",
    ];
    let has_marker = markers.iter().any(|m| cmdline.contains(m));
    if !has_marker {
        return false;
    }
    cmdline.contains(parent_exe) || exe.contains(parent_exe)
}

fn is_gecko_child(proc: &ProcessInfo, parent_exe: &str) -> bool {
    let cmdline = proc.cmdline.to_lowercase();
    let exe = proc.exe.to_lowercase();
    cmdline.contains("-contentproc") && exe.contains(parent_exe)
}

fn get_tree_root(
    pid: u32,
    ppid_map: &HashMap<u32, u32>,
    name_map: &HashMap<u32, String>,
    generic_parents: &HashSet<String>,
) -> u32 {
    let mut current = pid;
    loop {
        let name = name_map.get(&current).map(|s| s.as_str()).unwrap_or("").to_lowercase();
        let ppid = match ppid_map.get(&current) {
            Some(&p) => p,
            None => return current,
        };
        if ppid == 0 || ppid == current || !ppid_map.contains_key(&ppid) {
            return current;
        }
        let parent_name = name_map.get(&ppid).map(|s| s.as_str()).unwrap_or("").to_lowercase();
        if generic_parents.contains(&name) {
            current = ppid;
        } else if generic_parents.contains(&parent_name) {
            return current;
        } else if parent_name == name {
            current = ppid;
        } else {
            return current;
        }
    }
}

/// Group processes by four-layer algorithm
pub fn group_processes(
    processes: &[ProcessInfo],
    ram_total_bytes: u64,
    config: &GroupingConfig,
    exe_to_app: &HashMap<String, String>,
) -> Vec<ProcessGroup> {
    let rules = load_grouping_rules();
    let generic_set: HashSet<String> = rules.generic_parents.iter().cloned().collect();
    let transparent_runtimes: HashSet<String> = rules.transparent_runtimes.iter().cloned().collect();
    let app_patterns = &rules.apps;
    let tool_patterns = &rules.tools;
    let system_categories = &rules.system_categories;
    let category_overrides = &rules.category_overrides;
    let launchers_by_exe = &rules.launchers_by_exe;

    let pid_to_proc: HashMap<u32, ProcessInfo> = processes.iter().cloned().map(|p| (p.pid, p)).collect();
    let ppid_map: HashMap<u32, u32> = processes.iter().map(|p| (p.pid, p.ppid)).collect();
    let name_map: HashMap<u32, String> = processes
        .iter()
        .map(|p| (p.pid, (if p.exe.is_empty() { &p.name } else { &p.exe }).to_lowercase()))
        .collect();
    let effective_exe_map: HashMap<u32, String> = processes
        .iter()
        .map(|p| (p.pid, effective_exe(p, &transparent_runtimes, launchers_by_exe)))
        .collect();

    let system_exes: HashSet<String> = system_categories
        .iter()
        .flat_map(|c| c.exe.iter().cloned())
        .collect();
    let desktop_excluded: HashSet<String> = system_exes.union(&generic_set).cloned().collect();

    let current_uid = {
        #[cfg(unix)]
        { nix::unistd::getuid().as_raw() }
        #[cfg(not(unix))]
        { 0u32 }
    };

    type Assignment = (String, String); // layer, key
    let mut pid_to_assignment: HashMap<u32, Assignment> = HashMap::new();
    let mut no_tool_reclaim_pids: HashSet<u32> = HashSet::new();
    let mut pid_tool_is_build: HashMap<u32, bool> = HashMap::new();

    let terminal_exes: HashSet<String> = [
        "wezterm-gui", "alacritty", "kitty", "gnome-terminal",
        "konsole", "xterm", "iterm2", "terminal", "wezterm",
    ].iter().map(|s| s.to_string()).collect();

    for proc in processes {
        let pid = proc.pid;
        if pid_to_assignment.contains_key(&pid) {
            continue;
        }
        let exe = effective_exe_map.get(&pid).map(|s| s.as_str()).unwrap_or("");
        let cmdline = &proc.cmdline;
        let uid = proc.uid;

        if generic_set.contains(exe) {
            continue;
        }

        // Layer 1: App (only when cmdline present)
        if !cmdline.is_empty() {
        if let Some((app_name, pattern)) = match_app(exe, cmdline, app_patterns, exe_to_app, &desktop_excluded) {
            let mut assign = true;
            if let Some(ref p) = pattern {
                let family = p.family.to_lowercase();
                if family == "electron" || family == "chromium" {
                    assign = is_electron_child(proc, &p.exe.to_lowercase())
                        || effective_exe_map.get(&pid).map(|s| s.as_str()) == Some(&p.exe.to_lowercase());
                } else if family == "gecko" {
                    assign = is_gecko_child(proc, &p.exe.to_lowercase())
                        || exe == p.exe.to_lowercase();
                }
                if assign && p.no_tool_reclaim {
                    no_tool_reclaim_pids.insert(pid);
                }
            }
            if assign {
                pid_to_assignment.insert(pid, ("app".into(), format!("{}:{}", app_name, uid)));
                continue;
            }
        }
        let root = get_tree_root(pid, &ppid_map, &name_map, &generic_set);
        if let Some(root_proc) = pid_to_proc.get(&root) {
            let root_exe = effective_exe_map.get(&root).map(|s| s.as_str()).unwrap_or("");
            if let Some((app_name, pattern)) = match_app(
                root_exe,
                &root_proc.cmdline,
                app_patterns,
                exe_to_app,
                &desktop_excluded,
            ) {
                if !terminal_exes.contains(&app_name.to_lowercase()) {
                    if let Some(ref p) = pattern {
                        if p.no_tool_reclaim {
                            no_tool_reclaim_pids.insert(pid);
                        }
                    }
                    pid_to_assignment.insert(pid, ("app".into(), format!("{}:{}", app_name, uid)));
                    continue;
                }
            }
        }

        // Layer 2: Tool (skip no_tool_reclaim)
        if !no_tool_reclaim_pids.contains(&pid) {
            if let Some((tool_name, _, tool_is_build)) = match_tool(exe, cmdline, tool_patterns) {
                pid_tool_is_build.insert(pid, tool_is_build);
                pid_to_assignment.insert(pid, ("tool".into(), format!("{}:{}", tool_name, uid)));
                continue;
            }
        }
        }

        // Layer 3: System
        if !pid_to_assignment.contains_key(&pid) {
            if cmdline.is_empty() {
                pid_to_assignment.insert(pid, ("system".into(), "Kernel".into()));
            } else if let Some(cat) = match_system_category(proc, exe, system_categories, category_overrides) {
                let uid_key = if proc.uid == current_uid { proc.uid } else { u32::MAX };
                pid_to_assignment.insert(pid, ("system".into(), format!("{}:{}", cat, uid_key)));
            }
        }

        // Layer 4: Catch-all
        if !pid_to_assignment.contains_key(&pid) {
            let exe_fall = if exe.is_empty() {
                name_map.get(&pid).map(|s| s.as_str()).unwrap_or("")
            } else {
                exe
            };
            let key = if exe_fall.is_empty() {
                format!("pid:{}", pid)
            } else {
                format!("exe:{}:{}", exe_fall, uid)
            };
            pid_to_assignment.insert(pid, ("other".into(), key));
        }
    }

    // Build key -> pids
    let mut key_to_pids: HashMap<String, Vec<u32>> = HashMap::new();
    for (pid, (layer, key)) in &pid_to_assignment {
        let full_key = format!("{}:{}", layer, key);
        key_to_pids.entry(full_key).or_default().push(*pid);
    }

    // Build ProcessGroup list
    let mut result = Vec::new();
    for (full_key, pids) in key_to_pids {
        let procs: Vec<ProcessInfo> = pids
            .iter()
            .filter_map(|pid| pid_to_proc.get(pid))
            .cloned()
            .collect();
        if procs.is_empty() {
            continue;
        }
        let layer = full_key.split(':').next().unwrap_or("");
        let rest = full_key.splitn(2, ':').nth(1).unwrap_or("");
        let cpu_pct = procs.iter().map(|p| p.cpu_pct).sum();
        let mem_bytes = procs.iter().map(|p| p.rss_bytes).sum();
        let mem_pct = if ram_total_bytes > 0 {
            100.0 * mem_bytes as f32 / ram_total_bytes as f32
        } else {
            0.0
        };
        let user = procs.first().map(|p| uid_to_user(p.uid)).unwrap_or_default();

        let name = match layer {
            "system" if rest == "Kernel" => "Kernel".to_string(),
            "system" => rest.splitn(2, ':').next().unwrap_or(rest).to_string(),
            "app" => rest.splitn(2, ':').next().unwrap_or(rest).to_string(),
            "tool" => {
                let n = rest.splitn(2, ':').next().unwrap_or(rest);
                // Tool rules with build = false (servers) keep their plain name.
                let is_build = procs.iter().any(|p| *pid_tool_is_build.get(&p.pid).unwrap_or(&true));
                if procs.len() > 1 && is_build {
                    format!("{} build ({} procs)", n, procs.len())
                } else {
                    n.to_string()
                }
            }
            _ => {
                if rest.starts_with("exe:") {
                    let after_exe = &rest[4..];
                    after_exe.rsplitn(2, ':').nth(1).unwrap_or(after_exe).to_string()
                } else {
                    rest.to_string()
                }
            }
        };

        let name = if name.is_empty() || name.trim().is_empty() {
            "[other]".to_string()
        } else if name.to_lowercase() == "systemd" {
            "Session / Desktop".to_string()
        } else {
            name
        };

        result.push(ProcessGroup {
            name,
            proc_count: procs.len(),
            cpu_pct,
            mem_bytes,
            mem_pct,
            user,
            category: layer.to_string(),
            children: vec![],
            processes: procs,
            expanded: false,
            depth: 0,
            group_key: full_key,
        });
    }

    result = post_process_groups(result, config.other_cpu_max, config.other_mem_max);
    result = build_hierarchy(result, ram_total_bytes, config, &rules);
    result
}

fn electron_type_name(cmdline: &str) -> String {
    let cl = cmdline.to_lowercase();
    if cl.contains("--type=renderer") {
        return "Web Content".into();
    }
    if cl.contains("--type=gpu-process") {
        return "GPU Process".into();
    }
    if cl.contains("--type=utility") {
        return "Utility".into();
    }
    if cl.contains("--type=zygote") {
        return "Zygote".into();
    }
    if cl.contains("--crashpad-handler") {
        return "Crashpad".into();
    }
    "Main Process".into()
}

const GECKO_COMM_FIXUP: &[(&str, &str)] = &[
    ("Isolated Web Co", "Isolated Web Content"),
    ("Isolated Servic", "Isolated Service"),
    ("Privileged Cont", "Privileged Content"),
    ("Utility Process", "Utility Process"),
];

fn gecko_type_name(name: &str, cmdline: &str) -> String {
    let name = name.trim();
    if !name.is_empty() {
        for (k, v) in GECKO_COMM_FIXUP {
            if name == *k {
                return v.to_string();
            }
        }
        return name.to_string();
    }
    if cmdline.contains("-contentproc") {
        return "Web Content".into();
    }
    "Other".into()
}

fn build_tree_subgroups<F>(
    procs: &[ProcessInfo],
    key_fn: &F,
    parent_group_key: &str,
    user: &str,
    category: &str,
    ram_total_bytes: u64,
    skip_keys: &HashSet<String>,
    skip_root_keys: Option<&HashSet<String>>,
) -> Vec<ProcessGroup>
where
    F: Fn(&ProcessInfo) -> String,
{
    if procs.is_empty() {
        return vec![];
    }
    let pid_set: HashSet<u32> = procs.iter().map(|p| p.pid).collect();
    let mut children_of: HashMap<u32, Vec<ProcessInfo>> = HashMap::new();
    let mut roots: Vec<ProcessInfo> = Vec::new();
    for p in procs {
        if pid_set.contains(&p.ppid) && p.ppid != p.pid {
            children_of.entry(p.ppid).or_default().push(p.clone());
        } else {
            roots.push(p.clone());
        }
    }

    fn expand_transparent<F>(
        proc_list: &[ProcessInfo],
        children_of: &HashMap<u32, Vec<ProcessInfo>>,
        key_fn: &F,
        skip_keys: &HashSet<String>,
        also_skip: &HashSet<String>,
    ) -> Vec<ProcessInfo>
    where
        F: Fn(&ProcessInfo) -> String,
    {
        let mut result = Vec::new();
        for p in proc_list {
            if skip_keys.contains(&key_fn(p)) || also_skip.contains(&key_fn(p)) {
                if let Some(children) = children_of.get(&p.pid) {
                    result.extend(expand_transparent(children, children_of, key_fn, skip_keys, also_skip));
                }
            } else {
                result.push(p.clone());
            }
        }
        result
    }

    fn collect<F>(
        proc_list: Vec<ProcessInfo>,
        children_of: &HashMap<u32, Vec<ProcessInfo>>,
        key_fn: &F,
        parent_key: &str,
        user: &str,
        category: &str,
        ram_total_bytes: u64,
        skip_keys: &HashSet<String>,
        skip_root_keys: Option<&HashSet<String>>,
        is_root: bool,
    ) -> Vec<ProcessGroup>
    where
        F: Fn(&ProcessInfo) -> String,
    {
        if proc_list.is_empty() {
            return vec![];
        }
        let extra: HashSet<String> = if is_root {
            skip_root_keys.map(|s| s.iter().cloned().collect()).unwrap_or_default()
        } else {
            HashSet::new()
        };
        let proc_list = expand_transparent(&proc_list, children_of, key_fn, skip_keys, &extra);
        if proc_list.is_empty() {
            return vec![];
        }

        // Group siblings by key: (own_procs, child_pool)
        let mut by_key: HashMap<String, (Vec<ProcessInfo>, Vec<ProcessInfo>)> = HashMap::new();
        let mut order: Vec<String> = Vec::new();
        for p in &proc_list {
            let key = key_fn(p);
            let entry = by_key.entry(key.clone()).or_insert_with(|| {
                order.push(key.clone());
                (Vec::new(), Vec::new())
            });
            entry.0.push(p.clone());
            if let Some(children) = children_of.get(&p.pid) {
                entry.1.extend(children.clone());
            }
        }

        let mut result = Vec::new();
        for key in order {
            let (mut own_procs, child_pool) = by_key.remove(&key).unwrap_or_default();

            // Chain-collapse: absorb same-key children
            let mut same: Vec<ProcessInfo> = child_pool.iter().filter(|c| key_fn(c) == key).cloned().collect();
            let mut diff: Vec<ProcessInfo> = child_pool.into_iter().filter(|c| key_fn(c) != key).collect();
            while !same.is_empty() {
                let next_same: Vec<ProcessInfo> = same
                    .iter()
                    .flat_map(|c| children_of.get(&c.pid).cloned().unwrap_or_default().into_iter())
                    .filter(|g| key_fn(g) == key)
                    .collect();
                let next_diff: Vec<ProcessInfo> = same
                    .iter()
                    .flat_map(|c| children_of.get(&c.pid).cloned().unwrap_or_default().into_iter())
                    .filter(|g| key_fn(g) != key)
                    .collect();
                own_procs.extend(same);
                same = next_same;
                diff.extend(next_diff);
            }

            let node_key = format!("{}|sub:{}", parent_key, key.trim().to_lowercase());
            let sub_children = collect(
                diff,
                children_of,
                key_fn,
                &node_key,
                user,
                category,
                ram_total_bytes,
                skip_keys,
                skip_root_keys,
                false,
            );

            let cpu_pct = own_procs.iter().map(|p| p.cpu_pct).sum();
            let mem_bytes: u64 = own_procs.iter().map(|p| p.rss_bytes).sum();
            let mem_pct = if ram_total_bytes > 0 {
                100.0 * mem_bytes as f32 / ram_total_bytes as f32
            } else {
                0.0
            };
            let name = if own_procs.len() > 1 {
                format!("{} ({})", key, own_procs.len())
            } else {
                key.clone()
            };

            result.push(ProcessGroup {
                name,
                proc_count: own_procs.len(),
                cpu_pct,
                mem_bytes,
                mem_pct,
                user: user.to_string(),
                category: category.to_string(),
                children: sub_children,
                processes: own_procs,
                expanded: false,
                depth: 0,
                group_key: node_key,
            });
        }
        result
    }

    collect(
        roots,
        &children_of,
        key_fn,
        parent_group_key,
        user,
        category,
        ram_total_bytes,
        skip_keys,
        skip_root_keys,
        true,
    )
}

fn build_hierarchy(
    groups: Vec<ProcessGroup>,
    ram_total_bytes: u64,
    config: &GroupingConfig,
    rules: &crate::grouping::rules_loader::CompiledRules,
) -> Vec<ProcessGroup> {
    let transparent_runtimes: HashSet<String> = rules.transparent_runtimes.iter().cloned().collect();
    let generic_set: HashSet<String> = rules.generic_parents.iter().cloned().collect();
    let skip_keys: HashSet<String> = generic_set
        .union(&transparent_runtimes)
        .cloned()
        .collect();

    let default_expanded: HashSet<String> = config
        .default_expanded
        .iter()
        .map(|s| s.to_lowercase())
        .collect();
    let expand_threshold = config.expand_threshold;

    let mut result = Vec::new();
    for g in groups {
        let procs = &g.processes;
        let mut children: Vec<ProcessGroup> = Vec::new();

        if g.category == "app" && procs.len() > 1 {
            let exe_lower = procs.first().map(|p| p.exe.to_lowercase()).unwrap_or_default();
            let app_exe = procs.first().map(|p| normalize_exe(&p.exe)).unwrap_or_default();
            let is_gecko = ["firefox", "thunderbird", "librewolf"].iter().any(|x| exe_lower.contains(*x));
            let is_agent = rules.apps.iter().any(|p| p.family.to_lowercase() == "agent" && p.name.to_lowercase() == g.name.to_lowercase());

            if is_gecko {
                let gecko_root_skip: HashSet<String> = if app_exe.is_empty() {
                    HashSet::new()
                } else {
                    [app_exe.clone()].iter().cloned().collect()
                };
                children = build_tree_subgroups(
                    procs,
                    &|p| gecko_type_name(&p.name, &p.cmdline),
                    &g.group_key,
                    &g.user,
                    "app",
                    ram_total_bytes,
                    &skip_keys,
                    Some(&gecko_root_skip),
                );
            } else if is_agent {
                let tr = transparent_runtimes.clone();
                let lr = rules.launchers_by_exe.clone();
                children = build_tree_subgroups(
                    procs,
                    &|p| {
                        let e = effective_exe(p, &tr, &lr);
                        if e.is_empty() { normalize_exe(if p.exe.is_empty() { &p.name } else { &p.exe }) } else { e }
                    },
                    &g.group_key,
                    &g.user,
                    "app",
                    ram_total_bytes,
                    &skip_keys,
                    None,
                );
            } else {
                let app_exe_clone = app_exe.clone();
                let tr = transparent_runtimes.clone();
                let lr = rules.launchers_by_exe.clone();
                let main_process_skip: HashSet<String> = ["Main Process".into()].iter().cloned().collect();
                children = build_tree_subgroups(
                    procs,
                    &|p| {
                        let t = electron_type_name(&p.cmdline);
                        if t != "Main Process" {
                            return t;
                        }
                        let exe = effective_exe(p, &tr, &lr);
                        let exe = if exe.is_empty() { normalize_exe(if p.exe.is_empty() { &p.name } else { &p.exe }) } else { exe };
                        if exe == app_exe_clone { "Main Process".to_string() } else { exe }
                    },
                    &g.group_key,
                    &g.user,
                    "app",
                    ram_total_bytes,
                    &skip_keys,
                    Some(&main_process_skip),
                );
            }
        } else if g.category == "tool" && procs.len() > 1 {
            let tr = transparent_runtimes.clone();
            let lr = rules.launchers_by_exe.clone();
            children = build_tree_subgroups(
                procs,
                &|p| {
                    let e = effective_exe(p, &tr, &lr);
                    if e.is_empty() { normalize_exe(if p.exe.is_empty() { &p.name } else { &p.exe }) } else { e }
                },
                &g.group_key,
                &g.user,
                "tool",
                ram_total_bytes,
                &skip_keys,
                None,
            );
        } else if g.category == "system" && procs.len() > 1 && g.name != "Kernel" {
            let tr = transparent_runtimes.clone();
            let lr = rules.launchers_by_exe.clone();
            children = build_tree_subgroups(
                procs,
                &|p| {
                    let e = effective_exe(p, &tr, &lr);
                    if e.is_empty() { normalize_exe(if p.exe.is_empty() { &p.name } else { &p.exe }) } else { e }
                },
                &g.group_key,
                &g.user,
                "system",
                ram_total_bytes,
                &skip_keys,
                None,
            );
        }

        let expanded = default_expanded.contains(&g.name.to_lowercase())
            || (expand_threshold > 0 && g.proc_count as u32 <= expand_threshold);

        result.push(ProcessGroup {
            expanded,
            children,
            ..g
        });
    }
    result
}

fn post_process_groups(
    mut groups: Vec<ProcessGroup>,
    other_cpu_max: f64,
    other_mem_max: u64,
) -> Vec<ProcessGroup> {
    // Dedup by (name.lower(), user) - merge groups with same display key (Python _post_process_groups)
    let mut by_key: HashMap<(String, String), ProcessGroup> = HashMap::new();
    for g in groups {
        let key = (g.name.to_lowercase(), g.user.clone());
        let dedup_key = format!("{}:{}:{}", g.category.to_lowercase(), g.name.to_lowercase(), g.user);
        if let Some(existing) = by_key.get_mut(&key) {
            let (old_children, old_procs) = (existing.children.clone(), existing.processes.clone());
            let (new_children, new_procs) = (g.children.clone(), g.processes.clone());
            *existing = ProcessGroup {
                proc_count: old_procs.len() + new_procs.len(),
                cpu_pct: existing.cpu_pct + g.cpu_pct,
                mem_bytes: existing.mem_bytes + g.mem_bytes,
                mem_pct: existing.mem_pct + g.mem_pct,
                processes: {
                    let mut v = old_procs;
                    v.extend(new_procs);
                    v
                },
                children: if old_children.is_empty() { new_children } else { old_children },
                group_key: dedup_key,
                ..existing.clone()
            };
        } else {
            let mut g = g;
            g.group_key = dedup_key;
            by_key.insert(key, g);
        }
    }
    groups = by_key.into_values().collect();

    let preserved: HashSet<String> = ["kernel", "session / desktop"].iter().map(|s| s.to_string()).collect();
    let mut kept = Vec::new();
    let mut other = Vec::new();
    for g in groups {
        if preserved.contains(&g.name.to_lowercase()) {
            kept.push(g);
        } else if ["app", "tool", "system"].contains(&&g.category[..]) {
            kept.push(g);
        } else if (g.cpu_pct as f64) < other_cpu_max && g.mem_bytes < other_mem_max {
            other.push(g);
        } else {
            kept.push(g);
        }
    }
    if !other.is_empty() {
        let n = other.iter().map(|g| g.proc_count).sum();
        let all_procs: Vec<ProcessInfo> = other.iter().flat_map(|g| g.processes.clone()).collect();
        kept.push(ProcessGroup {
            name: format!("other ({})", n),
            proc_count: n,
            cpu_pct: other.iter().map(|g| g.cpu_pct).sum(),
            mem_bytes: other.iter().map(|g| g.mem_bytes).sum(),
            mem_pct: other.iter().map(|g| g.mem_pct).sum(),
            user: String::new(),
            category: "other".into(),
            children: other,
            processes: all_procs,
            expanded: false,
            depth: 0,
            group_key: "other:bucket".into(),
        });
    }
    kept
}

/// Label for a single process (effective exe)
pub fn proc_label(proc: &ProcessInfo) -> String {
    let rules = load_grouping_rules();
    let transparent: HashSet<String> = rules.transparent_runtimes.iter().cloned().collect();
    let exe = effective_exe(proc, &transparent, &rules.launchers_by_exe);
    let raw = normalize_exe(if proc.exe.is_empty() { &proc.name } else { &proc.exe });
    let label = if exe.is_empty() { raw.clone() } else { exe };
    if label == raw {
        if let Some(m) = regex::Regex::new(r"--type=(\S+)").unwrap().captures(&proc.cmdline) {
            return format!("{} [{}]", label, m.get(1).map(|x| x.as_str()).unwrap_or(""));
        }
    }
    label
}
