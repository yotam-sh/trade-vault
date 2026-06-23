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


def test_phantom_open_lot_not_in_snapshot_is_warned():
    """A holding with open lots but absent from the latest snapshot (closed but its lots
    were never closed) is surfaced as a 'phantom' warning."""
    get_db(); init_default_settings()
    from app.tax_lots import create_lot
    hid = add_holding(tase_id=7, tase_symbol='X', name_he='מניה', security_type='stock',
                      currency='ILS', ticker='X.TA')
    # Latest snapshot holds nothing for this holding...
    create_snapshot('2026-03-05', total_market_value=0, total_cost_basis=0,
                    total_daily_pnl=0, positions=[], total_deposits=0, total_withdrawals=0)
    # ...but an open lot lingers.
    create_lot(holding_id=hid, ticker='X.TA', buy_transaction_id=None,
               buy_date='2026-03-01', buy_price=100.0, shares=10, currency='ILS')
    warns = [msg for sev, _date, msg in reconcile() if sev == 'warn']
    assert any('phantom' in msg and f'holding {hid}' in msg for msg in warns)
