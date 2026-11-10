//! Shared grouping pattern types

#[derive(Debug, Clone)]
pub struct AppPattern {
    pub exe: String,
    pub name: String,
    pub family: String,
    pub cmdline: String,
    pub no_tool_reclaim: bool,
}

#[derive(Debug, Clone)]
pub struct ToolPattern {
    pub exe: String,
    pub name: String,
    pub category: String,
    /// Case-insensitive cmdline substring filter; such patterns win over exe-only ones.
    pub cmdline: String,
    /// False for long-running servers: group is not labeled "build (N procs)".
    pub build: bool,
}
