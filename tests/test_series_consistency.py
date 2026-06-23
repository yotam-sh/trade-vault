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


def test_overview_holdings_carry_raw_name_fields():
    """get_overview holdings must keep the raw enriched name/symbol fields so templates
    can honor display_prefs (the per-context name-source preference)."""
    _seed()
    from app.analytics.portfolio_analytics import get_overview
    h = get_overview('he')['holdings'][0]
    for k in ('name_he', 'name_en', 'name_tase_he', 'name_tase_en', 'symbol', 'symbol_en', 'ticker', 'security_type'):
        assert k in h, f'missing raw field {k}'


def test_overview_total_equity_includes_idle_cash():
    """Portfolio Value (total_equity) = positions market value + idle cash."""
    _seed()
    from app.analytics.portfolio_analytics import get_overview
    ov = get_overview('he')
    assert round(ov['total_equity'], 2) == round(ov['portfolio']['total_value'] + ov['idle_cash'], 2)


def test_total_return_includes_idle_cash():
    """Total Return ('cost change') compares equity (positions + idle cash) to net
    invested, so uninvested cash isn't counted as a loss."""
    get_db(); init_default_settings()
    from app.transactions import add_deposit
    from app.manual_portfolio import record_trade
    from app.snapshots import materialize_position_in_snapshot
    from app.analytics.portfolio_analytics import get_portfolio_value

    hid = add_holding(name_he='S', ticker='S', security_type='stock', currency='USD')
    add_deposit('2026-02-01', 1000, currency='USD')
    record_trade(hid, 'buy', '2026-02-02', shares=10, price=60)   # spends 600 → 400 cash idle
    materialize_position_in_snapshot(hid, 59.0)                   # positions now worth 590

    pv = get_portfolio_value()
    assert round(pv['total_cost'], 2) == 1000.0                  # net invested
    # equity (590 + 400 cash) − 1000 = −10, NOT market_value − net_invested (590 − 1000 = −410).
    assert round(pv['unrealized_pnl'], 2) == -10.0


def test_daily_pnl_derived_when_snapshot_pnl_zero():
    """Manual/US snapshots store total_daily_pnl=0; the daily change is derived from the
    change in total return Δ(equity − net_invested) instead of reading a flat 0."""
    get_db(); init_default_settings()
    from app.transactions import add_deposit
    from app.manual_portfolio import record_trade
    from app.snapshots import materialize_position_in_snapshot
    from app.analytics.series import daily_changes

    hid = add_holding(name_he='S', ticker='S', security_type='stock', currency='USD')
    add_deposit('2026-06-17', 1000, currency='USD')
    record_trade(hid, 'buy', '2026-06-17', shares=10, price=60)
    materialize_position_in_snapshot(hid, 60.0, date='2026-06-17')   # equity 1000, return 0
    materialize_position_in_snapshot(hid, 59.0, date='2026-06-18')   # equity 990, return −10

    dc = daily_changes()
    assert dc['2026-06-17']['daily_pnl'] == 0                        # first day, no prior
    assert dc['2026-06-18']['daily_pnl'] == -10.0                    # derived, not 0


def test_daily_summary_excludes_non_trading_days():
    """A snapshot landing on a non-trading day (e.g. a Saturday manual refresh) must not
    appear as a daily-summary row."""
    _seed()  # 2026-02-02 (Monday)
    create_snapshot('2026-02-07', total_market_value=10000, total_cost_basis=9200,
                    total_daily_pnl=0, positions=[], total_deposits=8000, total_withdrawals=0)
    dates = [r['date'] for r in get_daily_summary()]
    assert '2026-02-02' in dates
    assert '2026-02-07' not in dates                                 # Saturday filtered
