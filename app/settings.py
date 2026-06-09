"""App settings (key/value store) using TinyDB.

Per-portfolio settings live in each portfolio's `settings` table (get_setting /
set_setting). Market-data facts that are identical across portfolios — the yfinance
ticker map and the benchmark series cache — use the *shared* store accessors so they
are fetched once and seen by every portfolio.
"""

from tinydb import Query
from app.connection import get_table, get_shared_table, flush_shared, SETTINGS
from app.schemas import now_iso, validate_update


def _get(table, key, default):
    S = Query()
    result = table.search(S.key == key)
    return result[0]['value'] if result else default


def _set(table, key, value):
    S = Query()
    existing = table.search(S.key == key)
    record = {'key': key, 'value': value, 'updated_at': now_iso()}
    valid, errors = validate_update('settings', record)
    if not valid:
        raise ValueError(f"Invalid setting update: {errors}")
    if existing:
        table.update(record, S.key == key)
    else:
        table.insert(record)


def get_setting(key, default=None):
    """Get a per-portfolio setting value by key."""
    return _get(get_table(SETTINGS), key, default)


def set_setting(key, value):
    """Set a per-portfolio setting value. Creates or updates."""
    _set(get_table(SETTINGS), key, value)


def get_shared_setting(key, default=None):
    """Get a setting from the shared market-data store (all portfolios)."""
    return _get(get_shared_table(SETTINGS), key, default)


def set_shared_setting(key, value):
    """Set a setting in the shared market-data store and flush it."""
    _set(get_shared_table(SETTINGS), key, value)
    flush_shared()


def init_default_settings():
    """Initialize default settings and run any pending schema migrations."""
    from app.db_backup import migrate_db, rotate_backup
    # Snapshot the current DB before any startup mutation (migrations/repairs).
    rotate_backup()
    migrate_db()

    defaults = {
        'default_currency': 'ILS',
        'cost_method': 'fifo',
        'last_import_date': None,
        'graph_layout': {
            'order': ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
            'widths': {'A': 100, 'B': 100, 'C': 100, 'D': 100, 'E': 100, 'F': 100, 'G': 100},
            'hidden': [],
            'locked': [],
        },
    }
    for key, value in defaults.items():
        if get_setting(key) is None:
            set_setting(key, value)
