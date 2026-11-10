//! Tests for process grouping (ported from Python test_grouping.py)

use perf_glance::collectors::ProcessInfo;
use perf_glance::config::GroupingConfig;
use perf_glance::grouping::group_processes;
use std::collections::HashMap;

fn mock_process(
    pid: u32,
    ppid: u32,
    name: &str,
    exe: &str,
    cpu_pct: f32,
    rss: u64,
    cmdline: &str,
) -> ProcessInfo {
    ProcessInfo {
        pid,
        ppid,
        name: name.to_string(),
        exe: exe.to_string(),
        cpu_pct,
        rss_bytes: rss,
        cmdline: cmdline.to_string(),
        uid: 1000,
        starttime_ticks: 0,
        exe_path: String::new(),
    }
}

fn minimal_config() -> GroupingConfig {
    GroupingConfig {
        desktop_dirs: vec![],
        other_cpu_max: 0.1,
        other_mem_max: 30 << 20,
        default_expanded: vec![],
        expand_threshold: 0,
    }
}

const RAM: u64 = 1_000_000_000; // 1 GB

#[test]
fn test_group_processes_basic() {
    let processes = vec![
        mock_process(10, 1, "firefox", "firefox", 5.0, 100_000_000, "firefox"),
        mock_process(
            11,
            10,
            "Web Content",
            "firefox",
            3.0,
            50_000_000,
            "firefox -contentproc ...",
        ),
    ];
    let config = minimal_config();
    let exe_to_app = HashMap::new();
    let groups = group_processes(&processes, RAM, &config, &exe_to_app);
    assert!(!groups.is_empty());
    let total_procs: usize = groups.iter().map(|g| g.proc_count).sum();
    assert_eq!(total_procs, 2, "all processes should be accounted for");
}

#[test]
fn test_bytes_to_human() {
    assert_eq!(perf_glance::utils::bytes_to_human(0, false), "0");
    assert_eq!(perf_glance::utils::bytes_to_human(1024, false), "1K");
    assert_eq!(perf_glance::utils::bytes_to_human(30 * 1024 * 1024, false), "30M");
}

#[test]
fn test_proc_label_node_retitled_single_argv() {
    // Node CLI that rewrote process.title (argv == [title]), e.g. pi.
    let p = mock_process(1, 0, "pi", "node", 0.0, 0, "pi");
    assert_eq!(perf_glance::grouping::proc_label(&p), "pi");
}

#[test]
fn test_proc_label_node_bare_stays_node() {
    let p = mock_process(1, 0, "node", "node", 0.0, 0, "node");
    assert_eq!(perf_glance::grouping::proc_label(&p), "node");
}
