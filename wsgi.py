"""WSGI entry point for production deployment with Gunicorn or uWSGI.

Usage:
    gunicorn --config gunicorn.conf.py wsgi:app

IMPORTANT — Single-worker requirement:
    TinyDB with CachingMiddleware keeps the entire database in a per-process
    in-memory dict and flushes to disk periodically.  Running more than one
    worker process means each worker has its own independent copy of the
    in-memory cache; writes in one worker are invisible to the others until a
    full flush + re-read cycle, which TinyDB does not perform automatically.

    Always set ``workers = 1`` (see gunicorn.conf.py).  If you need horizontal
    scaling, migrate the storage layer to SQLite or PostgreSQL first.
"""

from server import app, _run_startup

# Run one-time startup tasks (lib check, DB init, default settings).
# This runs in the master process before any worker is forked when
# ``preload_app = True`` is set in gunicorn.conf.py.
_run_startup()
