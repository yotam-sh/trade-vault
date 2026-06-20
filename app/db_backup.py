"""Database backup and restore utilities."""

import glob
import json
import os
import shutil
from datetime import datetime
from app.connection import (
    get_db, close_db, flush_db, forget_path, active_db_path, get_shared_table,
    get_table, HOLDINGS, DAILY_PRICES, IMPORTS, SETTINGS, YFINANCE_CACHE, CHART_CACHE,
)

# Export/backup directories live next to the *active* portfolio's db file, so each
# portfolio keeps its own imports/ and backups/.

def _imports_dir():
    return os.path.join(os.path.dirname(active_db_path()), 'imports')


def _backups_dir():
    return os.path.join(os.path.dirname(active_db_path()), 'backups')


def rotate_backup(keep=20, min_interval_seconds=600):
    """Snapshot db.json into db/backups/ and prune to the newest `keep` copies.

    Skips if the newest existing backup is younger than `min_interval_seconds`, so
    rapid successive CLI invocations don't churn the rotation. Idempotent and
    best-effort: never raises into startup. Returns the backup path (or None if
    skipped / nothing to back up / failed).
    """
    try:
        db_path = active_db_path()
        backups_dir = _backups_dir()
        if not os.path.exists(db_path):
            return None
        os.makedirs(backups_dir, exist_ok=True)
        existing = sorted(glob.glob(os.path.join(backups_dir, 'db_*.json')))
        if existing and min_interval_seconds:
            import time
            if time.time() - os.path.getmtime(existing[-1]) < min_interval_seconds:
                return None
        flush_db()  # ensure cached writes are on disk before copying
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest = os.path.join(backups_dir, f'db_{ts}.json')
        shutil.copy2(db_path, dest)
        backups = sorted(glob.glob(os.path.join(backups_dir, 'db_*.json')))
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
    """Flush cache and copy the active portfolio's db to output_path."""
    flush_db()
    imports_dir = _imports_dir()
    if output_path is None:
        try:
            os.makedirs(imports_dir, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                f'Cannot create exports directory {imports_dir}: {e}. '
                'Check volume mount permissions or provide an explicit output path.'
            ) from e
        date_str = datetime.now().strftime('%Y-%m-%d')
        output_path = os.path.join(imports_dir, f'db_backup_{date_str}.json')
    shutil.copy2(active_db_path(), output_path)
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

    # Record-level validation: every record in each known table must pass its schema
    # before we overwrite the live DB. Tables without a schema are skipped.
    from app.schemas import validate_record, SCHEMAS
    invalid = 0
    first_errors = []
    for table_name, records in data.items():
        if table_name == '_default' or table_name not in SCHEMAS:
            continue
        if not isinstance(records, dict):
            return False, f"Table '{table_name}' must be an object of records"
        for doc_id, record in records.items():
            if not isinstance(record, dict):
                invalid += 1
                continue
            ok_rec, errs = validate_record(table_name, record)
            if not ok_rec:
                invalid += 1
                if len(first_errors) < 3:
                    first_errors.append(f"{table_name}[{doc_id}]: {errs[0]}")

    if invalid:
        detail = '; '.join(first_errors)
        return False, f'Backup has {invalid} invalid record(s). Examples — {detail}'

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
    cache_table = get_table(YFINANCE_CACHE)  # yfinance cache is per-portfolio
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

    # Drop the derived chart cache — it is regenerated on demand and must not be
    # carried across a restore (its stored version may not match the restored data).
    if CHART_CACHE in db.tables():
        db.drop_table(CHART_CACHE)

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


def migrate_shared_yfinance_to_portfolios():
    """One-time: relocate the formerly-shared yfinance cache + map into the default portfolio.

    Earlier builds stored ``yfinance_cache`` (keyed by per-portfolio ``holding_id``) and the
    ``yfinance_map`` setting in the SHARED store, which collides across portfolios. Both are
    now per-portfolio; this moves the existing shared data into the default portfolio (whose
    data it historically is) and clears the shared copies. Idempotent (guarded by a flag).
    """
    from app.connection import get_shared_table, using_portfolio, get_table, flush_db, flush_shared, YFINANCE_CACHE
    from app.settings import get_shared_setting, set_shared_setting, get_setting, set_setting
    from app import portfolios
    from tinydb import Query

    if get_shared_setting('yfinance_migrated_to_portfolio'):
        return

    shared_cache = get_shared_table(YFINANCE_CACHE)
    cache_rows = [dict(r) for r in shared_cache.all()]
    shared_map = get_shared_setting('yfinance_map', {}) or {}

    if cache_rows or shared_map:
        with using_portfolio(portfolios.default_id()):
            if cache_rows:
                ct = get_table(YFINANCE_CACHE)
                C = Query()
                for row in cache_rows:
                    hid = row.get('holding_id')
                    if ct.search(C.holding_id == hid):
                        ct.update(row, C.holding_id == hid)
                    else:
                        ct.insert(row)
            if shared_map:
                merged = get_setting('yfinance_map', {}) or {}
                merged.update(shared_map)
                set_setting('yfinance_map', merged)
            flush_db()
        shared_cache.truncate()
        if shared_map:
            set_shared_setting('yfinance_map', {})
        flush_shared()

    set_shared_setting('yfinance_migrated_to_portfolio', True)


def import_db(source_path):
    """Validate, replace, and migrate the database. Raises ValueError on bad input."""
    ok, msg = validate_backup(source_path)
    if not ok:
        raise ValueError(msg)

    db_path = active_db_path()
    imports_dir = _imports_dir()

    # Backup current db before replacing
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = None
    if os.path.exists(db_path):
        try:
            os.makedirs(imports_dir, exist_ok=True)
            backup_path = os.path.join(imports_dir, f'db.pre_import_{ts}.bak')
        except PermissionError:
            import tempfile
            backup_path = os.path.join(tempfile.gettempdir(), f'db.pre_import_{ts}.bak')
        shutil.copy2(db_path, backup_path)

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    forget_path(db_path)  # release the active portfolio's file handle
    shutil.copy2(source_path, db_path)
    get_db()  # re-open the active portfolio from the restored file

    migration_summary = migrate_db()
    return backup_path, migration_summary
