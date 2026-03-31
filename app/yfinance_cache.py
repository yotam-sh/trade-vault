"""yfinance cache CRUD - stores fetched yfinance data separate from holdings."""

from tinydb import Query
from app.connection import get_table, YFINANCE_CACHE


def get_yfinance_cache(holding_id):
    """Get cached yfinance data for a holding. Returns dict or empty dict."""
    table = get_table(YFINANCE_CACHE)
    C = Query()
    results = table.search(C.holding_id == holding_id)
    return results[0] if results else {}


def upsert_yfinance_cache(holding_id, data):
    """Create or fully replace the yfinance cache entry for a holding."""
    table = get_table(YFINANCE_CACHE)
    C = Query()
    record = {'holding_id': holding_id, **data}
    existing = table.search(C.holding_id == holding_id)
    if existing:
        table.update(record, C.holding_id == holding_id)
    else:
        table.insert(record)
