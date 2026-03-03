"""Line graph rendering with Braille, eighth-blocks, or ASCII."""

from __future__ import annotations

# Braille patterns: 2 columns x 4 rows per character
# Each cell encodes 8 dots. We use ⣀⣄⣆⣇⡇⣿ etc. for smooth line
# Simpler: use block chars ▁▂▃▄▅▆▇█ (U+2581 to U+2588) - 1/8 to 8/8
# ASCII fallback: .-'|

EIGHTH_BLOCKS = " ▁▂▃▄▅▆▇█"  # index 0 = empty, 8 = full
ASCII_CHARS = "_.-'|"


def render_line_graph(
    values: list[float],
    width: int,
    height: int = 4,
    use_braille: bool = True,
    use_unicode: bool = True,
) -> str:
    """Render a line graph. Values 0-100, newest on right. Returns multiline string."""
    if not values or width <= 0 or height <= 0:
        return ""

    # Use the most recent `width` values
    samples = values[-width:] if len(values) > width else values
    if not samples:
        return ""

    min_val = 0.0
    max_val = 100.0
    r = max_val - min_val
    if r <= 0:
        r = 1.0

    lines: list[list[str]] = []
    for _ in range(height):
        lines.append([""] * len(samples))

    if use_unicode and use_braille:
        return _render_braille(samples, width, height)
    elif use_unicode:
        return _render_eighth_blocks(samples, width, height)
    else:
        return _render_ascii(samples, width, height)


def _render_eighth_blocks(samples: list[float], width: int, height: int) -> str:
    """Use ▁▂▃▄▅▆▇█ for 8 vertical levels per character."""
    # Each row is 1/height of the range. We have 8 sub-levels via chars
    rows: list[str] = []
    for row_idx in range(height - 1, -1, -1):
        line_chars = []
        y_lo = 100.0 * row_idx / height
        y_hi = 100.0 * (row_idx + 1) / height
        for v in samples:
            if v <= y_lo:
                line_chars.append(EIGHTH_BLOCKS[0])
            elif v >= y_hi:
                line_chars.append(EIGHTH_BLOCKS[8])
            else:
                frac = (v - y_lo) / (y_hi - y_lo)
                idx = int(frac * 8)
                if idx >= 8:
                    idx = 7
                line_chars.append(EIGHTH_BLOCKS[idx + 1])
        rows.append("".join(line_chars))
    return "\n".join(rows)


def _render_braille(samples: list[float], width: int, height: int) -> str:
    """Use Braille patterns for 2x4 pixel cells. More compact."""
    # Braille: each char is 2 cols x 4 rows. So we need ceil(width/2) chars per row,
    # and we use 4 rows of pixels. Height in terminal rows = ceil(pixel_height / 4)
    # For simplicity, use 4 terminal rows = 16 pixel rows. Each sample = 1 column.
    # Braille cell: dots 1-8. We approximate the line through the cell.
    # Simpler: fall back to eighth-blocks for now - Braille is complex for arbitrary graphs
    return _render_eighth_blocks(samples, width, height)


def _render_ascii(samples: list[float], width: int, height: int) -> str:
    """Use ASCII chars _.-'| for fallback."""
    rows: list[str] = []
    for row_idx in range(height - 1, -1, -1):
        line_chars = []
        y_lo = 100.0 * row_idx / height
        y_hi = 100.0 * (row_idx + 1) / height
        for v in samples:
            if v <= y_lo:
                line_chars.append(" ")
            elif v >= y_hi:
                line_chars.append("|")
            else:
                frac = (v - y_lo) / (y_hi - y_lo)
                if frac < 0.25:
                    line_chars.append("_")
                elif frac < 0.5:
                    line_chars.append(".")
                elif frac < 0.75:
                    line_chars.append("-")
                else:
                    line_chars.append("'")
        rows.append("".join(line_chars))
    return "\n".join(rows)
