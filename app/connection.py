"""TinyDB database connection singleton and table constants."""

import os
import atexit
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

_default_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'db.json')
DB_PATH = os.environ.get('DB_PATH', _default_db_path)

# Table name constants
HOLDINGS = 'holdings'
TRANSACTIONS = 'transactions'
DAILY_PRICES = 'daily_prices'
PORTFOLIO_SNAPSHOTS = 'portfolio_snapshots'

IMPORTS = 'imports'
SETTINGS = 'settings'
TAX_LOTS = 'tax_lots'
YFINANCE_CACHE = 'yfinance_cache'

_db_instance = None
_db_mtime = None


def get_db(path=None):
    """Get or create the TinyDB singleton instance.

    If db.json was modified externally (e.g. CLI import while Flask is running),
    the stale in-memory cache is discarded and the DB is reopened from disk.
    """
    global _db_instance, _db_mtime
    db_path = path or DB_PATH

    # Detect external writes (e.g. CLI import while Flask is running)
    if _db_instance is not None:
        try:
            current_mtime = os.path.getmtime(db_path)
            if current_mtime != _db_mtime:
                _db_instance.close()
                _db_instance = None
        except OSError:
            pass

    if _db_instance is None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _db_instance = TinyDB(
            db_path,
            storage=CachingMiddleware(JSONStorage),
            ensure_ascii=False,
            indent=2,
            encoding='utf-8'
        )
        try:
            _db_mtime = os.path.getmtime(db_path)
        except OSError:
            _db_mtime = None

    return _db_instance


def get_table(name):
    """Get a named table from the database."""
    return get_db().table(name)


def flush_db():
    """Flush the CachingMiddleware write cache to disk without closing."""
    global _db_mtime
    if _db_instance is not None:
        _db_instance.storage.flush()
        # Update mtime so we don't re-open our own flush as an external change
        try:
            _db_mtime = os.path.getmtime(DB_PATH)
        except OSError:
            pass


def close_db():
    """Close the database and flush caching middleware."""
    global _db_instance, _db_mtime
    if _db_instance is not None:
        _db_instance.close()
        _db_instance = None
        _db_mtime = None


atexit.register(close_db)


