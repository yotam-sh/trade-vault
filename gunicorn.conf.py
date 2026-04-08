# Gunicorn configuration for TradeVault
#
# Run with:   gunicorn --config gunicorn.conf.py wsgi:app
#
# ── IMPORTANT: single-worker constraint ──────────────────────────────────────
# TinyDB with CachingMiddleware is NOT safe for multi-process use.
# Each worker keeps the database in its own in-memory cache; concurrent writes
# from multiple workers will silently corrupt the JSON file.
# Keep workers = 1 until the storage layer is migrated to SQLite/PostgreSQL.
# ─────────────────────────────────────────────────────────────────────────────

bind = "0.0.0.0:2501"
workers = 1           # DO NOT increase — see note above
threads = 1           # single thread per worker; TinyDB is not thread-safe
timeout = 120         # generous timeout for slow admin operations
graceful_timeout = 30 # time allowed for in-flight requests to finish on SIGTERM
preload_app = True    # import server.py once in master; workers fork from that state
accesslog = "-"       # log to stdout
errorlog = "-"        # log to stdout
loglevel = "info"
