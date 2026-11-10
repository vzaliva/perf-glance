//! Data collectors for system metrics

mod cpu;
mod memory;
mod processes;
mod temperature;

pub use cpu::{CpuSnapshot, read_cpu, get_aggregate_cpu_times};
pub use memory::{MemorySnapshot, read_memory};
pub use processes::{ProcessInfo, read_processes};
pub use temperature::read_temperature;
