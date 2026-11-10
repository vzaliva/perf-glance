//! Dump process group tree to stdout (for testing)

use crate::grouping::{proc_label, ProcessGroup};
use crate::utils;
use std::io::Write;

const NAME_WIDTH: usize = 32;
const USER_WIDTH: usize = 8;
const PROCS_WIDTH: usize = 6;
const CPU_WIDTH: usize = 6;
const MEMPCT_WIDTH: usize = 5;
const MEM_WIDTH: usize = 7;

fn make_pid_leaves(g: &mut ProcessGroup) {
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
            depth: g.depth + 1,
            group_key: format!("{}|pid:{}", g.group_key, p.pid),
        });
    }
}

fn expand_all(groups: &mut [ProcessGroup]) {
    for g in groups.iter_mut() {
        if !g.children.is_empty() {
            g.expanded = true;
            expand_all(&mut g.children);
        } else if g.processes.len() > 1 {
            make_pid_leaves(g);
            if !g.children.is_empty() {
                g.expanded = true;
            }
        }
    }
}

fn flatten_expanded(groups: &[ProcessGroup], depth: usize) -> Vec<(&ProcessGroup, usize)> {
    let mut result = Vec::new();
    for g in groups {
        result.push((g, depth));
        if !g.children.is_empty() {
            result.extend(flatten_expanded(&g.children, depth + 1));
        }
    }
    result
}

fn format_row(g: &ProcessGroup, depth: usize, name_width: usize) -> String {
    let indent = "  ".repeat(depth);
    let icon = if g.children.is_empty() { "  " } else { "▼ " };
    let display_name = if g.name.is_empty() { "[other]" } else { g.name.as_str() };
    let name_part = format!("{}{}{}", indent, icon, display_name);
    let name_part = format!("{:<width$}", name_part, width = name_width);
    format!(
        "{} {:<USER_WIDTH$} {:>PROCS_WIDTH$} {:>CPU_WIDTH$} {:>MEMPCT_WIDTH$} {:>MEM_WIDTH$}",
        name_part,
        g.user,
        g.proc_count,
        format!("{:.1}", g.cpu_pct),
        format!("{:.1}", g.mem_pct),
        utils::bytes_to_human(g.mem_bytes, false)
    )
}

/// Dump the full group tree (expanded) to the given writer
pub fn dump_group_tree<W: Write>(
    groups: &[ProcessGroup],
    mut w: W,
    sort_by: &str,
) -> std::io::Result<()> {
    if groups.is_empty() {
        writeln!(w, "(no groups)")?;
        return Ok(());
    }

    let mut groups = groups.to_vec();
    match sort_by {
        "mem" => groups.sort_by(|a, b| b.mem_bytes.cmp(&a.mem_bytes)),
        "count" => groups.sort_by(|a, b| b.proc_count.cmp(&a.proc_count)),
        _ => groups.sort_by(|a, b| b.cpu_pct.partial_cmp(&a.cpu_pct).unwrap_or(std::cmp::Ordering::Equal)),
    }

    expand_all(&mut groups);
    let flat = flatten_expanded(&groups, 0);

    let mut name_width = "Command".len();
    for (g, depth) in &flat {
        let indent = "  ".repeat(*depth);
        let icon = if g.children.is_empty() { "  " } else { "▼ " };
        let display_name = if g.name.is_empty() { "[other]" } else { g.name.as_str() };
        name_width = name_width.max(indent.len() + icon.len() + display_name.len());
    }
    name_width = name_width.max(NAME_WIDTH);

    writeln!(
        w,
        "{:<width$} {} {:>PROCS_WIDTH$} {:>CPU_WIDTH$} {:>MEMPCT_WIDTH$} {:>MEM_WIDTH$}",
        "Command",
        format!("{:<USER_WIDTH$}", "User"),
        "#Procs",
        "Cpu%",
        "Mem%",
        "MemB",
        width = name_width
    )?;
    let sep_len = name_width + 1 + USER_WIDTH + 1 + PROCS_WIDTH + 1 + CPU_WIDTH + 1 + MEMPCT_WIDTH + 1 + MEM_WIDTH;
    writeln!(w, "{}", "-".repeat(sep_len))?;
    for (g, depth) in flat {
        writeln!(w, "{}", format_row(g, depth, name_width))?;
    }
    Ok(())
}
