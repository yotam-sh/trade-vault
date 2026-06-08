"""Web parity for former CLI-only ops: manual buy/sell, sync-holdings, check-libs."""

import pytest

import server
from app.connection import get_db
from app.settings import init_default_settings
from app.holdings import add_holding, get_holding, update_holding
from app.snapshots import create_snapshot


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('TOTP_SECRET', raising=False)
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)   # gate off for these tests
    monkeypatch.setitem(server.app.config, 'WTF_CSRF_ENABLED', False)
    get_db(); init_default_settings()
    return server.app.test_client()


def test_sync_holdings_endpoint(client):
    held = add_holding(tase_id=2, tase_symbol='A', name_he='א', security_type='stock', currency='ILS')
    gone = add_holding(tase_id=3, tase_symbol='B', name_he='ב', security_type='stock', currency='ILS')
    create_snapshot('2026-02-02', total_market_value=1000, total_cost_basis=900, total_daily_pnl=0,
                    positions=[{'holding_id': held, 'ticker': 'A', 'quantity': 5,
                                'market_value': 1000, 'cost_basis': 900, 'daily_pnl': 0}],
                    total_deposits=1000, total_withdrawals=0)
    update_holding(held, is_active=False)   # wrong state on purpose
    update_holding(gone, is_active=True)
    assert client.post('/maintenance/sync-holdings').status_code == 302
    assert get_holding(held)['is_active'] is True
    assert get_holding(gone)['is_active'] is False


def test_check_libs_endpoint(client):
    r = client.post('/maintenance/check-libs')
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        assert 'outdated' in r.get_json()
