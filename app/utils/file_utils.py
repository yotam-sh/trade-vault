"""File utilities for import operations."""

import hashlib
from app.imports import find_by_hash


def file_hash(filepath):
    """Compute SHA-256 hash of a file.

    Args:
        filepath: Path to file to hash

    Returns:
        Hex string of SHA-256 hash
    """
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def check_duplicate(filepath):
    """Check if a file has already been imported by its hash.

    Args:
        filepath: Path to file to check

    Returns:
        Tuple of (is_duplicate: bool, existing_import: dict or None, file_hash: str)

    Example:
        is_dup, existing, fhash = check_duplicate(filepath)
        if is_dup:
            print(f"File already imported on {existing['import_date']}")
            return {'status': 'duplicate'}
    """
    fhash = file_hash(filepath)
    existing = find_by_hash(fhash)
    is_duplicate = existing is not None
    return is_duplicate, existing, fhash
