//! Memory (RAM and swap) collector

#[derive(Debug, Clone)]
pub struct MemorySnapshot {
    pub ram_total_bytes: u64,
    pub ram_used_bytes: u64,
    pub ram_cached_bytes: u64,
    pub ram_percent: f32,
    pub swap_total_bytes: u64,
    pub swap_used_bytes: u64,
    pub swap_percent: f32,
    pub has_swap: bool,
}

/// Read current memory and swap usage
pub fn read_memory(system: &mut sysinfo::System) -> MemorySnapshot {
    system.refresh_memory();

    let ram_total = system.total_memory();
    let ram_free = system.free_memory();
    let ram_available = system.available_memory();
    // Used ≈ total - available (more accurate than total - free on Linux)
    let ram_used = ram_total.saturating_sub(ram_available).max(ram_total.saturating_sub(ram_free));
    // Cached: on Linux, (free - available) approximates buffers+cached
    let ram_cached = ram_free.saturating_sub(ram_available);
    let ram_percent = if ram_total > 0 {
        100.0 * ram_used as f32 / ram_total as f32
    } else {
        0.0
    };

    let swap_total = system.total_swap();
    let swap_free = system.free_swap();
    let swap_used = swap_total.saturating_sub(swap_free);
    let swap_percent = if swap_total > 0 {
        100.0 * swap_used as f32 / swap_total as f32
    } else {
        0.0
    };
    let has_swap = swap_total > 0;

    MemorySnapshot {
        ram_total_bytes: ram_total,
        ram_used_bytes: ram_used,
        ram_cached_bytes: ram_cached,
        ram_percent,
        swap_total_bytes: swap_total,
        swap_used_bytes: swap_used,
        swap_percent,
        has_swap,
    }
}
