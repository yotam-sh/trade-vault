"""TOTP secret store.

The per-session login secret is managed from the web UI and persisted to a small
sidecar file next to db.json (NOT inside it), so it is never included in database
exports/backups (which copy only db.json). An environment variable TOTP_SECRET, if
set, always takes precedence (back-compat) and cannot be cleared from the web.
"""

import json
import os
import tempfile

from app import connection


def _auth_file():
    """Path to the sidecar, derived from the live DB path (follows test temp dirs)."""
    return os.path.join(os.path.dirname(connection.DB_PATH), 'auth.json')


def is_env_managed():
    """True when the secret comes from the TOTP_SECRET env var (web cannot change it)."""
    return bool(os.environ.get('TOTP_SECRET', '').strip())


def get_totp_secret():
    """Return the active TOTP secret, or None if login is not configured."""
    env = os.environ.get('TOTP_SECRET', '').strip()
    if env:
        return env
    try:
        with open(_auth_file(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        secret = (data or {}).get('totp_secret')
        return secret.strip() if isinstance(secret, str) and secret.strip() else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def set_totp_secret(secret):
    """Persist the TOTP secret to the sidecar file (atomic write)."""
    path = _auth_file()
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.auth-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'totp_secret': secret}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def clear_totp_secret():
    """Remove the sidecar secret (disable web-managed login).

    Returns False without changes if the secret is env-managed.
    """
    if is_env_managed():
        return False
    try:
        os.remove(_auth_file())
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True
