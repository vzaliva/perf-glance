"""Human-readable number formatting."""


def bytes_to_human(b: int, use_gib: bool = False) -> str:
    """Format bytes as human-readable string (e.g. 380M, 1.5G, 31.4 GiB)."""
    if b <= 0:
        return "0"
    if b < 1024:
        return f"{b}B"
    if use_gib:
        units = [
            (1 << 40, "TiB"),
            (1 << 30, "GiB"),
            (1 << 20, "MiB"),
            (1 << 10, "KiB"),
        ]
    else:
        units = [
            (1 << 40, "T"),
            (1 << 30, "G"),
            (1 << 20, "M"),
            (1 << 10, "K"),
        ]
    for size, unit in units:
        if b >= size:
            val = b / size
            if val >= 10 or val == int(val):
                return f"{int(val)}{unit}"
            return f"{val:.1f}{unit}"
    return f"{b}B"
