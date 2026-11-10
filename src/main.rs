//! perf-glance: terminal-based system utilization monitor

use perf_glance::config::Config;
use std::path::Path;

fn run_dump_groups(config_path: Option<&Path>, sort_by: &str) -> std::io::Result<()> {
    let config = Config::load(config_path)?;
    let exe_to_app = if config.grouping.desktop_dirs.is_empty() {
        std::collections::HashMap::new()
    } else {
        perf_glance::grouping::scan_desktop_entries(&config.grouping.desktop_dirs)
    };

    let mut system = sysinfo::System::new_all();
    system.refresh_all();
    let memory = perf_glance::collectors::read_memory(&mut system);
    let processes = perf_glance::collectors::read_processes(&mut system);
    let groups = perf_glance::grouping::group_processes(
        &processes,
        memory.ram_total_bytes,
        &config.grouping,
        &exe_to_app,
    );

    perf_glance::dump_groups::dump_group_tree(&groups, &mut std::io::stdout(), sort_by)?;
    Ok(())
}

fn main() -> std::io::Result<()> {
    let mut args = std::env::args().skip(1);
    let mut config_path: Option<std::path::PathBuf> = None;
    let mut interval: Option<u64> = None;
    let mut iterations: Option<u32> = None;
    let mut dump_groups = false;
    let mut dump_sort = "cpu".to_string();

    while let Some(arg) = args.next() {
        if let Some(val) = arg.strip_prefix("--dump-sort=") {
            dump_sort = val.to_string();
        } else {
            match arg.as_str() {
                "-i" | "--interval" => {
                    interval = args.next().and_then(|s| s.parse().ok());
                }
                "-n" | "--iterations" => {
                    iterations = args.next().and_then(|s| s.parse().ok());
                }
                "--config" => {
                    config_path = args.next().map(|s| s.into());
                }
                "--dump-groups" => dump_groups = true,
                "--dump-sort" => {
                    dump_sort = args.next().unwrap_or_else(|| "cpu".into());
                }
                _ => {}
            }
        }
    }

    if dump_groups {
        run_dump_groups(config_path.as_deref(), &dump_sort)?;
        return Ok(());
    }

    let mut config = Config::load(config_path.as_deref())?;
    if let Some(i) = interval {
        config.display.refresh_interval = i.max(1);
    }

    perf_glance::app::run(config, iterations)
}
