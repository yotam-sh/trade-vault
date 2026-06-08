"""Charts that read the same data now pull it the same way (single source)."""

from app.connection import get_db
from app.settings import init_default_settings
from app.holdings import add_holding
from app.snapshots import create_snapshot
from app.analytics.portfolio_analytics import get_allocation_history
from app.analytics.daily_analytics import get_daily_type_chart_data, get_daily_summary


def _seed():
    get_db(); init_default_settings()
    s_id = add_holding(tase_id=1, tase_symbol='S', name_he='מניה', security_type='stock',
                       currency='ILS', ticker='S.TA')
    e_id = add_holding(tase_id=2, tase_symbol='E', name_he='סל', security_type='etf',
                       currency='ILS', ticker='E.TA')
    positions = [
        {'holding_id': s_id, 'ticker': 'S.TA', 'quantity': 10, 'market_value': 6000,
         'cost_basis': 5000, 'daily_pnl': 100, 'weight': 0},
        {'holding_id': e_id, 'ticker': 'E.TA', 'quantity': 20, 'market_value': 4000,
         'cost_basis': 4200, 'daily_pnl': -50, 'weight': 0},
    ]
    create_snapshot('2026-02-02', total_market_value=10000, total_cost_basis=9200,
                    total_daily_pnl=50, positions=positions,
                    total_deposits=8000, total_withdrawals=0)


def test_allocation_and_bytype_and_snapshot_totals_agree():
    _seed()
    alloc = get_allocation_history()[0]
    bytype = get_daily_type_chart_data()[0]

    # By-type total_value == snapshot market value == sum of allocation type bands.
    assert bytype['total_value'] == 10000
    assert alloc['stock'] + alloc['etf'] + alloc['mutual_fund'] + alloc['bond'] + alloc['other'] == 10000

    # Allocation value bands come from the same positions as the by-type change bands.
    assert alloc['stock'] == 6000 and alloc['etf'] == 4000
    assert bytype['stock'] == 100 and bytype['etf'] == -50


def test_daily_summary_change_pct_uses_canonical_basis():
    _seed()
    # First snapshot has no prior close -> morning = mv - pnl = 9950; pct = 50/9950.
    row = get_daily_summary()[0]
    assert row['morning_value'] == 9950
    assert row['change_pct'] == round(50 / 9950 * 100, 2)
