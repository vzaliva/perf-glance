//! Process list collector

use sysinfo::System;
use std::path::Path;

#[derive(Debug, Clone)]
pub struct ProcessInfo {
    pub pid: u32,
    pub ppid: u32,
    pub name: String,
    pub exe: String,
    pub cpu_pct: f32,
    pub rss_bytes: u64,
    pub cmdline: String,
    pub uid: u32,
    pub starttime_ticks: u64,
    pub exe_path: String,
}

fn effective_exe(raw_exe: &str) -> String {
    if raw_exe.is_empty() {
        return String::new();
    }
    let name = Path::new(raw_exe)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(raw_exe)
        .to_string();
    // Strip version number pattern like 3.12, 30.2
    let version_re = regex::Regex::new(r"^\d+(\.\d+)+$").unwrap();
    if version_re.is_match(&name) {
        if let Some(parent) = Path::new(raw_exe).parent() {
            if let Some(grandparent) = parent.parent() {
                let gp_name = grandparent
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("");
                if !gp_name.is_empty() && !version_re.is_match(gp_name) {
                    return gp_name.to_string();
                }
            }
        }
    }
    name
}

/// Read process list with CPU%. sysinfo provides cpu_usage() per process (0-100).
///
/// On Linux, sysinfo enumerates threads from `/proc/[pid]/task/` as separate processes.
/// We filter to only thread group leaders (pid == tgid) to match psutil/`ps` behavior.
pub fn read_processes(system: &mut System) -> Vec<ProcessInfo> {
    system.refresh_processes();
    system.refresh_cpu_usage();

    let mut processes = Vec::new();
    for (pid, proc_) in system.processes() {
        let pid_u32 = pid.as_u32();

        let mut uid_from_status = 0u32;
        #[cfg(target_os = "linux")]
        {
            if let Ok(content) = std::fs::read_to_string(format!("/proc/{}/status", pid_u32)) {
                let mut tgid = pid_u32;
                for line in content.lines() {
                    if line.starts_with("Tgid:") {
                        if let Some(t) = line.split_whitespace().nth(1) {
                            tgid = t.parse().unwrap_or(pid_u32);
                        }
                        break;
                    }
                }
                if tgid != pid_u32 {
                    continue; // thread (TID), not process (TGID) — skip to match psutil
                }
                for line in content.lines() {
                    if line.starts_with("Uid:") {
                        if let Some(u) = line.split_whitespace().nth(1) {
                            uid_from_status = u.parse().unwrap_or(0);
                        }
                        break;
                    }
                }
            }
        }

        let ppid = proc_.parent().map(|p| p.as_u32()).unwrap_or(0);
        let name = proc_.name().to_string();
        let exe_path = proc_
            .exe()
            .and_then(|p| p.to_str().map(String::from))
            .unwrap_or_default();
        let exe = {
            let raw = if exe_path.is_empty() {
                &name
            } else {
                &exe_path
            };
            let e = effective_exe(raw);
            if e.is_empty() {
                let cmdline_name = proc_
                    .cmd()
                    .first()
                    .map(|s| s.as_ref())
                    .unwrap_or("")
                    .rsplit('/')
                    .next()
                    .unwrap_or("")
                    .trim_end_matches(|c: char| c == ':' || c == ';' || c == ',');
                if cmdline_name.len() > name.len() {
                    cmdline_name.to_string()
                } else {
                    name.clone()
                }
            } else {
                e
            }
        };
        let exe_final = if exe.contains('/') {
            exe.rsplit('/').next().unwrap_or(&exe).to_string()
        } else {
            exe
        };

        let cmdline = proc_.cmd().join(" ");
        let cpu_pct = proc_.cpu_usage();
        let rss_bytes = proc_.memory();
        let uid = uid_from_status; // from /proc status on Linux; 0 elsewhere
        let starttime_ticks = (proc_.start_time() as u64)
            .saturating_mul(100)
            .min(u64::MAX / 2);

        processes.push(ProcessInfo {
            pid: pid_u32,
            ppid,
            name,
            exe: exe_final,
            cpu_pct,
            rss_bytes,
            cmdline,
            uid,
            starttime_ticks,
            exe_path,
        });
    }

    processes
}
