"""TinyDB database connection singleton and table constants."""

import os
import atexit
import threading
from tinydb import TinyDB
from tinydb.middlewares import CachingMiddleware

from app.storage import AtomicJSONStorage

_default_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'db.json')
DB_PATH = os.environ.get('DB_PATH', _default_db_path)

# Serializes writes/flushes across the gunicorn worker's threads. TinyDB's
# CachingMiddleware mutates a shared in-memory cache, which is not thread-safe.
_db_lock = threading.RLock()

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

    with _db_lock:
        # Detect external writes (e.g. CLI import while Flask is running). Discard the
        # stale cache WITHOUT flushing — flushing here would clobber the external write.
        if _db_instance is not None:
            try:
                current_mtime = os.path.getmtime(db_path)
                if current_mtime != _db_mtime:
                    _discard_db()
            except OSError:
                pass

        if _db_instance is None:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            _db_instance = TinyDB(
                db_path,
                storage=CachingMiddleware(AtomicJSONStorage),
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


def _discard_db():
    """Drop the in-memory DB instance WITHOUT flushing cached writes.

    Used when an external process (e.g. a CLI import) has written db.json while we
    held a stale cache.  Resetting the CachingMiddleware's modified counter ensures
    the subsequent close() does not write our stale cache over the external changes.
    """
    global _db_instance, _db_mtime
    if _db_instance is None:
        return
    try:
        middleware = _db_instance.storage  # CachingMiddleware
        if hasattr(middleware, '_cache_modified_count'):
            middleware._cache_modified_count = 0
        if hasattr(middleware, 'cache'):
            middleware.cache = None
        _db_instance.close()
    except Exception:
        pass
    _db_instance = None
    _db_mtime = None


def flush_db():
    """Flush the CachingMiddleware write cache to disk without closing."""
    global _db_mtime
    with _db_lock:
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
    with _db_lock:
        if _db_instance is not None:
            _db_instance.close()
            _db_instance = None
            _db_mtime = None


atexit.register(close_db)


def install_shutdown_handler():
    """Flush+close the DB on SIGTERM (e.g. `docker stop` on a bare-metal process).

    Python does not run atexit handlers on an un-handled SIGTERM, so cached writes
    would be lost. Call this from the dev server and CLI entrypoints — NOT under
    gunicorn, which installs its own worker SIGTERM handling.
    """
    import signal

    def _handler(signum, frame):
        close_db()
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass  # not in the main thread / signal unsupported on this platform


