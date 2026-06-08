"""Sidecar TOTP secret store: set/get/clear, env precedence, temp-dir path."""

import os

from app import auth_store, connection


def test_set_get_clear(monkeypatch):
    monkeypatch.delenv('TOTP_SECRET', raising=False)
    assert auth_store.get_totp_secret() is None
    auth_store.set_totp_secret('ABC123')
    assert auth_store.get_totp_secret() == 'ABC123'
    # the sidecar sits next to the (temp) DB, not inside db.json
    assert os.path.exists(os.path.join(os.path.dirname(connection.DB_PATH), 'auth.json'))
    assert auth_store.clear_totp_secret() is True
    assert auth_store.get_totp_secret() is None


def test_env_takes_precedence_and_blocks_clear(monkeypatch):
    monkeypatch.setenv('TOTP_SECRET', 'ENVSECRET')
    auth_store.set_totp_secret('FILESECRET')
    assert auth_store.get_totp_secret() == 'ENVSECRET'   # env wins
    assert auth_store.is_env_managed() is True
    assert auth_store.clear_totp_secret() is False        # can't clear env-managed
