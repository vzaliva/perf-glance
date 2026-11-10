//! Memory (RAM and swap) section widget

use crate::config::ThemeConfig;
use crate::utils;
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::Color;

const BAR_WIDTH: usize = 32;
const FILLED: char = '█';
const EMPTY: char = '░';

fn parse_color(s: &str) -> Color {
    if s.starts_with('#') && s.len() >= 7 {
        if let (Ok(r), Ok(g), Ok(b)) = (
            u8::from_str_radix(&s[1..3], 16),
            u8::from_str_radix(&s[3..5], 16),
            u8::from_str_radix(&s[5..7], 16),
        ) {
            return Color::Rgb(r, g, b);
        }
    }
    Color::White
}

pub struct MemorySection;

impl MemorySection {
    pub fn render(
        area: Rect,
        ram_total: u64,
        ram_used: u64,
        ram_cached: u64,
        swap_total: u64,
        swap_used: u64,
        has_swap: bool,
        theme: &ThemeConfig,
        show_swap: bool,
        buf: &mut Buffer,
    ) {
        let header_color = parse_color(&theme.mem_used);
        buf.set_string(area.x, area.y, "Memory", Style::default().fg(header_color));

        let term_w = area.width as usize;
        let show_swap_val = show_swap && has_swap && swap_total > 0;
        let bar_w = if show_swap_val {
            ((term_w as i32 - 64) / 2).max(12).min(BAR_WIDTH as i32) as usize
        } else {
            (term_w as i32 - 32).max(12).min(BAR_WIDTH as i32) as usize
        };
        let bar_w = bar_w.max(12);

        let mut line = String::from("RAM  ");
        if ram_total > 0 {
            let used_frac = ram_used as f64 / ram_total as f64;
            let cached_frac = ram_cached as f64 / ram_total as f64;
            let used_w = (bar_w as f64 * used_frac + 0.5).min(bar_w as f64) as usize;
            let cached_w = (bar_w as f64 * cached_frac + 0.5).min((bar_w - used_w) as f64) as usize;
            let free_w = bar_w - used_w - cached_w;
            line.push('[');
            line.push_str(&FILLED.to_string().repeat(used_w));
            line.push_str(&FILLED.to_string().repeat(cached_w));
            line.push_str(&EMPTY.to_string().repeat(free_w));
            line.push_str("]  ");
        }
        let ram_pct = if ram_total > 0 {
            100.0 * ram_used as f64 / ram_total as f64
        } else {
            0.0
        };
        line.push_str(&format!(
            "{} / {}  ({:.0}%)",
            utils::bytes_to_human(ram_used, false),
            utils::bytes_to_human(ram_total, false),
            ram_pct
        ));
        buf.set_string(area.x, area.y + 1, &line, Style::default().fg(Color::White));

        if show_swap_val {
            let mut swap_line = String::from("   Swap ");
            let swap_frac = if swap_total > 0 {
                swap_used as f64 / swap_total as f64
            } else {
                0.0
            };
            let swap_w = (bar_w as f64 * swap_frac + 0.5).min(bar_w as f64) as usize;
            let swap_color = parse_color(&theme.mem_swap);
            swap_line.push('[');
            swap_line.push_str(&FILLED.to_string().repeat(swap_w));
            swap_line.push_str(&EMPTY.to_string().repeat(bar_w - swap_w));
            swap_line.push_str("]  ");
            let swap_pct = if swap_total > 0 {
                100.0 * swap_used as f64 / swap_total as f64
            } else {
                0.0
            };
            swap_line.push_str(&format!(
                "{} / {}  ({:.0}%)",
                utils::bytes_to_human(swap_used, false),
                utils::bytes_to_human(swap_total, false),
                swap_pct
            ));
            buf.set_string(area.x + 40, area.y + 1, &swap_line, Style::default().fg(swap_color));
        }
    }
}

use ratatui::style::Style;
