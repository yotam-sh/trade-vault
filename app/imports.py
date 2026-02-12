"""Import audit trail CRUD."""

from tinydb import Query
from app.connection import get_table, IMPORTS
from app.schemas import now_iso, validate_record


def create_import(filename, filepath, file_hash, data_date, import_type,
                  rows_imported=0, **kwargs):
    """Create an import audit record. Returns doc_id."""
    table = get_table(IMPORTS)
    now = now_iso()
    record = {
        'filename': filename,
        'filepath': filepath,
        'file_hash': file_hash,
        'import_date': now,
        'data_date': data_date,
        'status': kwargs.get('status', 'success'),
        'rows_imported': rows_imported,
        'rows_skipped': kwargs.get('rows_skipped', 0),
        'new_holdings': kwargs.get('new_holdings', 0),
        'errors': kwargs.get('errors', []),
        'securities': kwargs.get('securities', []),
        'import_type': import_type,
        'created_at': now,
    }

    valid, errors = validate_record('imports', record)
    if not valid:
        raise ValueError(f"Invalid import record: {errors}")

    return table.insert(record)


def find_by_hash(file_hash):
    """Check if a file has already been imported by its SHA-256 hash."""
    table = get_table(IMPORTS)
    I = Query()
    results = table.search(I.file_hash == file_hash)
    return results[0] if results else None


