"""Web Maintenance page: TOTP setup/disable, reconcile, all without the CLI."""

import pyotp
import pytest

import server
from app import auth_store


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('TOTP_SECRET', raising=False)
    monkeypatch.setitem(server.app.config, 'WTF_CSRF_ENABLED', False)
    return server.app.test_client()


def test_totp_setup_flow_enables_login(client):
    begin = client.post('/maintenance/totp/begin').get_json()
    assert 'secret' in begin and '<svg' in begin['svg']

    code = pyotp.TOTP(begin['secret']).now()
    confirm = client.post('/maintenance/totp/confirm', data={'code': code})
    assert confirm.get_json()['ok'] is True
    assert auth_store.get_totp_secret() is not None

    # Gate is now active: a fresh (unauthenticated) client is redirected to login.
    fresh = server.app.test_client()
    assert fresh.get('/transactions').status_code == 302


def test_totp_confirm_rejects_bad_code(client):
    client.post('/maintenance/totp/begin')
    r = client.post('/maintenance/totp/confirm', data={'code': '000000'})
    assert r.status_code == 400 and r.get_json()['ok'] is False
    assert auth_store.get_totp_secret() is None


def test_disable_clears_secret(client):
    begin = client.post('/maintenance/totp/begin').get_json()
    client.post('/maintenance/totp/confirm', data={'code': pyotp.TOTP(begin['secret']).now()})
    assert auth_store.get_totp_secret() is not None
    client.post('/maintenance/totp/disable')
    assert auth_store.get_totp_secret() is None


def test_reconcile_endpoint_returns_issues(client):
    from app.connection import get_db, get_table, PORTFOLIO_SNAPSHOTS
    from app.settings import init_default_settings
    get_db(); init_default_settings()
    get_table(PORTFOLIO_SNAPSHOTS).insert({
        'date': '2026-03-03', 'total_market_value': 10000,
        'positions': [{'holding_id': 1, 'market_value': 5000, 'quantity': 5}],
        'cash_balance': 0, 'total_equity': 10000,
    })
    issues = client.post('/maintenance/reconcile').get_json()['issues']
    assert any('positions sum' in i['msg'] for i in issues)
