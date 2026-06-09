"""Shared pytest fixtures: every test runs against an isolated temp database."""

import pytest


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Point the DB at a unique temp db.json for each test.

    DB_PATH is the no-active-portfolio default, so with no portfolio context set the
    connection layer resolves to this temp file. The registry (portfolios.json) and
    shared store (shared.json) derive from its directory, so they're isolated too.
    """
    db_file = str(tmp_path / 'db.json')
    monkeypatch.setenv('DB_PATH', db_file)

    import app.connection as conn
    conn.close_db()
    monkeypatch.setattr(conn, 'DB_PATH', db_file)
    conn._instances.clear()
    conn._mtimes.clear()

    yield

    conn.close_db()
    conn._instances.clear()
    conn._mtimes.clear()
