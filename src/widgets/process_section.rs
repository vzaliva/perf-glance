//! Process list section widget

use crate::collectors::ProcessInfo;
use crate::config::{self, ThemeConfig};
use crate::grouping::{proc_label, ProcessGroup};
use crate::utils;
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use std::collections::{HashMap, HashSet};
use std::fs;

/// Extract PID from per-PID leaf group_key (e.g. "exe:foo:1000|pid:12345:0")
fn pid_from_group_key(group_key: &str) -> Option<u32> {
    group_key
        .split("|pid:")
        .nth(1)
        .and_then(|s| s.split(':').next())
        .and_then(|s| s.parse().ok())
}

const SORT_CYCLE: &[&str] = &["cpu", "cum", "mem", "count"];

fn parse_color(s: &str) -> Color {
    if s.starts_with('#') && s.len() >= 7 {
        if let (Ok(r), Ok(g), Ok(b)) = (
            u8::from_str_radix(&s[1..3], 16),
            u8::from_str_radix(&s[3..5], 16),
            u8::from_str_radix(&s[5..7], 16),
        ) {
            return Color::Rgb(r, g, b);
        }
    }
    Color::White
}

fn flatten_groups<'a>(groups: &'a [ProcessGroup], text_filter: &str) -> Vec<(&'a ProcessGroup, usize)> {
    let filter_lower = text_filter.to_lowercase().trim().to_string();
    let mut result = Vec::new();
    fn walk<'a>(
        gs: &'a [ProcessGroup],
        depth: usize,
        out: &mut Vec<(&'a ProcessGroup, usize)>,
        filter: &str,
    ) {
        for g in gs {
            if filter.is_empty()
                || g.name.to_lowercase().contains(filter)
                || g.user.to_lowercase().contains(filter)
            {
                out.push((g, depth));
            }
            if g.expanded {
                walk(&g.children, depth + 1, out, filter);
            }
        }
    }
    walk(groups, 0, &mut result, &filter_lower);
    result
}

pub struct ProcessSection {
    pub sort_by: String,
    pub cursor_index: usize,
    pub scroll_offset: usize,
    pub flat_rows: Vec<(ProcessGroup, usize)>,
    pub groups: Vec<ProcessGroup>,
    pub user_filter: Option<String>,
    pub text_filter: String,
    pub cum_share_by_key: HashMap<String, f32>,
    pub expanded_state: HashSet<(String, String)>,
}

fn load_expanded_state() -> HashSet<(String, String)> {
    let path = config::config_dir().join("state.json");
    if !path.exists() {
        return HashSet::new();
    }
    if let Ok(data) = fs::read_to_string(&path) {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(&data) {
            if let Some(arr) = json.get("expanded").and_then(|v| v.as_array()) {
                return arr
                    .iter()
                    .filter_map(|v| {
                        let a = v.as_array()?;
                        if a.len() == 2 {
                            let n = a[0].as_str()?.to_lowercase();
                            let u = a[1].as_str().unwrap_or("").to_string();
                            Some((n, u))
                        } else {
                            None
                        }
                    })
                    .collect();
            }
        }
    }
    HashSet::new()
}

fn persist_expanded_state(expanded: &HashSet<(String, String)>) {
    let path = config::config_dir().join("state.json");
    if let Err(_) = fs::create_dir_all(path.parent().unwrap_or(std::path::Path::new("."))) {
        return;
    }
    let arr: Vec<Vec<String>> = expanded
        .iter()
        .map(|(n, u)| vec![n.clone(), u.clone()])
        .collect();
    let json = serde_json::json!({ "expanded": arr });
    let _ = fs::write(path, serde_json::to_string_pretty(&json).unwrap_or_default());
}

impl Default for ProcessSection {
    fn default() -> Self {
        Self {
            sort_by: "cpu".into(),
            cursor_index: 0,
            scroll_offset: 0,
            flat_rows: Vec::new(),
            groups: Vec::new(),
            user_filter: None,
            text_filter: String::new(),
            cum_share_by_key: HashMap::new(),
            expanded_state: load_expanded_state(),
        }
    }
}

impl ProcessSection {
    pub fn cycle_sort(&mut self) -> &str {
        let idx = SORT_CYCLE.iter().position(|s| *s == self.sort_by).unwrap_or(0);
        self.sort_by = SORT_CYCLE[(idx + 1) % SORT_CYCLE.len()].to_string();
        &self.sort_by
    }

    pub fn toggle_user_filter(&mut self, current_user: &str) -> bool {
        match &self.user_filter {
            None => {
                self.user_filter = Some(current_user.to_string());
                true
            }
            Some(_) => {
                self.user_filter = None;
                false
            }
        }
    }

    pub fn set_text_filter(&mut self, s: &str) {
        self.text_filter = s.to_string();
    }

    pub fn clear_text_filter(&mut self) {
        self.text_filter.clear();
    }

    /// PIDs for selected row. kill_group=false: one PID only; kill_group=true: all in group tree.
    pub fn selected_pids(&self, kill_group: bool) -> Vec<u32> {
        if self.flat_rows.is_empty() || self.cursor_index >= self.flat_rows.len() {
            return vec![];
        }
        let (g, _) = &self.flat_rows[self.cursor_index];
        let mut pids = Vec::new();
        if kill_group {
            fn collect_recursive(node: &ProcessGroup, out: &mut Vec<u32>) {
                for p in &node.processes {
                    out.push(p.pid);
                }
                if let Some(pid) = pid_from_group_key(&node.group_key) {
                    out.push(pid);
                }
                for child in &node.children {
                    collect_recursive(child, out);
                }
            }
            collect_recursive(g, &mut pids);
        } else {
            if g.processes.len() == 1 {
                pids.push(g.processes[0].pid);
            } else if g.processes.is_empty() {
                if let Some(pid) = pid_from_group_key(&g.group_key) {
                    pids.push(pid);
                }
            }
        }
        // Dedupe preserving order
        let mut seen = HashSet::new();
        pids.retain(|p| seen.insert(*p));
        pids
    }

    /// Selected process for popup. Returns Some only when exactly one PID in selection.
    pub fn selected_individual_process(&self) -> Option<ProcessInfo> {
        let pids = self.selected_pids(true);
        if pids.len() != 1 {
            return None;
        }
        let target_pid = pids[0];
        fn find_proc(node: &ProcessGroup, target: u32) -> Option<ProcessInfo> {
            for p in &node.processes {
                if p.pid == target {
                    return Some(p.clone());
                }
            }
            for child in &node.children {
                if let Some(proc) = find_proc(child, target) {
                    return Some(proc);
                }
            }
            None
        }
        let (g, _) = &self.flat_rows[self.cursor_index];
        find_proc(g, target_pid)
    }

    pub fn do_scroll_up(&mut self) {
        self.cursor_index = self.cursor_index.saturating_sub(1);
    }

    pub fn do_scroll_down(&mut self) {
        if !self.flat_rows.is_empty() {
            self.cursor_index = (self.cursor_index + 1).min(self.flat_rows.len() - 1);
        }
    }

    fn scroll_to_cursor(&mut self, visible_rows: usize) {
        if self.cursor_index < self.scroll_offset {
            self.scroll_offset = self.cursor_index;
        } else if self.cursor_index >= self.scroll_offset + visible_rows {
            self.scroll_offset = self.cursor_index - visible_rows + 1;
        }
    }

    pub fn do_expand(&mut self) -> bool {
        if self.flat_rows.is_empty() || self.cursor_index >= self.flat_rows.len() {
            return false;
        }
        let (g, depth) = &self.flat_rows[self.cursor_index];
        if g.expanded {
            return false;
        }
        // If no children but multiple processes, create per-PID leaves
        let key = (g.name.to_lowercase(), g.user.clone());
        Self::ensure_children_for_group(&mut self.groups, &key, *depth);
        self.expanded_state.insert(key.clone());
        persist_expanded_state(&self.expanded_state);
        Self::set_expanded_in_groups(&mut self.groups, &key, true);
        self.flat_rows = flatten_groups(&self.groups, &self.text_filter)
            .into_iter()
            .map(|(grp, d)| (grp.clone(), d))
            .collect();
        true
    }

    fn ensure_children_for_group(
        groups: &mut [ProcessGroup],
        key: &(String, String),
        depth: usize,
    ) {
        for g in groups.iter_mut() {
            if (g.name.to_lowercase(), g.user.clone()) == *key {
                if g.children.is_empty() && g.processes.len() > 1 {
                    for p in &g.processes {
                        let label = proc_label(p);
                        let child_name = if label.is_empty() {
                            format!("PID {}", p.pid)
                        } else {
                            format!("PID {}  {}", p.pid, label)
                        };
                        g.children.push(ProcessGroup {
                            name: child_name,
                            proc_count: 1,
                            cpu_pct: p.cpu_pct,
                            mem_bytes: p.rss_bytes,
                            mem_pct: 0.0,
                            user: g.user.clone(),
                            category: g.category.clone(),
                            children: vec![],
                            processes: vec![p.clone()],
                            expanded: false,
                            depth: (depth + 1) as u32,
                            group_key: format!("{}|pid:{}:{}", g.group_key, p.pid, p.starttime_ticks),
                        });
                    }
                }
                return;
            }
            Self::ensure_children_for_group(&mut g.children, key, depth + 1);
        }
    }

    pub fn do_collapse(&mut self) -> bool {
        if self.flat_rows.is_empty() || self.cursor_index >= self.flat_rows.len() {
            return false;
        }
        let (g, _) = &self.flat_rows[self.cursor_index];
        if !g.expanded {
            return false;
        }
        let key = (g.name.to_lowercase(), g.user.clone());
        self.expanded_state.remove(&key);
        persist_expanded_state(&self.expanded_state);
        Self::set_expanded_in_groups(&mut self.groups, &key, false);
        self.flat_rows = flatten_groups(&self.groups, &self.text_filter)
            .into_iter()
            .map(|(grp, d)| (grp.clone(), d))
            .collect();
        true
    }

    fn set_expanded_in_groups(
        groups: &mut [ProcessGroup],
        key: &(String, String),
        expanded: bool,
    ) {
        for g in groups.iter_mut() {
            if (g.name.to_lowercase(), g.user.clone()) == *key {
                g.expanded = expanded;
            }
            Self::set_expanded_in_groups(&mut g.children, key, expanded);
        }
    }

    pub fn reset_cumulative(&mut self) {
        self.cum_share_by_key.clear();
    }

    fn apply_expanded_state(&mut self, groups: &mut [ProcessGroup]) {
        fn walk(groups: &mut [ProcessGroup], expanded: &HashSet<(String, String)>, depth: usize) {
            for g in groups.iter_mut() {
                let key = (g.name.to_lowercase(), g.user.clone());
                if expanded.contains(&key) {
                    g.expanded = true;
                    if g.children.is_empty() && g.processes.len() > 1 {
                        for p in &g.processes.clone() {
                            let label = proc_label(p);
                            let child_name = if label.is_empty() {
                                format!("PID {}", p.pid)
                            } else {
                                format!("PID {}  {}", p.pid, label)
                            };
                            g.children.push(ProcessGroup {
                                name: child_name,
                                proc_count: 1,
                                cpu_pct: p.cpu_pct,
                                mem_bytes: p.rss_bytes,
                                mem_pct: 0.0,
                                user: g.user.clone(),
                                category: g.category.clone(),
                                children: vec![],
                                processes: vec![p.clone()],
                                expanded: false,
                                depth: (depth + 1) as u32,
                                group_key: format!("{}|pid:{}:{}", g.group_key, p.pid, p.starttime_ticks),
                            });
                        }
                    }
                }
                walk(&mut g.children, expanded, depth + 1);
            }
        }
        walk(groups, &self.expanded_state, 0);
    }

    pub fn update(
        &mut self,
        groups: Vec<ProcessGroup>,
        _theme: &ThemeConfig,
        visible_rows: usize,
        cum_share_by_key: HashMap<String, f32>,
    ) {
        let mut groups = groups;
        if let Some(ref user) = self.user_filter {
            groups.retain(|g| &g.user == user);
        }
        if groups.is_empty() {
            self.groups = vec![];
            self.flat_rows = vec![];
            return;
        }
        match self.sort_by.as_str() {
            "mem" => groups.sort_by(|a, b| b.mem_bytes.cmp(&a.mem_bytes)),
            "count" => groups.sort_by(|a, b| b.proc_count.cmp(&a.proc_count)),
            "cum" => groups.sort_by(|a, b| {
                let va = cum_share_by_key.get(&a.group_key).copied().unwrap_or(0.0);
                let vb = cum_share_by_key.get(&b.group_key).copied().unwrap_or(0.0);
                vb.partial_cmp(&va).unwrap_or(std::cmp::Ordering::Equal)
            }),
            _ => groups.sort_by(|a, b| b.cpu_pct.partial_cmp(&a.cpu_pct).unwrap_or(std::cmp::Ordering::Equal)),
        }
        self.apply_expanded_state(&mut groups);
        self.groups = groups;
        self.cum_share_by_key = cum_share_by_key;
        self.flat_rows = flatten_groups(&self.groups, &self.text_filter)
            .into_iter()
            .map(|(g, d): (&ProcessGroup, usize)| (g.clone(), d))
            .collect();
        self.scroll_offset = self.scroll_offset.min(self.flat_rows.len().saturating_sub(visible_rows).max(0));
        self.cursor_index = self.cursor_index.min(self.flat_rows.len().saturating_sub(1).max(0));
        self.scroll_to_cursor(visible_rows);
    }

    pub fn render(
        &self,
        area: Rect,
        theme: &ThemeConfig,
        buf: &mut Buffer,
    ) {
        const USER_W: usize = 8;
        const PROCS_W: usize = 6;
        const CPU_W: usize = 6;
        const CUMCPU_W: usize = 6;
        const MEMPCT_W: usize = 5;
        const MEM_W: usize = 7;
        let fixed_w = USER_W + PROCS_W + CPU_W + CUMCPU_W + MEMPCT_W + MEM_W + 6;
        let name_w = (area.width as usize).saturating_sub(fixed_w).max(20).min(64);

        let header_color = parse_color(&theme.proc_count);
        let active_style = if theme.proc_sort_active.to_lowercase().contains("bold") {
            Style::default().fg(header_color).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(header_color)
        };

        fn hdr_label(col: &str, active: bool) -> String {
            if active {
                format!("[{}]", col)
            } else {
                col.to_string()
            }
        }

        let mut header = "Command".to_string();
        if self.user_filter.is_some() {
            header.push_str(" [user]");
        }
        header = format!("{:<width$}", header, width = name_w);
        buf.set_string(area.x, area.y, &header, Style::default().fg(header_color));
        let x = area.x + name_w as u16 + 1;
        buf.set_string(x, area.y, &format!("{:<USER_W$}", "User"), Style::default().fg(header_color));
        let procs_lbl = hdr_label("#Procs", self.sort_by == "count");
        buf.set_string(x + USER_W as u16 + 1, area.y, &format!("{:>PROCS_W$}", procs_lbl), if self.sort_by == "count" { active_style } else { Style::default().fg(header_color) });
        let cpu_lbl = hdr_label("Cpu%", self.sort_by == "cpu");
        buf.set_string(x + USER_W as u16 + 1 + PROCS_W as u16 + 1, area.y, &format!("{:>CPU_W$}", cpu_lbl), if self.sort_by == "cpu" { active_style } else { Style::default().fg(header_color) });
        let cum_lbl = hdr_label("Cum%", self.sort_by == "cum");
        buf.set_string(x + USER_W as u16 + 1 + PROCS_W as u16 + 1 + CPU_W as u16 + 1, area.y, &format!("{:>CUMCPU_W$}", cum_lbl), if self.sort_by == "cum" { active_style } else { Style::default().fg(header_color) });
        let mem_lbl = hdr_label("Mem%", self.sort_by == "mem");
        buf.set_string(x + USER_W as u16 + 1 + PROCS_W as u16 + 1 + CPU_W as u16 + 1 + CUMCPU_W as u16 + 1, area.y, &format!("{:>MEMPCT_W$}", mem_lbl), if self.sort_by == "mem" { active_style } else { Style::default().fg(header_color) });
        buf.set_string(x + USER_W as u16 + 1 + PROCS_W as u16 + 1 + CPU_W as u16 + 1 + CUMCPU_W as u16 + 1 + MEMPCT_W as u16 + 1, area.y, &format!("{:>MEM_W$}", "MemB"), Style::default().fg(header_color));

        let visible_rows = (area.height as usize).saturating_sub(1).max(5);
        let start = self.scroll_offset;
        let end = (start + visible_rows).min(self.flat_rows.len());

        for (i, (g, depth)) in self.flat_rows[start..end].iter().enumerate() {
            let y = area.y + 1 + i as u16;
            let row_idx = start + i;
            let is_selected = row_idx == self.cursor_index;

            let indent = "  ".repeat(*depth);
            let expandable = !g.children.is_empty() || g.processes.len() > 1;
            let icon = if expandable {
                if g.expanded { "▼ " } else { "▶ " }
            } else if *depth > 0 {
                "· "
            } else {
                "  "
            };
            let display_name = if g.name.is_empty() { "[other]" } else { g.name.as_str() };
            let mut name_part = format!("{}{}{}", indent, icon, display_name);
            if name_part.len() > name_w {
                name_part = format!("{}…", &name_part[..name_w.saturating_sub(1)]);
            }
            name_part = format!("{:<width$}", name_part, width = name_w);

            let cumcpu = self.cum_share_by_key.get(&g.group_key).copied().unwrap_or(0.0);
            let row = format!(
                "{} {:<USER_W$} {:>PROCS_W$} {:>CPU_W$} {:>CUMCPU_W$} {:>MEMPCT_W$} {:>MEM_W$}",
                name_part,
                g.user.chars().take(USER_W).collect::<String>(),
                g.proc_count,
                format!("{:.1}", g.cpu_pct),
                format!("{:.1}", cumcpu),
                format!("{:.1}", g.mem_pct),
                utils::bytes_to_human(g.mem_bytes, false)
            );
            let style = if is_selected {
                Style::default().bg(Color::White).fg(Color::Black)
            } else {
                Style::default()
            };
            buf.set_string(area.x, y, &row, style);
        }
    }
}
