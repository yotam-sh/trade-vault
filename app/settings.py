"""App settings (key/value store) using TinyDB."""

from tinydb import Query
from app.connection import get_table, SETTINGS
from app.schemas import now_iso, validate_update


def get_setting(key, default=None):
    """Get a setting value by key."""
    table = get_table(SETTINGS)
    S = Query()
    result = table.search(S.key == key)
    if result:
        return result[0]['value']
    return default


def set_setting(key, value):
    """Set a setting value. Creates or updates."""
    table = get_table(SETTINGS)
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
