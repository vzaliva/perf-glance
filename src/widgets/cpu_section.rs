//! CPU utilization section widget

use crate::collectors::CpuSnapshot;
use crate::config::ThemeConfig;
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use std::collections::VecDeque;

// Index = prev*5 + curr. Index 6 = graph_bg: grey dotted baseline for empty cells (btop-style).
const BRAILLE_UP: &[&str] = &[
    " ", "⢀", "⢠", "⢰", "⢸",
    "⡀", "⣀", "⣠", "⣰", "⣸",
    "⡄", "⣄", "⣤", "⣴", "⣼",
    "⡆", "⣆", "⣦", "⣶", "⣾",
    "⡇", "⣇", "⣧", "⣷", "⣿",
];
const BRAILLE_BASELINE: &str = "⣀"; // Grey dotted baseline for empty cells (Python/btop: green over grey)
const BASELINE_COLOR: Color = Color::Gray; // Visible grey for baseline dots (DarkGray can be too dim)
const BRAILLE_DOWN: &[&str] = &[
    " ", "⠈", "⠘", "⠸", "⢸",
    "⠁", "⠉", "⠙", "⠹", "⢹",
    "⠃", "⠋", "⠛", "⠻", "⢻",
    "⠇", "⠏", "⠟", "⠿", "⢿",
    "⡇", "⡏", "⡟", "⡿", "⣿",
];

const LABEL_W: usize = 4;
const METRIC_W: usize = 11;
const GAP_W: usize = 2;
const SEP_W: usize = 2; // " │"

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

fn cpu_color(pct: f32, theme: &ThemeConfig) -> Color {
    if pct < 50.0 {
        parse_color(&theme.cpu_low)
    } else if pct < 80.0 {
        parse_color(&theme.cpu_mid)
    } else {
        parse_color(&theme.cpu_high)
    }
}

fn temp_color(temp: f32, theme: &ThemeConfig) -> Color {
    if temp <= 70.0 {
        parse_color(&theme.temp_low)
    } else if temp <= 85.0 {
        parse_color(&theme.temp_mid)
    } else {
        parse_color(&theme.temp_high)
    }
}

fn quantize_to_level(value: f32, cur_high: f32, cur_low: f32, mod_: f32) -> usize {
    if value >= cur_high {
        return 4;
    }
    if value <= cur_low {
        return 0;
    }
    let r = cur_high - cur_low;
    if r <= 0.0 {
        return 0;
    }
    ((value - cur_low) * 4.0 / r + mod_).round() as usize
}

pub struct CpuSection {
    pub agg_history: VecDeque<f32>,
    pub core_history: Vec<VecDeque<(f32, Color)>>,
}

impl Default for CpuSection {
    fn default() -> Self {
        Self {
            agg_history: VecDeque::with_capacity(600),
            core_history: Vec::new(),
        }
    }
}

impl CpuSection {
    pub fn update(
        &mut self,
        snapshot: &CpuSnapshot,
        _temp: Option<f32>,
        theme: &ThemeConfig,
        _show_freq: bool,
        _show_temp: bool,
    ) {
        let per_core = &snapshot.per_core_pct;
        let n = per_core.len();
        while self.core_history.len() < n {
            self.core_history.push(VecDeque::with_capacity(300));
        }
        for (i, &pct) in per_core.iter().enumerate() {
            let c = cpu_color(pct, theme);
            self.core_history[i].push_back((pct, c));
            if self.core_history[i].len() > 300 {
                self.core_history[i].pop_front();
            }
        }
        self.agg_history.push_back(snapshot.aggregate_pct);
        if self.agg_history.len() > 600 {
            self.agg_history.pop_front();
        }
    }

    pub fn render(
        &self,
        area: Rect,
        snapshot: &CpuSnapshot,
        temp: Option<f32>,
        theme: &ThemeConfig,
        show_freq: bool,
        show_temp: bool,
        buf: &mut Buffer,
    ) {
        let graph_color = parse_color(&theme.cpu_graph);
        let mut header = format!("CPU");
        if show_freq {
            if let Some(f) = snapshot.frequency_ghz {
                header.push_str(&format!("  {:.1}GHz (core avg),", f));
            }
        }
        header.push_str(&format!("  {:.0}%", snapshot.aggregate_pct));
        buf.set_string(area.x, area.y, &header, Style::default().fg(graph_color));
        if show_temp {
            if let Some(t) = temp {
                let temp_str = format!("Temp: {:.0}°C", t);
                let pad = area
                    .width
                    .saturating_sub(header.len() as u16)
                    .saturating_sub(temp_str.len() as u16)
                    .max(2);
                let pad_str = " ".repeat(pad as usize);
                buf.set_string(area.x + header.len() as u16, area.y, &pad_str, Style::default().fg(graph_color));
                buf.set_string(area.x + header.len() as u16 + pad, area.y, &temp_str, Style::default().fg(temp_color(t, theme)));
            }
        }

        let per_core = &snapshot.per_core_pct;
        let n_cores = per_core.len();
        if n_cores == 0 {
            return;
        }

        let term_w = area.width as usize;
        let n_rows = ((n_cores + 1) / 2).max(2);
        let n_rows = if n_rows % 2 == 1 { n_rows + 1 } else { n_rows };
        let metric_w = if show_freq { METRIC_W } else { METRIC_W - 5 };
        let core_fixed = 2 * LABEL_W + 2 * metric_w + GAP_W;
        // Equal 50/50 split: graph and per-core panel same width
        let graph_w = ((term_w - SEP_W) / 2).max(10);
        let core_chart_w = ((graph_w - core_fixed) / 2).max(4);

        let half = n_rows / 2;

        let agg: Vec<f32> = self.agg_history.iter().copied().collect();
        let n_samples = graph_w * 2;
        let raw: Vec<f32> = if agg.len() >= n_samples {
            agg[agg.len() - n_samples..].to_vec()
        } else {
            let mut v = vec![0.0; n_samples.saturating_sub(agg.len())];
            v.extend(agg);
            v
        };

        for row in 0..n_rows {
            let y = area.y + 1 + row as u16;
            if y >= area.bottom() {
                break;
            }
            let is_top = row < half;
            let (cur_high, cur_low, symbols) = if is_top {
                let horizon = row;
                let ch = 100.0 * (half - horizon) as f32 / half as f32;
                let cl = 100.0 * (half - horizon - 1) as f32 / half as f32;
                (ch, cl, BRAILLE_UP)
            } else {
                let horizon_inner = row - half;
                let horizon = half - 1 - horizon_inner;
                let ch = 100.0 * (half - horizon) as f32 / half as f32;
                let cl = 100.0 * (half - horizon - 1) as f32 / half as f32;
                (ch, cl, BRAILLE_DOWN)
            };

            let axis_row = half - 1; // Central baseline (0% axis) - dotted only here, plain space elsewhere
            for col in 0..graph_w {
                let idx_l = col * 2;
                let idx_r = col * 2 + 1;
                let v_prev = raw.get(idx_l).copied().unwrap_or(0.0);
                let v_curr = raw.get(idx_r).copied().unwrap_or(0.0);
                let r0 = quantize_to_level(v_prev, cur_high, cur_low, 0.1);
                let r1 = quantize_to_level(v_curr, cur_high, cur_low, 0.1);
                let sym_idx = r0 * 5 + r1;
                let char_str = symbols.get(sym_idx).unwrap_or(&" ");
                let (display_char, cell_color) = if *char_str == " " {
                    if row == axis_row {
                        (BRAILLE_BASELINE, BASELINE_COLOR)
                    } else {
                        (" ", Color::Reset) // Plain space for clean background (matches Python)
                    }
                } else {
                    (char_str.as_ref(), cpu_color(v_prev.max(v_curr), theme))
                };
                let x_pos = area.x + col as u16;
                buf.set_string(x_pos, y, display_char, Style::default().fg(cell_color));
            }

            let sep_x = area.x + graph_w as u16;
            buf.set_string(sep_x, y, " │", Style::default().fg(Color::DarkGray));

            for col in 0..2 {
                let idx = row + col * n_rows; // Left col: 0..n_rows-1, right col: n_rows..2*n_rows-1 (matches Python)
                if idx >= n_cores {
                    continue;
                }
                if col == 1 {
                    buf.set_string(sep_x + 2 + (LABEL_W + core_chart_w + metric_w) as u16, y, &" ".repeat(GAP_W), Style::default());
                }
                let core_x = sep_x + 2 + (col as usize * (LABEL_W + core_chart_w + metric_w + GAP_W)) as u16;
                let pct = per_core[idx];
                let label = format!("C{:<2} ", idx);
                buf.set_string(core_x, y, &label, Style::default().fg(Color::DarkGray));
                let hist: Vec<(f32, Color)> = self.core_history.get(idx).map(|h| h.iter().copied().collect()).unwrap_or_default();
                let chart_cells = render_per_core_chart(&hist, core_chart_w, theme);
                for (coli, (char_str, cell_color)) in chart_cells.iter().enumerate() {
                    buf.set_string(core_x + LABEL_W as u16 + coli as u16, y, char_str, Style::default().fg(*cell_color));
                }
                let freq_str = if show_freq {
                    snapshot.per_core_freq_ghz.as_ref()
                        .and_then(|f| f.get(idx).and_then(|v| *v))
                        .map(|f| format!(" {:.1}G", f))
                        .unwrap_or_default()
                } else {
                    String::new()
                };
                let metrics = format!(" {:3.0}%{}", pct, freq_str);
                buf.set_string(core_x + LABEL_W as u16 + core_chart_w as u16, y, &metrics, Style::default().fg(cpu_color(pct, theme)));
            }
        }

        let baseline_y = area.y + 1 + n_rows as u16;
        if baseline_y < area.bottom() {
            buf.set_string(area.x, baseline_y, &"─".repeat(graph_w), Style::default().fg(Color::DarkGray));
            buf.set_string(area.x + graph_w as u16, baseline_y, "─┘", Style::default().fg(Color::DarkGray));
        }
    }
}

fn render_per_core_chart(history: &[(f32, Color)], width: usize, theme: &ThemeConfig) -> Vec<(String, Color)> {
    let n = history.len();
    let samples: Vec<(f32, Color)> = if n >= width * 2 {
        history[n - width * 2..].to_vec()
    } else {
        let pad = (width * 2).saturating_sub(n);
        let mut v = vec![(0.0f32, Color::DarkGray); pad];
        v.extend(history.iter().cloned());
        v
    };
    let mut result = Vec::with_capacity(width);
    for col in 0..width {
        let idx_prev = col * 2;
        let idx_curr = col * 2 + 1;
        let (v_prev, _) = samples.get(idx_prev).copied().unwrap_or((0.0, Color::DarkGray));
        let (v_curr, _) = samples.get(idx_curr).copied().unwrap_or((0.0, Color::DarkGray));
        let r0 = quantize_to_level(v_prev, 100.0, 0.0, 0.3);
        let r1 = quantize_to_level(v_curr, 100.0, 0.0, 0.3);
        let sym_idx = r0 * 5 + r1;
        let char_str = BRAILLE_UP.get(sym_idx).unwrap_or(&" ").to_string();
        let (display_char, cell_color) = if char_str == " " {
            (BRAILLE_BASELINE.to_string(), BASELINE_COLOR)
        } else {
            (char_str, cpu_color(v_prev.max(v_curr), theme))
        };
        result.push((display_char, cell_color));
    }
    result
}
