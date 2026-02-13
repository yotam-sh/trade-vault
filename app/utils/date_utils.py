"""Date utilities including TASE trading calendar logic."""

import os
import re
from datetime import datetime


def parse_date_from_filename(filename):
    """Parse date from filename format DDMMYYYY.xlsx -> ISO date string.

    Used for trade files and morning balance files.

    Args:
        filename: Filename like "17122025.xlsx" or full path

    Returns:
        ISO date string like "2025-12-17"

    Raises:
        ValueError: If filename doesn't match expected pattern
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    m = re.match(r'^(\d{2})(\d{2})(\d{4})$', base)
    if not m:
        raise ValueError(f"Cannot parse date from filename: {filename}")
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def is_tase_weekend(date_str):
    """Check if a date falls on a TASE weekend (non-trading day of week).

    TASE switched from Sun-Thu to Mon-Fri trading on 2026-01-05.
    - Before 2026-01-05: Friday + Saturday are off
    - After 2026-01-05: Saturday + Sunday are off

    Args:
        date_str: ISO date string like "2026-01-15"

    Returns:
        True if date is a weekend (non-trading day)
    """
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    wd = dt.weekday()  # Mon=0 ... Sun=6

    if date_str < '2026-01-05':
        return wd in (4, 5)  # Fri, Sat
    else:
        return wd in (5, 6)  # Sat, Sun


def parse_excel_date(value):
    """Parse date from Excel cell value (handles both datetime and string).

    Args:
        value: Excel cell value (datetime object or string)

    Returns:
        ISO date string or None if value is None
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    return str(value)
