"""reconcile(): catches snapshot/equity inconsistencies."""

from app.connection import get_db, get_table, PORTFOLIO_SNAPSHOTS
from app.settings import init_default_settings
from app.holdings import add_holding
from app.snapshots import create_snapshot
from app.reconcile import reconcile


def test_clean_snapshot_has_no_errors():
    get_db(); init_default_settings()
    hid = add_holding(tase_id=1, tase_symbol='S', name_he='מניה', security_type='stock',
                      currency='ILS', ticker='S.TA')
    positions = [{'holding_id': hid, 'ticker': 'S.TA', 'quantity': 10,
                  'market_value': 5000, 'cost_basis': 4000, 'daily_pnl': 0, 'weight': 0}]
    create_snapshot('2026-03-02', total_market_value=5000, total_cost_basis=4000,
                    total_daily_pnl=0, positions=positions,
                    total_deposits=5000, total_withdrawals=0)
    errors = [i for i in reconcile() if i[0] == 'error']
    assert errors == []


def test_positions_sum_mismatch_is_error():
    get_db(); init_default_settings()
    # Raw insert with positions that don't sum to total_market_value.
    get_table(PORTFOLIO_SNAPSHOTS).insert({
        'date': '2026-03-03',
        'total_market_value': 10000,
        'positions': [{'holding_id': 1, 'market_value': 5000, 'quantity': 5}],
        'cash_balance': 0,
        'total_equity': 10000,
    })
    errors = [i for i in reconcile() if i[0] == 'error']
    assert any('positions sum' in msg for _sev, _date, msg in errors)


def test_equity_identity_mismatch_is_error():
    get_db(); init_default_settings()
    get_table(PORTFOLIO_SNAPSHOTS).insert({
        'date': '2026-03-04',
        'total_market_value': 8000,
        'positions': [{'holding_id': 1, 'market_value': 8000, 'quantity': 5}],
        'cash_balance': 100,
        'total_equity': 9999,   # should be 8100
    })
    errors = [i for i in reconcile() if i[0] == 'error']
    assert any('total_equity' in msg for _sev, _date, msg in errors)
