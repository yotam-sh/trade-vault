"""Portfolio registry & lifecycle.

Each portfolio is an isolated TinyDB file. A small JSON registry (db/portfolios.json)
lists them and records the default. The existing db/db.json becomes the first
portfolio automatically on first run, with zero data migration. File paths are stored
relative to the db/ directory so the registry survives volume/path changes.
"""

import json
import os
import re
import tempfile
import uuid
from datetime import datetime

from app import connection
from app.connection import using_portfolio, get_db, flush_db, forget_path


def _registry_path():
    return os.path.join(connection.db_dir(), 'portfolios.json')


def _default_entry():
    # The pre-existing db file becomes the first portfolio (relative name only).
    return {
        'id': 'default',
        'name': 'IBI',
        'file': os.path.basename(connection.DB_PATH),
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }


def _load():
    """Load the registry, bootstrapping it on first run."""
    path = _registry_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get('portfolios'):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    reg = {'default_id': 'default', 'portfolios': [_default_entry()]}
    _save(reg)
    return reg


def _save(reg):
    path = _registry_path()
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.portfolios-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def list_portfolios():
    """All portfolios as [{id, name, file, created_at}], default first-ish order kept."""
    return list(_load()['portfolios'])


def get_portfolio(pid):
    """The registry entry for `pid`, or None."""
    return next((p for p in _load()['portfolios'] if p['id'] == pid), None)


def default_id():
    """Id of the default portfolio (used when a session has no selection)."""
    return _load().get('default_id', 'default')


def exists(pid):
    return get_portfolio(pid) is not None


def set_default(pid):
    """Mark `pid` as the default portfolio. Returns True if it existed."""
    reg = _load()
    if not any(p['id'] == pid for p in reg['portfolios']):
        return False
    reg['default_id'] = pid
    _save(reg)
    return True


def portfolio_stats(pid):
    """Lightweight counts for the management table (read-only, no migrations)."""
    from app.connection import (
        using_portfolio, get_table, HOLDINGS, PORTFOLIO_SNAPSHOTS,
    )
    with using_portfolio(pid):
        holdings = len(get_table(HOLDINGS))
        snaps = get_table(PORTFOLIO_SNAPSHOTS)
        dates = [s.get('date') for s in snaps.all() if s.get('date')]
        return {
            'holdings': holdings,
            'snapshots': len(snaps),
            'last_date': max(dates) if dates else None,
        }


def portfolio_path(pid):
    """Absolute db-file path for `pid`, resolved against the db/ dir. None if unknown."""
    entry = get_portfolio(pid)
    if not entry:
        return None
    return os.path.join(connection.db_dir(), entry['file'])


def _slugify(name):
    slug = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-')
    return slug or 'portfolio'


def create_portfolio(name):
    """Create a new isolated portfolio and initialize its db. Returns the new id."""
    name = (name or '').strip() or 'Portfolio'
    pid = f'{_slugify(name)}-{uuid.uuid4().hex[:6]}'
    entry = {
        'id': pid,
        'name': name,
        'file': os.path.join('portfolios', f'{pid}.json').replace('\\', '/'),
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }
    reg = _load()
    reg['portfolios'].append(entry)
    _save(reg)

    # Initialize the fresh db (defaults + migrations) under the new portfolio context.
    from app.settings import init_default_settings
    with using_portfolio(pid):
        get_db()
        init_default_settings()
        flush_db()
    return pid


def rename_portfolio(pid, name):
    """Rename a portfolio. Returns True if it existed."""
    name = (name or '').strip()
    if not name:
        return False
    reg = _load()
    for p in reg['portfolios']:
        if p['id'] == pid:
            p['name'] = name
            _save(reg)
            return True
    return False


def delete_portfolio(pid):
    """Delete a portfolio's db file and registry entry.

    Refuses to delete the default portfolio or the last remaining one. Returns
    (ok, message).
    """
    reg = _load()
    if pid == reg.get('default_id'):
        return False, 'cannot delete the default portfolio'
    if len(reg['portfolios']) <= 1:
        return False, 'cannot delete the only portfolio'
    entry = next((p for p in reg['portfolios'] if p['id'] == pid), None)
    if not entry:
        return False, 'portfolio not found'

    path = os.path.join(connection.db_dir(), entry['file'])
    forget_path(path)  # release the file handle before removing
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        return False, f'could not remove db file: {e}'

    reg['portfolios'] = [p for p in reg['portfolios'] if p['id'] != pid]
    _save(reg)
    return True, 'deleted'
