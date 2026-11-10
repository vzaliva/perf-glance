//! Scan .desktop files to build exe -> display name mapping

use std::collections::HashMap;
use std::path::{Path, PathBuf};

fn expand_path(s: &str) -> PathBuf {
    if s.starts_with("~/") {
        if let Some(home) = dirs::home_dir() {
            return home.join(&s[2..]);
        }
    } else if s == "~" {
        if let Some(home) = dirs::home_dir() {
            return home;
        }
    }
    PathBuf::from(s)
}

fn parse_exec(exec_line: &str) -> String {
    let mut remaining = exec_line.trim();
    if remaining.is_empty() {
        return String::new();
    }
    let parts: Vec<&str> = remaining.split_whitespace().collect();
    if !parts.is_empty() && (parts[0] == "env" || parts[0] == "/usr/bin/env") {
        remaining = parts.get(1).map(|s| *s).unwrap_or("");
        if let Some(rest) = remaining.split_once(char::is_whitespace) {
            remaining = rest.1;
        } else {
            remaining = "";
        }
    }
    while !remaining.is_empty() {
        if let Some(rest) = remaining.split_once('=') {
            let (key, val) = rest;
            if key.chars().next().map_or(false, |c| c.is_alphabetic() || c == '_') {
                remaining = val.trim_start();
                if remaining.starts_with('"') {
                    if let Some(end) = remaining[1..].find('"') {
                        remaining = remaining[end + 2..].trim_start();
                    } else {
                        break;
                    }
                } else if remaining.starts_with('\'') {
                    if let Some(end) = remaining[1..].find('\'') {
                        remaining = remaining[end + 2..].trim_start();
                    } else {
                        break;
                    }
                } else {
                    remaining = remaining.split_whitespace().nth(1).unwrap_or("").trim_start();
                }
                continue;
            }
        }
        break;
    }
    let cmd = remaining.split_whitespace().next().unwrap_or("");
    let cmd = regex::Regex::new(r"%[uUfFdDnNikvc]").unwrap().replace_all(cmd, "");
    let cmd = cmd.trim();
    if cmd.is_empty() {
        return String::new();
    }
    cmd.rsplit('/').next().unwrap_or(cmd).to_string()
}

fn parse_desktop_file(path: &Path) -> Option<(String, String, String)> {
    let content = std::fs::read_to_string(path).ok()?;
    let mut exec_val = String::new();
    let mut name_val = String::new();
    let mut wmclass_val = String::new();
    let mut in_desktop_entry = false;

    for line in content.lines() {
        let line = line.trim();
        if line == "[Desktop Entry]" {
            in_desktop_entry = true;
            continue;
        }
        if in_desktop_entry && line.starts_with('[') {
            break;
        }
        if !in_desktop_entry {
            continue;
        }
        if let Some((key, val)) = line.split_once('=') {
            let key = key.trim().to_lowercase();
            let val = val.trim();
            match key.as_str() {
                "exec" => exec_val = val.to_string(),
                "name" => name_val = val.to_string(),
                "startupwmclass" => wmclass_val = val.to_lowercase(),
                _ => {}
            }
        }
    }
    let exe = parse_exec(&exec_val);
    if exe.is_empty() {
        return None;
    }
    let display = if name_val.is_empty() { exe.clone() } else { name_val };
    Some((exe, display, wmclass_val))
}

/// Scan .desktop files in given directories. Returns exe (lowercase) -> display name.
pub fn scan_desktop_entries(dirs: &[String]) -> HashMap<String, String> {
    let mut result = HashMap::new();
    let mut seen_dirs = std::collections::HashSet::new();

    for dir_spec in dirs {
        let base = expand_path(dir_spec);
        if !base.is_dir() || seen_dirs.contains(&base) {
            continue;
        }
        seen_dirs.insert(base.clone());
        if let Ok(entries) = std::fs::read_dir(&base) {
            for e in entries.flatten() {
                let p = e.path();
                if p.is_file() && p.extension().map_or(false, |e| e == "desktop") {
                    if let Some((exe, display, wmclass)) = parse_desktop_file(&p) {
                        let exe_lower = exe.to_lowercase();
                        result.insert(exe_lower.clone(), display.clone());
                        let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
                        if stem != exe_lower {
                            result.insert(stem, display.clone());
                        }
                        if !wmclass.is_empty() {
                            result.insert(wmclass, display);
                        }
                    }
                }
            }
        }
    }
    result
}
