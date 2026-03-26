"""App settings (key/value store) using TinyDB."""

from tinydb import Query
from app.connection import get_table, SETTINGS
from app.schemas import now_iso


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
    if existing:
        table.update(record, S.key == key)
    else:
        table.insert(record)


def init_default_settings():
    """Initialize default settings if not already set."""
    defaults = {
        'default_currency': 'ILS',
        'cost_method': 'fifo',
        'ticker_map': {},
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
