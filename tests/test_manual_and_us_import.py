"""Phase 2 + 3: non-TASE holdings, manual trades, and the US (IBI Smart) CSV import."""

import pytest

from app.connection import get_db
from app.settings import init_default_settings
from app.holdings import add_holding, get_holding, get_holding_by_ticker, SYNTHETIC_TASE_BASE


# ── Phase 2: non-TASE holdings ────────────────────────────────────────────────

def test_add_holding_without_tase_id_gets_synthetic_id():
    get_db(); init_default_settings()
    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    h = get_holding(hid)
    assert h['tase_id'] >= SYNTHETIC_TASE_BASE     # synthetic, no collision with real TASE ids
    assert h['manual'] is True
    assert h['currency'] == 'USD'
    assert h['ticker'] == 'AAPL'

    # Dedup by ticker — same ticker returns the same holding, no duplicate.
    hid2 = add_holding(name_he='Apple Inc', ticker='AAPL', security_type='stock', currency='USD')
    assert hid2 == hid

    # A second synthetic holding gets a distinct id.
    hid3 = add_holding(name_he='Nvidia', ticker='NVDA', security_type='stock', currency='USD')
    assert get_holding(hid3)['tase_id'] > h['tase_id']


def test_real_tase_holding_unaffected():
    get_db(); init_default_settings()
    hid = add_holding(tase_id=629014, tase_symbol='טבע', name_he='טבע',
                      security_type='stock', currency='ILS')
    h = get_holding(hid)
    assert h['tase_id'] == 629014
    assert h['manual'] is False


# ── Phase 2: manual trades (FIFO + oversell guard) ────────────────────────────

def test_manual_trade_buy_then_sell_and_oversell_guard():
    get_db(); init_default_settings()
    from app.manual_portfolio import record_trade
    from app.tax_lots import get_all_lots

    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    record_trade(hid, 'buy', '2026-06-01', shares=10, price=100.0)
    record_trade(hid, 'buy', '2026-06-05', shares=10, price=120.0)

    open_shares = sum(l['remaining_shares'] for l in get_all_lots()
                      if l['holding_id'] == hid and not l['is_closed'])
    assert open_shares == 20

    # Partial sell consumes oldest lot first (FIFO).
    record_trade(hid, 'sell', '2026-06-10', shares=15, price=150.0)
    open_shares = sum(l['remaining_shares'] for l in get_all_lots()
                      if l['holding_id'] == hid and not l['is_closed'])
    assert open_shares == 5

    # Oversell is rejected (surfaced, not silently dropped).
    with pytest.raises(ValueError):
        record_trade(hid, 'sell', '2026-06-11', shares=99, price=150.0)


def test_add_position_is_visible_then_reduced_then_removed():
    get_db(); init_default_settings()
    from app.manual_portfolio import record_trade
    from app.snapshots import materialize_position_in_snapshot
    from app.analytics.portfolio_analytics import get_portfolio_value

    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')

    # Opening buy → materialize at entered price → visible immediately.
    record_trade(hid, 'buy', '2026-06-01', shares=10, price=150.0)
    materialize_position_in_snapshot(hid, 150.0)
    pf = get_portfolio_value()
    pos = next(p for p in pf['positions'] if p['holding_id'] == hid)
    assert pos['quantity'] == 10
    assert pos['market_value'] == 1500.0

    # Partial sell → position reduced.
    record_trade(hid, 'sell', '2026-06-05', shares=4, price=160.0)
    materialize_position_in_snapshot(hid, 160.0)
    pf = get_portfolio_value()
    pos = next(p for p in pf['positions'] if p['holding_id'] == hid)
    assert pos['quantity'] == 6
    assert pos['market_value'] == round(6 * 160.0, 2)

    # Closing sell → position removed from the snapshot.
    record_trade(hid, 'sell', '2026-06-10', shares=6, price=170.0)
    materialize_position_in_snapshot(hid, 170.0)
    pf = get_portfolio_value()
    assert all(p['holding_id'] != hid for p in (pf['positions'] if pf else []))


def test_record_trade_semantic_actions():
    get_db(); init_default_settings()
    from app.manual_portfolio import record_trade
    from app.tax_lots import get_all_lots

    def open_qty(hid):
        return sum(l['remaining_shares'] for l in get_all_lots()
                   if l['holding_id'] == hid and not l['is_closed'])

    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    record_trade(hid, 'increase', '2026-06-01', shares=10, price=100.0)
    record_trade(hid, 'increase', '2026-06-02', shares=5, price=110.0)
    assert open_qty(hid) == 15

    record_trade(hid, 'reduction', '2026-06-05', shares=4, price=120.0)
    assert open_qty(hid) == 11

    # Close sells the full open quantity regardless of the shares argument.
    record_trade(hid, 'close', '2026-06-10', shares=0, price=130.0)
    assert open_qty(hid) == 0

    # Closing again raises (nothing open).
    with pytest.raises(ValueError):
        record_trade(hid, 'close', '2026-06-11', shares=0, price=130.0)


def test_close_then_reopen_toggles_is_active():
    get_db(); init_default_settings()
    from app.manual_portfolio import record_trade
    from app.holdings import get_holding
    from app.tax_lots import get_all_lots

    def open_qty(hid):
        return sum(l['remaining_shares'] for l in get_all_lots()
                   if l['holding_id'] == hid and not l['is_closed'])

    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    record_trade(hid, 'increase', '2026-06-01', shares=10, price=100.0)
    assert get_holding(hid)['is_active'] is True

    record_trade(hid, 'close', '2026-06-02', shares=0, price=120.0)
    assert open_qty(hid) == 0
    assert get_holding(hid)['is_active'] is False   # closed → inactive

    # Reopen via Increase (what the closed-row Adjust button does).
    record_trade(hid, 'increase', '2026-06-03', shares=5, price=130.0)
    assert open_qty(hid) == 5
    assert get_holding(hid)['is_active'] is True     # reopened → active


def test_has_nearby_trade_suppresses_on_manual_source():
    get_db(); init_default_settings()
    from app.manual_portfolio import record_trade
    from app.importers.position_tracker import has_nearby_trade

    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    record_trade(hid, 'buy', '2026-06-10', shares=10, price=100.0)
    # A manual buy near the date must suppress interpolation (no duplicate twin).
    assert has_nearby_trade(hid, '2026-06-10', 'buy') is True


# ── Phase 3: US (IBI Smart) CSV import ────────────────────────────────────────

_US_CSV = (
    "undefined (2026-06-18)\n"
    "Symbol,Qty,Last Price,Change %,Bid,Bid Size,Ask,Ask Size,Mkt. Value,Total Cost,Unr. P/L %,Consensus\n"
    "ASTS,4,79.9,-6.47,79.85,1,80.05,59,319.6,312.34,2.32,Neutral\n"
    "AXTI,2,84.319,-8.45,84.25,1,84.32,173,168.64,163.2,3.33,Buy\n"
)


def test_us_csv_import(tmp_path):
    get_db(); init_default_settings()
    from app.importers.daily_importer import import_daily_portfolio
    from app.holdings import get_holding_by_ticker
    from app.snapshots import get_latest_snapshot

    csv = tmp_path / 'undefined_(2026-06-18).csv'
    csv.write_text(_US_CSV, encoding='utf-8')

    res = import_daily_portfolio(str(csv), force=True)
    assert res['status'] == 'success'
    assert res['rows_imported'] == 2
    assert res['format'] == 'us_csv'

    h = get_holding_by_ticker('ASTS')
    assert h is not None
    assert h['currency'] == 'USD'
    assert h['tase_id'] >= SYNTHETIC_TASE_BASE

    snap = get_latest_snapshot()
    assert snap['date'] == '2026-06-18'           # date parsed from the title line
    assert round(snap['total_market_value'], 2) == round(319.6 + 168.64, 2)

    # Re-importing the same bytes is a duplicate (no double snapshot).
    res2 = import_daily_portfolio(str(csv), force=True)
    assert res2['status'] == 'duplicate'
