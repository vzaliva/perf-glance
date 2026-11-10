//! Process detail helpers for popup (status, exe path, cwd, age)

use crate::collectors::ProcessInfo;
use crate::utils;

#[cfg(target_os = "linux")]
pub fn read_status(pid: u32) -> (String, String) {
    let mut state = String::new();
    let mut threads = String::new();
    if let Ok(content) = std::fs::read_to_string(format!("/proc/{}/status", pid)) {
        for line in content.lines() {
            if line.starts_with("State:") {
                state = line
                    .split_whitespace()
                    .nth(1)
                    .unwrap_or("")
                    .trim_matches(|c| c == '(' || c == ')')
                    .to_string();
            } else if line.starts_with("Threads:") {
                threads = line.split_whitespace().nth(1).unwrap_or("?").to_string();
            }
        }
    }
    (state, threads)
}

#[cfg(not(target_os = "linux"))]
pub fn read_status(_pid: u32) -> (String, String) {
    ("?".into(), "?".into())
}

pub fn resolve_exe_path(pid: u32) -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(target) = std::fs::read_link(format!("/proc/{}/exe", pid)) {
            return target.to_string_lossy().to_string();
        }
    }
    String::new()
}

pub fn resolve_cwd_path(pid: u32) -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(target) = std::fs::read_link(format!("/proc/{}/cwd", pid)) {
            return target.to_string_lossy().to_string();
        }
    }
    String::new()
}

fn format_duration(seconds: f64) -> String {
    let total = seconds.max(0.0) as u64;
    let (days, rem) = (total / 86400, total % 86400);
    let (hours, rem) = (rem / 3600, rem % 3600);
    let (mins, secs) = (rem / 60, rem % 60);
    if days > 0 {
        format!("{}d {}h", days, hours)
    } else if hours > 0 {
        format!("{}h {}m", hours, mins)
    } else if mins > 0 {
        format!("{}m {}s", mins, secs)
    } else {
        format!("{}s", secs)
    }
}

fn read_uptime_seconds() -> Option<f64> {
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = std::fs::read_to_string("/proc/uptime") {
            if let Some(first) = content.split_whitespace().next() {
                if let Ok(secs) = first.parse::<f64>() {
                    return Some(secs);
                }
            }
        }
    }
    None
}

/// Process age from start time (Linux: /proc/pid/stat; fallback from ticks)
pub fn process_age(pid: u32, starttime_ticks: u64) -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = std::fs::read_to_string(format!("/proc/{}/stat", pid)) {
            if let Some(start_ticks_str) = content.split(')').nth(1).and_then(|s| s.split_whitespace().nth(19)) {
                if let Ok(ticks) = start_ticks_str.parse::<u64>() {
                    let hz = unsafe { libc::sysconf(libc::_SC_CLK_TCK) } as f64;
                    if hz > 0.0 {
                        if let Some(uptime) = read_uptime_seconds() {
                            let start_at = ticks as f64 / hz;
                            let age = uptime - start_at;
                            if age >= 0.0 {
                                return format_duration(age);
                            }
                        }
                    }
                }
            }
        }
        if starttime_ticks > 0 {
            if let Some(uptime) = read_uptime_seconds() {
                let hz = unsafe { libc::sysconf(libc::_SC_CLK_TCK) } as f64;
                if hz > 0.0 {
                    let start_at = starttime_ticks as f64 / hz;
                    let age = uptime - start_at;
                    if age >= 0.0 {
                        return format_duration(age);
                    }
                }
            }
        }
    }
    "?".to_string()
}

#[cfg(not(target_os = "linux"))]
pub fn process_age(_pid: u32, _starttime_ticks: u64) -> String {
    "?".to_string()
}

fn uid_to_user(uid: u32) -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(Some(user)) = nix::unistd::User::from_uid(nix::unistd::Uid::from_raw(uid)) {
            return user.name;
        }
    }
    uid.to_string()
}

/// Build popup body text for one process
pub fn process_popup_body(proc: &ProcessInfo) -> String {
    let (state, threads) = read_status(proc.pid);
    let exe_path = resolve_exe_path(proc.pid);
    let cwd_path = resolve_cwd_path(proc.pid);
    let user = uid_to_user(proc.uid);
    let age = process_age(proc.pid, proc.starttime_ticks);

    let state_str = if state.is_empty() { "?" } else { &state };
    let threads_str = if threads.is_empty() { "?" } else { &threads };
    let exe_path_str = if exe_path.is_empty() {
        "[unavailable]"
    } else {
        &exe_path
    };
    let cwd_str = if cwd_path.is_empty() {
        "[unavailable]"
    } else {
        &cwd_path
    };

    format!(
        "PID: {}    PPID: {}    User: {} ({})\n\
         Exe: {}\n\
         Path: {}\n\
         Workdir: {}\n\
         CPU%: {:.1}    Mem: {}    Threads: {}\n\
         State: {}    Age: {}\n\n\
         Command line:\n\
         {}",
        proc.pid,
        proc.ppid,
        user,
        proc.uid,
        proc.exe.is_empty().then(|| proc.name.as_str()).unwrap_or(&proc.exe),
        exe_path_str,
        cwd_str,
        proc.cpu_pct,
        utils::bytes_to_human(proc.rss_bytes, false),
        threads_str,
        state_str,
        age,
        proc.cmdline.is_empty().then(|| "[empty]".to_string()).unwrap_or(proc.cmdline.clone())
    )
}
