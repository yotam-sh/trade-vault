"""TinyDB database connection singleton and table constants."""

import os
import atexit
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'db.json')

# Table name constants
HOLDINGS = 'holdings'
TRANSACTIONS = 'transactions'
DAILY_PRICES = 'daily_prices'
PORTFOLIO_SNAPSHOTS = 'portfolio_snapshots'
DIVIDENDS = 'dividends'
IMPORTS = 'imports'
SETTINGS = 'settings'
TAX_LOTS = 'tax_lots'

_db_instance = None


def get_db(path=None):
    """Get or create the TinyDB singleton instance."""
    global _db_instance
    if _db_instance is None:
        db_path = path or DB_PATH
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _db_instance = TinyDB(
            db_path,
            storage=CachingMiddleware(JSONStorage),
            ensure_ascii=False,
            indent=2,
            encoding='utf-8'
        )
    return _db_instance


def get_table(name):
    """Get a named table from the database."""
    return get_db().table(name)


def close_db():
    """Close the database and flush caching middleware."""
    global _db_instance
    if _db_instance is not None:
        _db_instance.close()
        _db_instance = None


atexit.register(close_db)


