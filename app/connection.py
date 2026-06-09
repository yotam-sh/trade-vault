"""TinyDB database connection and table constants.

Multi-portfolio aware: each portfolio is its own db file. The *active* portfolio is
resolved per-context from a ContextVar (set per Flask request, or via using_portfolio()
in CLI/background threads); with none set it falls back to DB_PATH (the default file,
also what tests point at). A separate fixed shared db (shared.json) holds market-data
caches that all portfolios read.
"""

import os
import atexit
import threading
import contextvars
from contextlib import contextmanager
from tinydb import TinyDB
from tinydb.middlewares import CachingMiddleware

from app.storage import AtomicJSONStorage

_default_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'db.json')
# Default/back-compat path: the first portfolio's file and the anchor for the db/
# directory (shared store, auth sidecar, registry all live alongside it).
DB_PATH = os.environ.get('DB_PATH', _default_db_path)

# Serializes writes/flushes across the worker's threads. TinyDB's CachingMiddleware
# mutates a shared in-memory cache, which is not thread-safe.
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
CHART_CACHE = 'chart_cache'  # derived chart payloads; safe to drop/rebuild

# Open TinyDB instances and their last-seen mtimes, keyed by absolute file path.
_instances = {}
_mtimes = {}

# Active portfolio id for the current context; None => the default DB_PATH file.
_active_pid = contextvars.ContextVar('active_portfolio_id', default=None)


# ── Active-portfolio context ─────────────────────────────────────────────────

def set_active_portfolio(pid):
    """Set the active portfolio id for this context. Returns a reset token."""
    return _active_pid.set(pid)


def reset_active_portfolio(token):
    """Restore the active portfolio to a previous value using its token."""
    _active_pid.reset(token)


def current_portfolio_id():
    """The active portfolio id in this context (None => default file)."""
    return _active_pid.get()


@contextmanager
def using_portfolio(pid):
    """Run a block with `pid` as the active portfolio (CLI / background threads)."""
    token = _active_pid.set(pid)
    try:
        yield
    finally:
        _active_pid.reset(token)


def db_dir():
    """Directory that holds db.json, the shared store, the registry and auth sidecar."""
    return os.path.dirname(DB_PATH)


def active_db_path():
    """Absolute path of the active portfolio's db file (DB_PATH when none active)."""
    pid = _active_pid.get()
    if pid is None:
        return DB_PATH
    from app.portfolios import portfolio_path  # lazy: avoids import cycle
    return portfolio_path(pid) or DB_PATH


def shared_db_path():
    """Fixed shared market-data store, alongside the default db file."""
    return os.path.join(db_dir(), 'shared.json')


# ── Connection management ────────────────────────────────────────────────────

def _open(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _instances[db_path] = TinyDB(
        db_path,
        storage=CachingMiddleware(AtomicJSONStorage),
        ensure_ascii=False,
        indent=2,
        encoding='utf-8',
    )
    try:
        _mtimes[db_path] = os.path.getmtime(db_path)
    except OSError:
        _mtimes[db_path] = None
    return _instances[db_path]


def get_db(path=None):
    """Get or create the TinyDB instance for `path` (default: the active portfolio).

    If the file was modified externally (e.g. a CLI import while Flask runs), the
    stale in-memory cache is discarded and reopened from disk.
    """
    db_path = path or active_db_path()
    with _db_lock:
        if db_path in _instances:
            try:
                if os.path.getmtime(db_path) != _mtimes.get(db_path):
                    _discard_path(db_path)  # external write: drop stale cache
            except OSError:
                pass
        if db_path not in _instances:
            _open(db_path)
        return _instances[db_path]


def get_table(name):
    """Get a named table from the active portfolio's database."""
    return get_db().table(name)


def get_shared_db():
    """The shared market-data store (yfinance cache, benchmark, ticker map)."""
    return get_db(shared_db_path())


def get_shared_table(name):
    """Get a named table from the shared market-data store."""
    return get_shared_db().table(name)


def _discard_path(db_path):
    """Drop an in-memory instance WITHOUT flushing (external write detected)."""
    inst = _instances.pop(db_path, None)
    _mtimes.pop(db_path, None)
    if inst is None:
        return
    try:
        middleware = inst.storage  # CachingMiddleware
        if hasattr(middleware, '_cache_modified_count'):
            middleware._cache_modified_count = 0
        if hasattr(middleware, 'cache'):
            middleware.cache = None
        inst.close()
    except Exception:
        pass


def forget_path(db_path):
    """Close and drop an instance (used before deleting its file on disk)."""
    with _db_lock:
        _discard_path(db_path)


def _flush_path(db_path):
    with _db_lock:
        inst = _instances.get(db_path)
        if inst is not None:
            inst.storage.flush()
            try:
                _mtimes[db_path] = os.path.getmtime(db_path)
            except OSError:
                pass


def flush_db():
    """Flush the active portfolio's write cache to disk without closing."""
    _flush_path(active_db_path())


def flush_shared():
    """Flush the shared store's write cache to disk."""
    _flush_path(shared_db_path())


def close_db():
    """Flush and close every open database instance."""
    with _db_lock:
        for inst in list(_instances.values()):
            try:
                inst.close()
            except Exception:
                pass
        _instances.clear()
        _mtimes.clear()


atexit.register(close_db)


def install_shutdown_handler():
    """Flush+close all DBs on SIGTERM (e.g. `docker stop` on a bare-metal process).

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
