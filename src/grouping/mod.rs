//! Process grouping logic

mod desktop_entries;
mod patterns;
mod process_groups;
mod rules_loader;

pub use desktop_entries::scan_desktop_entries;
pub use process_groups::{group_processes, ProcessGroup, proc_label};
pub use rules_loader::{load_grouping_rules, CompiledRules};
