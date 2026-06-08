"""Every table builder exposes the full name set from the same live holding."""

from app.connection import get_db
from app.settings import init_default_settings
from app.holdings import add_holding, update_holding
from app.snapshots import create_snapshot
from app.analytics.portfolio_analytics import get_portfolio_value
from app.analytics.position_analytics import get_positions_list


def _seed():
    get_db(); init_default_settings()
    hid = add_holding(tase_id=10, tase_symbol='נ', name_he='נקסטקום',
                      security_type='stock', currency='ILS', ticker='NXTM.TA')
    update_holding(hid, name_tase_en='NEXTCOM', name_tase_he='נקסטקום')
    create_snapshot('2026-02-02', total_market_value=5000, total_cost_basis=4000,
                    total_daily_pnl=0,
                    positions=[{'holding_id': hid, 'ticker': 'NXTM.TA', 'quantity': 10,
                                'market_value': 5000, 'cost_basis': 4000, 'daily_pnl': 0}],
                    total_deposits=4000, total_withdrawals=0)
    return hid


def test_open_positions_name_matches_holdings():
    hid = _seed()
    holdings_pos = {p['holding_id']: p for p in get_portfolio_value()['positions']}
    open_pos = {p['holding_id']: p for p in get_positions_list()['open']}
    assert hid in holdings_pos and hid in open_pos
    # The reported bug: Open Positions must carry the same TASE English name as Holdings.
    assert open_pos[hid]['name_tase_en'] == holdings_pos[hid]['name_tase_en'] == 'NEXTCOM'
    # Full display set present (no silent fallback for any pref).
    for field in ('name_tase_he', 'name_yf_long', 'name_yf_short', 'symbol_en'):
        assert field in open_pos[hid]
