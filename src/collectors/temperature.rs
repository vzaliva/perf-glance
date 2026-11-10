//! CPU temperature collector

/// Read CPU temperature in Celsius. Returns None if unavailable.
#[cfg(target_os = "linux")]
pub fn read_temperature() -> Option<f32> {
    use std::fs;
    use std::path::Path;

    let keys_pref = ["coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"];
    let mut temps: Vec<f32> = Vec::new();

    let hwmon_base = Path::new("/sys/class/hwmon");
    if !hwmon_base.exists() {
        return None;
    }

    let read_temp = |path: &Path| -> Option<f32> {
        fs::read_to_string(path).ok().and_then(|s| s.trim().parse().ok())
    };

    for entry in fs::read_dir(hwmon_base).ok()?.flatten() {
        let name_path = entry.path().join("name");
        let name = fs::read_to_string(&name_path).ok()?.trim().to_lowercase();

        if keys_pref.iter().any(|k| name.contains(k)) {
            for i in 0..16 {
                let temp_path = entry.path().join(format!("temp{i}_input"));
                if temp_path.exists() {
                    if let Some(t) = read_temp(&temp_path) {
                        let label_path = entry.path().join(format!("temp{i}_label"));
                        let label = fs::read_to_string(&label_path)
                            .unwrap_or_default()
                            .to_lowercase();
                        // Prefer package/core/cpu sensors
                        let is_relevant = label.is_empty()
                            || label.contains("core")
                            || label.contains("package")
                            || label.contains("cpu")
                            || label.contains("tdie")
                            || label.contains("tctl");
                        if is_relevant {
                            temps.push(t / 1000.0); // millidegrees -> Celsius
                        }
                    }
                }
            }
            if temps.is_empty() {
                for i in 0..16 {
                    let temp_path = entry.path().join(format!("temp{i}_input"));
                    if temp_path.exists() {
                        if let Some(t) = read_temp(&temp_path) {
                            temps.push(t / 1000.0);
                        }
                    }
                }
            }
        }
    }

    // Fallback: any hwmon temp
    if temps.is_empty() {
        for entry in fs::read_dir(hwmon_base).ok()?.flatten() {
            for i in 0..16 {
                let temp_path = entry.path().join(format!("temp{i}_input"));
                if temp_path.exists() {
                    if let Some(t) = read_temp(&temp_path) {
                        temps.push(t / 1000.0);
                    }
                }
            }
        }
    }

    temps.into_iter().max_by(|a, b| a.partial_cmp(b).unwrap())
}

/// macOS: temperature often not exposed without IOKit; return None for now
#[cfg(target_os = "macos")]
pub fn read_temperature() -> Option<f32> {
    None
}
