//! CPU utilization and frequency collector

use sysinfo::System;

#[derive(Debug, Clone)]
pub struct CpuSnapshot {
    pub per_core_pct: Vec<f32>,
    pub aggregate_pct: f32,
    pub frequency_ghz: Option<f32>,
    pub per_core_freq_ghz: Option<Vec<Option<f32>>>,
}

/// Read current CPU utilization. First call returns zeros; second call (after delay) returns percentages.
pub fn read_cpu(system: &mut System, _previous: Option<&CpuSnapshot>) -> CpuSnapshot {
    system.refresh_cpu_usage();

    let cpus = system.cpus();
    let per_core_pct: Vec<f32> = cpus.iter().map(|c| c.cpu_usage()).collect();
    let aggregate_pct = system.global_cpu_info().cpu_usage();

    // Per-core frequency (sysinfo provides this on supported platforms)
    let per_core_freq_ghz: Option<Vec<Option<f32>>> = {
        let freqs: Vec<Option<f32>> = cpus
            .iter()
            .map(|c| {
                let f = c.frequency();
                if f > 0 {
                    Some(f as f32 / 1000.0) // MHz -> GHz
                } else {
                    None
                }
            })
            .collect();
        if freqs.iter().any(|f| f.is_some()) {
            Some(freqs)
        } else {
            None
        }
    };

    let frequency_ghz = per_core_freq_ghz.as_ref().and_then(|freqs| {
        let valid: Vec<f32> = freqs.iter().filter_map(|&f| f).collect();
        if valid.is_empty() {
            None
        } else {
            Some(valid.iter().sum::<f32>() / valid.len() as f32)
        }
    });

    CpuSnapshot {
        per_core_pct,
        aggregate_pct,
        frequency_ghz,
        per_core_freq_ghz,
    }
}

/// Return aggregate CPU time proxy (used for compatibility; sysinfo gives process cpu_usage directly)
pub fn get_aggregate_cpu_times(system: &System) -> f64 {
    system.global_cpu_info().cpu_usage() as f64
}
