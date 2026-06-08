"""Database backup and restore utilities."""

import glob
import json
import os
import shutil
from datetime import datetime
from app.connection import get_db, close_db, flush_db, DB_PATH, get_table, HOLDINGS, DAILY_PRICES, IMPORTS, SETTINGS, YFINANCE_CACHE

# Dedicated directory for export backups and pre-import safety copies.
IMPORTS_DIR = os.path.join(os.path.dirname(DB_PATH), 'imports')

# Rolling on-startup backups. Lives under the persisted db/ volume so it survives
# container recreate.
BACKUPS_DIR = os.path.join(os.path.dirname(DB_PATH), 'backups')


def rotate_backup(keep=20, min_interval_seconds=600):
    """Snapshot db.json into db/backups/ and prune to the newest `keep` copies.

    Skips if the newest existing backup is younger than `min_interval_seconds`, so
    rapid successive CLI invocations don't churn the rotation. Idempotent and
    best-effort: never raises into startup. Returns the backup path (or None if
    skipped / nothing to back up / failed).
    """
    try:
        if not os.path.exists(DB_PATH):
            return None
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        existing = sorted(glob.glob(os.path.join(BACKUPS_DIR, 'db_*.json')))
        if existing and min_interval_seconds:
            import time
            if time.time() - os.path.getmtime(existing[-1]) < min_interval_seconds:
                return None
        flush_db()  # ensure cached writes are on disk before copying
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest = os.path.join(BACKUPS_DIR, f'db_{ts}.json')
        shutil.copy2(DB_PATH, dest)
        backups = sorted(glob.glob(os.path.join(BACKUPS_DIR, 'db_*.json')))
        for old in backups[:-keep]:
            try:
                os.remove(old)
            except OSError:
                pass
        return dest
    except Exception:
        return None

# Increment this when a new migration step is added.
SCHEMA_VERSION = 1

# Minimum tables that must exist for a valid TradeVault backup.
# TinyDB only creates a table entry once data is inserted, so not all tables
# are guaranteed to be present in every database.
REQUIRED_TABLES = {'holdings', 'transactions', 'settings'}


def export_db(output_path=None):
    """Flush cache and copy db.json to output_path. Returns the output path."""
    flush_db()
    if output_path is None:
        try:
            os.makedirs(IMPORTS_DIR, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                f'Cannot create exports directory {IMPORTS_DIR}: {e}. '
                'Check volume mount permissions or provide an explicit output path.'
            ) from e
        date_str = datetime.now().strftime('%Y-%m-%d')
        output_path = os.path.join(IMPORTS_DIR, f'db_backup_{date_str}.json')
    shutil.copy2(DB_PATH, output_path)
    return output_path


def validate_backup(path):
    """Validate a backup file. Returns (ok: bool, message: str)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, f'Invalid JSON: {e}'

    if not isinstance(data, dict):
        return False, 'Root must be a JSON object'

    found = set(data.keys()) - {'_default'}
    missing = REQUIRED_TABLES - found
    if missing:
        return False, f'Not a valid TradeVault backup — missing tables: {", ".join(sorted(missing))}'

    return True, 'OK'


def migrate_db():
    """Migrate the database to the current schema structure.

    Checks schema_version in settings first — skips all work if already
    up to date. Idempotent — safe to call on every startup.

    Migrations applied:
    1. yfinance_data (Fix 9): copy holding['yfinance_data'] into yfinance_cache
       table and strip the field from the holding record.
    2. sector/industry (Fix 6): remove always-null top-level fields from holdings.
    3. daily_prices cleanup (Fix 10): remove unrealized_pnl, unrealized_pnl_pct,
       holding_weight_pct from daily_price records.
    4. dividends table (Fix 8): drop the dividends table if it exists.
    5. ticker_map (Fix 3): remove ticker_map key from settings.
    6. imports.filepath (Fix 4): strip absolute paths down to basename.

    Returns a dict summarising what was changed.
    """
    from app.settings import get_setting, set_setting
    if get_setting('schema_version') == SCHEMA_VERSION:
        return {}  # already up to date

    summary = {}

    # ── 1. yfinance_data → yfinance_cache ────────────────────────────────────
    holdings_table = get_table(HOLDINGS)
    cache_table = get_table(YFINANCE_CACHE)
    from tinydb import Query
    C = Query()

    migrated_yf = 0
    for holding in holdings_table.all():
        yf_data = holding.get('yfinance_data')
        if yf_data:
            hid = holding.doc_id
            # Only write to cache if not already present
            if not cache_table.search(C.holding_id == hid):
                cache_table.insert({'holding_id': hid, **yf_data})
                migrated_yf += 1
            # Strip from holding record
            holdings_table.update(
                lambda r: r.pop('yfinance_data', None),
                doc_ids=[hid],
            )
    summary['yfinance_cache_migrated'] = migrated_yf

    # ── 2. Remove sector/industry from holdings ───────────────────────────────
    cleaned_holdings = 0
    for holding in holdings_table.all():
        if 'sector' in holding or 'industry' in holding:
            holdings_table.update(
                lambda r: (r.pop('sector', None), r.pop('industry', None)),
                doc_ids=[holding.doc_id],
            )
            cleaned_holdings += 1
    summary['holdings_fields_cleaned'] = cleaned_holdings

    # ── 3. Strip unused fields from daily_prices ─────────────────────────────
    dp_table = get_table(DAILY_PRICES)
    REMOVED_DP_FIELDS = ('unrealized_pnl', 'unrealized_pnl_pct', 'holding_weight_pct')
    cleaned_dp = 0
    for rec in dp_table.all():
        if any(f in rec for f in REMOVED_DP_FIELDS):
            dp_table.update(
                lambda r: [r.pop(f, None) for f in REMOVED_DP_FIELDS],
                doc_ids=[rec.doc_id],
            )
            cleaned_dp += 1
    summary['daily_prices_fields_cleaned'] = cleaned_dp

    # ── 4. Drop dividends table ───────────────────────────────────────────────
    db = get_db()
    if 'dividends' in db.tables():
        db.drop_table('dividends')
        summary['dividends_table_dropped'] = True
    else:
        summary['dividends_table_dropped'] = False

    # ── 5. Remove ticker_map from settings ────────────────────────────────────
    settings_table = get_table(SETTINGS)
    S = Query()
    removed_ticker_map = settings_table.remove(S.key == 'ticker_map')
    summary['ticker_map_removed'] = bool(removed_ticker_map)

    # ── 6. Strip absolute paths from imports.filepath ────────────────────────
    imports_table = get_table(IMPORTS)
    fixed_paths = 0
    for rec in imports_table.all():
        fp = rec.get('filepath', '')
        basename = os.path.basename(fp)
        if fp != basename:
            imports_table.update({'filepath': basename}, doc_ids=[rec.doc_id])
            fixed_paths += 1
    summary['import_paths_fixed'] = fixed_paths

    set_setting('schema_version', SCHEMA_VERSION)
    flush_db()
    return summary


def import_db(source_path):
    """Validate, replace, and migrate the database. Raises ValueError on bad input."""
    ok, msg = validate_backup(source_path)
    if not ok:
        raise ValueError(msg)

    # Backup current db before replacing
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = None
    if os.path.exists(DB_PATH):
        try:
            os.makedirs(IMPORTS_DIR, exist_ok=True)
            backup_path = os.path.join(IMPORTS_DIR, f'db.pre_import_{ts}.bak')
        except PermissionError:
            import tempfile
            backup_path = os.path.join(tempfile.gettempdir(), f'db.pre_import_{ts}.bak')
        shutil.copy2(DB_PATH, backup_path)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    close_db()
    shutil.copy2(source_path, DB_PATH)
    get_db()  # re-initialize singleton

    migration_summary = migrate_db()
    return backup_path, migration_summary
