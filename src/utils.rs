//! Utility helpers for formatting and display

/// Format bytes as human-readable string (e.g. 380M, 1.5G, 31.4 GiB).
pub fn bytes_to_human(b: u64, use_gib: bool) -> String {
    if b == 0 {
        return "0".to_string();
    }
    if b < 1024 {
        return format!("{b}B");
    }
    let units: &[(u64, &str)] = if use_gib {
        &[
            (1 << 40, "TiB"),
            (1 << 30, "GiB"),
            (1 << 20, "MiB"),
            (1 << 10, "KiB"),
        ]
    } else {
        &[
            (1 << 40, "T"),
            (1 << 30, "G"),
            (1 << 20, "M"),
            (1 << 10, "K"),
        ]
    };
    for &(size, unit) in units {
        if b >= size {
            let val = b as f64 / size as f64;
            return if val >= 10.0 || val.fract() == 0.0 {
                format!("{}{unit}", val as u64)
            } else {
                format!("{val:.1}{unit}")
            };
        }
    }
    format!("{b}B")
}

/// Format duration in seconds to compact human form (e.g. "2h 30m", "45s")
pub fn format_duration(seconds: f64) -> String {
    let total = seconds.max(0.0) as u64;
    let (days, rem) = (total / 86400, total % 86400);
    let (hours, rem) = (rem / 3600, rem % 3600);
    let (mins, secs) = (rem / 60, rem % 60);
    if days > 0 {
        format!("{days}d {hours}h")
    } else if hours > 0 {
        format!("{hours}h {mins}m")
    } else if mins > 0 {
        format!("{mins}m {secs}s")
    } else {
        format!("{secs}s")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bytes_to_human() {
        assert_eq!(bytes_to_human(0, false), "0");
        assert_eq!(bytes_to_human(500, false), "500B");
        assert_eq!(bytes_to_human(1024, false), "1K");
        assert_eq!(bytes_to_human(30 * 1024 * 1024, false), "30M");
        assert_eq!(bytes_to_human(1536 * 1024 * 1024, false), "1.5G");
    }
}
