//! perf-glance: terminal-based system utilization monitor for Linux and macOS

pub mod app;
pub mod config;
pub mod dump_groups;
pub mod grouping;
pub mod process_info;
pub mod widgets;

pub mod collectors;
pub mod utils;

pub use app::run;
pub use config::Config;
