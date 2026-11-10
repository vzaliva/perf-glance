//! Main TUI application

use crate::collectors::{read_cpu, read_memory, read_processes, read_temperature};
use crate::config::Config;
use crate::grouping::{group_processes, scan_desktop_entries};
use crate::process_info::process_popup_body;
use crate::widgets::{CpuSection, MemorySection, ProcessSection};
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use nix::sys::signal::{self, Signal};
use nix::unistd::Pid;
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout},
    widgets::Widget,
    Terminal,
};
use std::io::{self, stdout};
use sysinfo::System;

const MIN_WIDTH: u16 = 70;
const MIN_HEIGHT: u16 = 15;

#[derive(Clone)]
struct PopupContent {
    title: String,
    body: String,
}

enum AppMode {
    Main,
    FilterInput(String),
    Popup(PopupContent),
}

fn kill_processes(pids: &[u32], sig: Signal) -> (usize, usize, usize, usize) {
    let mut ok = 0;
    let mut missing = 0;
    let mut denied = 0;
    let mut failed = 0;
    for &pid in pids {
        let result = signal::kill(Pid::from_raw(pid as i32), Some(sig));
        match result {
            Ok(()) => ok += 1,
            Err(nix::errno::Errno::ESRCH) => missing += 1,
            Err(nix::errno::Errno::EPERM) => denied += 1,
            Err(_) => failed += 1,
        }
    }
    (ok, missing, denied, failed)
}

pub fn run(mut config: Config, iterations: Option<u32>) -> io::Result<()> {
    enable_raw_mode()?;
    let mut stdout = stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut system = System::new_all();
    system.refresh_all();

    let mut cpu_section = CpuSection::default();
    let mut process_section = ProcessSection::default();

    let exe_to_app = if !config.grouping.desktop_dirs.is_empty() {
        scan_desktop_entries(&config.grouping.desktop_dirs)
    } else {
        std::collections::HashMap::new()
    };

    let mut cpu_snap = read_cpu(&mut system, None);
    std::thread::sleep(std::time::Duration::from_millis(500));
    cpu_snap = read_cpu(&mut system, Some(&cpu_snap));

    let mut iteration_count: u32 = 0;
    let mut cum_by_key: std::collections::HashMap<String, f64> = std::collections::HashMap::new();
    let mut prev_pct_by_key: std::collections::HashMap<String, f32> = std::collections::HashMap::new();
    let mut prev_sample_ts: Option<f64> = None;
    let mut last_refresh = std::time::Instant::now();
    let mut refresh_interval_secs = config.display.refresh_interval.max(1) as u64;

    system.refresh_all();
    let mut memory = read_memory(&mut system);
    let processes = read_processes(&mut system);
    let mut groups = group_processes(&processes, memory.ram_total_bytes, &config.grouping, &exe_to_app);
    let temp = read_temperature();
    cpu_snap = read_cpu(&mut system, Some(&cpu_snap));
    cpu_section.update(
        &cpu_snap,
        temp,
        &config.theme,
        config.display.show_cpu_freq,
        config.display.show_cpu_temp,
    );
    let mut cum_share = std::collections::HashMap::new();
    let current_user = std::env::var("USER").unwrap_or_default();
    let mut last_temp = temp;
    process_section.update(groups.clone(), &config.theme, 8, cum_share.clone());

    let mut mode = AppMode::Main;
    let mut message: Option<(String, std::time::Instant)> = None;
    const MESSAGE_DURATION: std::time::Duration = std::time::Duration::from_secs(2);

    loop {
        let poll_timeout = std::time::Duration::from_millis(100);
        let mut should_break = false;
        let mut need_refresh = false;

        while event::poll(poll_timeout)? {
            match event::read()? {
                Event::Key(key) => {
                    if key.kind != KeyEventKind::Press && key.kind != KeyEventKind::Repeat {
                        continue;
                    }

                    match &mut mode {
                        AppMode::Popup(_) => {
                            match key.code {
                                KeyCode::Esc | KeyCode::Char('q') | KeyCode::Char('Q') => {
                                    mode = AppMode::Main;
                                }
                                KeyCode::Char('k') => {
                                    let mut pids = process_section.selected_pids(false);
                                    if pids.is_empty() {
                                        pids = process_section.selected_pids(true);
                                    }
                                    if !pids.is_empty() {
                                        let (ok, missing, denied, failed) =
                                            kill_processes(&pids, Signal::SIGTERM);
                                        let mut parts = Vec::new();
                                        if ok > 0 {
                                            parts.push(format!("signaled {}", ok));
                                        }
                                        if missing > 0 {
                                            parts.push(format!("missing {}", missing));
                                        }
                                        if denied > 0 {
                                            parts.push(format!("denied {}", denied));
                                        }
                                        if failed > 0 {
                                            parts.push(format!("failed {}", failed));
                                        }
                                        message = Some((
                                            format!("SIGTERM: {}", parts.join(", ")),
                                            std::time::Instant::now(),
                                        ));
                                        mode = AppMode::Main;
                                        need_refresh = ok > 0;
                                    }
                                }
                                KeyCode::Char('K') => {
                                    let pids = process_section.selected_pids(true);
                                    if !pids.is_empty() {
                                        let (ok, missing, denied, failed) =
                                            kill_processes(&pids, Signal::SIGKILL);
                                        let mut parts = Vec::new();
                                        if ok > 0 {
                                            parts.push(format!("signaled {}", ok));
                                        }
                                        if missing > 0 {
                                            parts.push(format!("missing {}", missing));
                                        }
                                        if denied > 0 {
                                            parts.push(format!("denied {}", denied));
                                        }
                                        if failed > 0 {
                                            parts.push(format!("failed {}", failed));
                                        }
                                        message = Some((
                                            format!("SIGKILL: {}", parts.join(", ")),
                                            std::time::Instant::now(),
                                        ));
                                        mode = AppMode::Main;
                                        need_refresh = ok > 0;
                                    }
                                }
                                _ => {}
                            }
                        }
                        AppMode::FilterInput(buf) => {
                            match key.code {
                                KeyCode::Esc => {
                                    process_section.clear_text_filter();
                                    mode = AppMode::Main;
                                }
                                KeyCode::Enter => {
                                    process_section.set_text_filter(buf);
                                    mode = AppMode::Main;
                                }
                                KeyCode::Backspace => {
                                    buf.pop();
                                    process_section.set_text_filter(buf);
                                }
                                KeyCode::Char(c) => {
                                    buf.push(c);
                                    process_section.set_text_filter(buf);
                                }
                                _ => {}
                            }
                        }
                        AppMode::Main => {
                            match key.code {
                                KeyCode::Char('q') | KeyCode::Char('Q') => {
                                    should_break = true;
                                    break;
                                }
                                KeyCode::Char('r') | KeyCode::Char('R') => {
                                    need_refresh = true;
                                }
                                KeyCode::Char('+') => {
                                    refresh_interval_secs =
                                        (refresh_interval_secs + 1).min(60);
                                    config.display.refresh_interval = refresh_interval_secs;
                                }
                                KeyCode::Char('-') => {
                                    refresh_interval_secs =
                                        (refresh_interval_secs - 1).max(1);
                                    config.display.refresh_interval = refresh_interval_secs;
                                }
                                KeyCode::Char('s') | KeyCode::Char('S') => {
                                    process_section.cycle_sort();
                                    need_refresh = true;
                                }
                                KeyCode::Char('u') | KeyCode::Char('U') => {
                                    let active =
                                        process_section.toggle_user_filter(&current_user);
                                    message = Some((
                                        if active {
                                            format!("Showing only {} processes", current_user)
                                        } else {
                                            "Showing all processes".into()
                                        },
                                        std::time::Instant::now(),
                                    ));
                                }
                                KeyCode::Up => process_section.do_scroll_up(),
                                KeyCode::Down => process_section.do_scroll_down(),
                                KeyCode::Right => {
                                    let _ = process_section.do_expand();
                                }
                                KeyCode::Enter => {
                                    if let Some(proc) = process_section.selected_individual_process()
                                    {
                                        let title = format!(
                                            "Process {}  {}",
                                            proc.pid,
                                            proc.exe.is_empty()
                                                .then(|| proc.name.as_str())
                                                .unwrap_or(&proc.exe)
                                        );
                                        let body = process_popup_body(&proc);
                                        mode = AppMode::Popup(PopupContent { title, body });
                                    } else {
                                        let _ = process_section.do_expand();
                                    }
                                }
                                KeyCode::Left | KeyCode::Backspace => {
                                    let _ = process_section.do_collapse();
                                }
                                KeyCode::Char('/') => {
                                    mode = AppMode::FilterInput(
                                        process_section.text_filter.clone(),
                                    );
                                }
                                KeyCode::Esc => {
                                    process_section.clear_text_filter();
                                }
                                KeyCode::Char('0') => {
                                    process_section.reset_cumulative();
                                    cum_by_key.clear();
                                    prev_pct_by_key.clear();
                                    prev_sample_ts = None;
                                    message = Some((
                                        "Cumulative CPU counters reset".into(),
                                        std::time::Instant::now(),
                                    ));
                                }
                                KeyCode::Char('k') => {
                                    let mut pids = process_section.selected_pids(false);
                                    if pids.is_empty() {
                                        pids = process_section.selected_pids(true);
                                    }
                                    if !pids.is_empty() {
                                        let (ok, missing, denied, failed) =
                                            kill_processes(&pids, Signal::SIGTERM);
                                        let mut parts = Vec::new();
                                        if ok > 0 {
                                            parts.push(format!("signaled {}", ok));
                                        }
                                        if missing > 0 {
                                            parts.push(format!("missing {}", missing));
                                        }
                                        if denied > 0 {
                                            parts.push(format!("denied {}", denied));
                                        }
                                        if failed > 0 {
                                            parts.push(format!("failed {}", failed));
                                        }
                                        message = Some((
                                            format!("SIGTERM: {}", parts.join(", ")),
                                            std::time::Instant::now(),
                                        ));
                                        need_refresh = ok > 0;
                                    } else {
                                        message = Some((
                                            "No process PIDs found for selected row/group"
                                                .into(),
                                            std::time::Instant::now(),
                                        ));
                                    }
                                }
                                KeyCode::Char('K') => {
                                    let pids = process_section.selected_pids(true);
                                    if !pids.is_empty() {
                                        let (ok, missing, denied, failed) =
                                            kill_processes(&pids, Signal::SIGKILL);
                                        let mut parts = Vec::new();
                                        if ok > 0 {
                                            parts.push(format!("signaled {}", ok));
                                        }
                                        if missing > 0 {
                                            parts.push(format!("missing {}", missing));
                                        }
                                        if denied > 0 {
                                            parts.push(format!("denied {}", denied));
                                        }
                                        if failed > 0 {
                                            parts.push(format!("failed {}", failed));
                                        }
                                        message = Some((
                                            format!("SIGKILL: {}", parts.join(", ")),
                                            std::time::Instant::now(),
                                        ));
                                        need_refresh = ok > 0;
                                    } else {
                                        message = Some((
                                            "No process PIDs found for selected row/group"
                                                .into(),
                                            std::time::Instant::now(),
                                        ));
                                    }
                                }
                                KeyCode::Char('?') => {
                                    message = Some((
                                        "q quit  r refresh  +/- interval  s sort  u user  / filter  0 reset  k kill  K kill-9  ↑↓ move  enter info  → expand  ← collapse".into(),
                                        std::time::Instant::now(),
                                    ));
                                }
                                _ => {}
                            }
                        }
                    }
                }
                _ => {}
            }
        }

        if should_break {
            break;
        }

        // Clear stale message
        if let Some((_, t)) = &message {
            if t.elapsed() > MESSAGE_DURATION {
                message = None;
            }
        }

        iteration_count += 1;
        if let Some(max_iter) = iterations {
            if iteration_count >= max_iter {
                break;
            }
        }

        let refresh_interval =
            std::time::Duration::from_secs(refresh_interval_secs);
        let should_refresh = last_refresh.elapsed() >= refresh_interval || need_refresh;

        if should_refresh {
            system.refresh_all();
            memory = read_memory(&mut system);
            let processes = read_processes(&mut system);
            groups = group_processes(
                &processes,
                memory.ram_total_bytes,
                &config.grouping,
                &exe_to_app,
            );

            let sample_ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs_f64();
            let top_level_keys: std::collections::HashSet<String> =
                groups.iter().map(|g| g.group_key.clone()).collect();
            if let Some(prev_ts) = prev_sample_ts {
                let dt = sample_ts - prev_ts;
                if dt > 0.0 {
                    for g in &groups {
                        let key = g.group_key.clone();
                        let prev_pct = prev_pct_by_key.get(&key).copied().unwrap_or(0.0);
                        let curr_pct = g.cpu_pct;
                        let cum = cum_by_key.get(&key).copied().unwrap_or(0.0);
                        cum_by_key.insert(
                            key,
                            cum + ((prev_pct as f64 + curr_pct as f64) * 0.5 * dt),
                        );
                    }
                }
            }
            for g in &groups {
                prev_pct_by_key.insert(g.group_key.clone(), g.cpu_pct);
            }
            prev_sample_ts = Some(sample_ts);

            let denom: f64 = top_level_keys
                .iter()
                .filter_map(|k| cum_by_key.get(k))
                .sum::<f64>()
                .max(1e-9);
            cum_share = groups
                .iter()
                .map(|g| {
                    let share =
                        100.0 * cum_by_key.get(&g.group_key).copied().unwrap_or(0.0) / denom;
                    (g.group_key.clone(), share as f32)
                })
                .collect();

            last_temp = read_temperature();
            cpu_snap = read_cpu(&mut system, Some(&cpu_snap));
            cpu_section.update(
                &cpu_snap,
                last_temp,
                &config.theme,
                config.display.show_cpu_freq,
                config.display.show_cpu_temp,
            );
            last_refresh = std::time::Instant::now();
        }

        terminal.draw(|f| {
            // CPU height: header(1) + graph rows + baseline(1). n_rows from core count.
            let n_cores = cpu_snap.per_core_pct.len();
            let cpu_n_rows = if n_cores == 0 {
                0
            } else {
                let r = ((n_cores + 1) / 2).max(2);
                if r % 2 == 1 { r + 1 } else { r }
            };
            let cpu_height = (2 + cpu_n_rows).max(2) as u16;

            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(cpu_height),  // CPU: exact height
                    Constraint::Length(2),          // Memory: fixed 2 lines
                    Constraint::Fill(1),            // Process: all remaining space
                    Constraint::Length(1),          // Footer
                ])
                .split(f.area());

            let (w, h) = (f.area().width, f.area().height);
            if w < MIN_WIDTH || h < MIN_HEIGHT {
                let msg = format!(
                    "Terminal too small ({}×{}). Minimum: {}×{}.",
                    w, h, MIN_WIDTH, MIN_HEIGHT
                );
                f.render_widget(ratatui::widgets::Paragraph::new(msg), f.area());
                return;
            }

            let cpu_area = chunks[0];
            let mem_area = chunks[1];
            let proc_area = chunks[2];
            let footer_area = chunks[3];

            let visible_rows = (proc_area.height as usize).saturating_sub(2).max(5);
            process_section.update(groups.clone(), &config.theme, visible_rows, cum_share.clone());

            cpu_section.render(
                cpu_area,
                &cpu_snap,
                last_temp,
                &config.theme,
                config.display.show_cpu_freq,
                config.display.show_cpu_temp,
                f.buffer_mut(),
            );

            MemorySection::render(
                mem_area,
                memory.ram_total_bytes,
                memory.ram_used_bytes,
                memory.ram_cached_bytes,
                memory.swap_total_bytes,
                memory.swap_used_bytes,
                memory.has_swap,
                &config.theme,
                config.display.show_swap,
                f.buffer_mut(),
            );

            // Process list (or split with filter bar)
            let (proc_list_area, filter_bar_area) = match &mode {
                AppMode::FilterInput(buf) if proc_area.height >= 2 => {
                    let list_h = proc_area.height - 1;
                    let list = ratatui::layout::Rect {
                        x: proc_area.x,
                        y: proc_area.y,
                        width: proc_area.width,
                        height: list_h,
                    };
                    let bar = ratatui::layout::Rect {
                        x: proc_area.x,
                        y: proc_area.y + list_h,
                        width: proc_area.width,
                        height: 1,
                    };
                    (list, Some((bar, buf)))
                }
                _ => (proc_area, None),
            };
            process_section.render(proc_list_area, &config.theme, f.buffer_mut());
            if let Some((bar, buf)) = filter_bar_area {
                f.render_widget(
                    ratatui::widgets::Paragraph::new(format!("Filter: {}_", buf))
                        .style(ratatui::style::Style::default().fg(ratatui::style::Color::Cyan)),
                    bar,
                );
            }

            // Popup overlay
            if let AppMode::Popup(popup) = &mode {
                let (pw, ph) = (f.area().width, f.area().height);
                let popup_w = (pw * 3 / 4).min(80).max(40);
                let popup_h = (ph * 3 / 4).min(24).max(10);
                let px = (pw - popup_w) / 2;
                let py = (ph - popup_h) / 2;
                let popup_rect = ratatui::layout::Rect {
                    x: px,
                    y: py,
                    width: popup_w,
                    height: popup_h,
                };
                // Clear inner area
                let clear_style = ratatui::style::Style::default()
                    .bg(ratatui::style::Color::Black)
                    .fg(ratatui::style::Color::White);
                for y in popup_rect.y..popup_rect.y + popup_rect.height {
                    for x in popup_rect.x..popup_rect.x + popup_rect.width {
                        f.render_widget(
                            ratatui::widgets::Paragraph::new(" ")
                                .style(clear_style),
                            ratatui::layout::Rect {
                                x,
                                y,
                                width: 1,
                                height: 1,
                            },
                        );
                    }
                }
                let border = ratatui::widgets::Block::default()
                    .borders(ratatui::widgets::Borders::ALL)
                    .border_style(ratatui::style::Style::default().fg(ratatui::style::Color::Cyan));
                let inner = border.inner(popup_rect);
                ratatui::widgets::Block::default()
                    .borders(ratatui::widgets::Borders::ALL)
                    .border_style(ratatui::style::Style::default().fg(ratatui::style::Color::Cyan))
                    .render(popup_rect, f.buffer_mut());
                let mut lines = vec![ratatui::text::Line::from(popup.title.as_str())];
                for line in popup.body.lines().take((inner.height as usize).saturating_sub(3)) {
                    lines.push(ratatui::text::Line::from(line));
                }
                lines.push(ratatui::text::Line::from(""));
                lines.push(ratatui::text::Line::from(
                    "ESC close   k SIGTERM   K SIGKILL",
                ));
                let text = ratatui::text::Text::from(lines);
                f.render_widget(
                    ratatui::widgets::Paragraph::new(text)
                        .wrap(ratatui::widgets::Wrap { trim: true }),
                    inner,
                );
            }

            // Footer
            let footer = if let Some((msg, _)) = &message {
                msg.clone()
            } else {
                " q quit  s sort  u user  / filter  ↵ info  k/K kill  0 reset  ? help ".to_string()
            };
            f.render_widget(
                ratatui::widgets::Paragraph::new(footer)
                    .style(ratatui::style::Style::default().fg(ratatui::style::Color::DarkGray)),
                footer_area,
            );
        })?;
    }

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}
