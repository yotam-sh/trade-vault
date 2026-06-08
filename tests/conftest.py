"""Shared pytest fixtures: every test runs against an isolated temp database."""

import pytest


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Point the DB singleton at a unique temp db.json for each test.

    Patches the module-level DB_PATH in every module that captured it at import
    time, and resets the connection singleton before and after the test.
    """
    db_file = str(tmp_path / 'db.json')
    monkeypatch.setenv('DB_PATH', db_file)

    import app.connection as conn
    conn.close_db()
    monkeypatch.setattr(conn, 'DB_PATH', db_file)
    conn._db_instance = None
    conn._db_mtime = None

    import app.db_backup as dbk
    monkeypatch.setattr(dbk, 'DB_PATH', db_file, raising=False)
    monkeypatch.setattr(dbk, 'IMPORTS_DIR', str(tmp_path / 'imports'), raising=False)
    monkeypatch.setattr(dbk, 'BACKUPS_DIR', str(tmp_path / 'backups'), raising=False)

    yield

    conn.close_db()
    conn._db_instance = None
    conn._db_mtime = None
