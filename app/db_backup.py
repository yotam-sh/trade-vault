"""Database backup and restore utilities."""

import json
import os
import shutil
from datetime import datetime
from app.connection import get_db, close_db, flush_db, DB_PATH

# Minimum tables that must exist for a valid TradeVault backup.
# TinyDB only creates a table entry once data is inserted, so not all tables
# are guaranteed to be present in every database.
REQUIRED_TABLES = {'holdings', 'transactions', 'settings'}


def export_db(output_path=None):
    """Flush cache and copy db.json to output_path. Returns the output path."""
    flush_db()
    if output_path is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
        output_path = f'db_backup_{date_str}.json'
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


def import_db(source_path):
    """Validate and replace the database. Raises ValueError on bad input."""
    ok, msg = validate_backup(source_path)
    if not ok:
        raise ValueError(msg)

    # Backup current db before replacing
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = DB_PATH + f'.pre_import_{ts}.bak'
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, backup_path)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    close_db()
    shutil.copy2(source_path, DB_PATH)
    get_db()  # re-initialize singleton
    return backup_path
