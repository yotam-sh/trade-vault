"""Daily-history backfill, extended-hours sessions, US calendar and number locale."""

import pytest

from app.connection import get_db
from app.settings import init_default_settings
from app.holdings import add_holding, SYNTHETIC_TASE_BASE


# ── Extended-hours session schema + daily_prices dedup ────────────────────────

def test_session_schema_validation():
    from app.schemas import validate_record
    base = {'holding_id': 1, 'ticker': 'AAPL', 'date': '2026-06-18', 'price': 100.0,
            'quantity': 1, 'market_value': 100.0, 'cost_basis': 90.0, 'currency': 'USD',
            'import_id': 1, 'created_at': '2026-06-18T00:00:00'}
    ok, _ = validate_record('daily_prices', {**base, 'session': 'post'})
    assert ok
    ok, _ = validate_record('daily_prices', {**base, 'session': 'bogus'})
    assert not ok
    ok, _ = validate_record('daily_prices', base)  # missing session is fine
    assert ok


def test_daily_price_sessions_coexist_and_readers_are_regular_only():
    get_db(); init_default_settings()
    from app.daily_prices import add_daily_price, get_prices_by_date, get_latest_price

    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    add_daily_price(hid, 'AAPL', '2026-06-18', 100.0, 1, 100.0, 90.0, 'USD', None, session='regular')
    add_daily_price(hid, 'AAPL', '2026-06-18', 103.0, 1, 103.0, 90.0, 'USD', None, session='post')

    reg = get_prices_by_date('2026-06-18')                 # regular default
    assert len(reg) == 1 and reg[0]['price'] == 100.0
    post = get_prices_by_date('2026-06-18', session='post')
    assert len(post) == 1 and post[0]['price'] == 103.0
    assert get_latest_price(hid)['price'] == 100.0         # last-known is regular-only


def test_add_daily_price_backcompat_missing_session_treated_regular():
    get_db(); init_default_settings()
    from app.connection import get_table, DAILY_PRICES
    from app.daily_prices import add_daily_price, get_prices_by_date

    # A pre-extended-hours row has no 'session' field.
    get_table(DAILY_PRICES).insert({
        'holding_id': 5, 'ticker': 'X', 'date': '2026-06-18', 'price': 50.0,
        'quantity': 1, 'market_value': 50.0, 'cost_basis': 50.0, 'currency': 'USD',
        'import_id': None, 'created_at': '2026-06-18T00:00:00'})
    assert len(get_prices_by_date('2026-06-18')) == 1          # read as regular
    # A regular write dedups against the untagged row (updates in place).
    add_daily_price(5, 'X', '2026-06-18', 55.0, 1, 55.0, 50.0, 'USD', None, session='regular')
    rows = get_prices_by_date('2026-06-18')
    assert len(rows) == 1 and rows[0]['price'] == 55.0


def test_pick_session_price():
    from app.manual_portfolio import _pick_session_price
    assert _pick_session_price({'market_state': 'POST', 'post_price': 103, 'regular_price': 100}) == ('post', 103.0)
    assert _pick_session_price({'market_state': 'PRE', 'pre_price': 98, 'regular_price': 100}) == ('pre', 98.0)
    assert _pick_session_price({'market_state': 'REGULAR', 'regular_price': 100}) == ('regular', 100.0)
    assert _pick_session_price({'market_state': 'CLOSED', 'regular_price': 100}) == ('regular', 100.0)
    # marketState says POST but no post price → fall back to regular.
    assert _pick_session_price({'market_state': 'POST', 'regular_price': 100}) == ('regular', 100.0)
    assert _pick_session_price({}) == ('regular', None)


# ── Backfill ──────────────────────────────────────────────────────────────────

def _setup_aapl_with_trades():
    from app.manual_portfolio import record_trade
    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    record_trade(hid, 'buy', '2026-06-01', shares=10, price=100.0)   # Mon
    record_trade(hid, 'buy', '2026-06-03', shares=10, price=120.0)   # Wed
    record_trade(hid, 'sell', '2026-06-04', shares=5, price=130.0)   # Thu (FIFO from lot1)
    return hid


_CLOSES = {'2026-06-01': 100.0, '2026-06-02': 105.0, '2026-06-03': 110.0,
           '2026-06-04': 115.0, '2026-06-05': 120.0}


def _patch_history(monkeypatch):
    hist = [{'date': d, 'close': c, 'volume': 0} for d, c in sorted(_CLOSES.items())]
    monkeypatch.setattr('app.utils.translation_service.get_yfinance_history', lambda s: hist)


def _snap_on(date):
    from app.snapshots import list_snapshots
    return next((s for s in list_snapshots() if s['date'] == date), None)


def test_backfill_builds_dense_history_with_fifo_cost(monkeypatch):
    get_db(); init_default_settings()
    hid = _setup_aapl_with_trades()
    _patch_history(monkeypatch)

    from app.backfill import rebuild_daily_history
    summary = rebuild_daily_history(end_date='2026-06-05')
    assert summary['holdings'] == 1
    assert summary['dates'] == 5

    # 06-03: qty 20, FIFO open cost = 10*100 + 10*120 = 2200
    s3 = _snap_on('2026-06-03')
    assert round(s3['total_market_value'], 2) == round(20 * 110.0, 2)
    assert round(s3['total_cost_basis'], 2) == 2200.0

    # 06-05: after the FIFO sell of 5 from lot1 → qty 15, cost = 5*100 + 10*120 = 1700
    s5 = _snap_on('2026-06-05')
    assert round(s5['total_market_value'], 2) == round(15 * 120.0, 2)
    assert round(s5['total_cost_basis'], 2) == 1700.0

    # FIFO cost-basis matches the live tax-lots rebuild at the final date.
    from app.tax_lots import get_all_lots
    open_cost = sum(l['total_cost'] for l in get_all_lots()
                    if l['holding_id'] == hid and not l['is_closed'])
    assert round(open_cost, 2) == 1700.0


def test_backfill_is_idempotent(monkeypatch):
    get_db(); init_default_settings()
    _setup_aapl_with_trades()
    _patch_history(monkeypatch)
    from app.backfill import rebuild_daily_history

    rebuild_daily_history(end_date='2026-06-05')
    first = _snap_on('2026-06-05')['total_market_value']
    from app.snapshots import list_snapshots
    n1 = len([s for s in list_snapshots() if s['date'] in _CLOSES])

    rebuild_daily_history(end_date='2026-06-05')             # re-run
    n2 = len([s for s in list_snapshots() if s['date'] in _CLOSES])
    assert n1 == n2 == 5                                      # no duplicate snapshots
    assert _snap_on('2026-06-05')['total_market_value'] == first


def test_backfill_refuses_daily_file_portfolio(monkeypatch):
    get_db(); init_default_settings()
    _setup_aapl_with_trades()
    _patch_history(monkeypatch)
    from app.imports import create_import
    create_import('data.xlsx', 'data.xlsx', 'hash123', '2026-06-04',
                  'daily_portfolio', rows_imported=1)

    from app.backfill import rebuild_daily_history
    summary = rebuild_daily_history(end_date='2026-06-05')
    assert summary.get('skipped') == 'daily_file_portfolio'


def test_backfill_skips_real_tase_holding(monkeypatch):
    get_db(); init_default_settings()
    _patch_history(monkeypatch)
    # A real-TASE holding (not manual/synthetic) must never get fabricated history.
    from app.manual_portfolio import record_trade
    hid = add_holding(tase_id=629014, tase_symbol='TEVA', name_he='טבע',
                      security_type='stock', currency='ILS', ticker='TEVA.TA')
    record_trade(hid, 'buy', '2026-06-01', shares=10, price=100.0)

    from app.backfill import rebuild_daily_history
    summary = rebuild_daily_history(end_date='2026-06-05')
    assert summary['holdings'] == 0
    assert summary['dates'] == 0


# ── Gap-fill on price refresh ─────────────────────────────────────────────────

def _patch_live_price(monkeypatch, price=120.0):
    monkeypatch.setattr('app.utils.translation_service.fetch_rich_info_from_yfinance',
                        lambda t: {'market_state': 'REGULAR', 'regular_price': price,
                                   'current_price': price})


def test_refresh_backfills_missing_trading_days(monkeypatch):
    """A manual refresh fills missing trading days back to the first trade, skips weekends."""
    get_db(); init_default_settings()
    _setup_aapl_with_trades()
    _patch_history(monkeypatch)
    _patch_live_price(monkeypatch)

    from app.manual_portfolio import refresh_prices_and_snapshot
    res = refresh_prices_and_snapshot()

    assert res['backfilled'] == 5                    # the 5 trading days from history
    assert _snap_on('2026-06-03') is not None        # past weekday filled
    assert _snap_on('2026-06-05') is not None
    assert _snap_on('2026-06-06') is None            # Saturday never emitted
    assert _snap_on('2026-06-07') is None            # Sunday never emitted

    # Second refresh the same day: today's snapshot exists → no re-backfill.
    res2 = refresh_prices_and_snapshot()
    assert res2['backfilled'] == 0


def test_refresh_backfill_noop_for_daily_file_portfolio(monkeypatch):
    """Daily-file (TASE) portfolios get history from imports — refresh never fabricates it."""
    get_db(); init_default_settings()
    _setup_aapl_with_trades()
    _patch_history(monkeypatch)
    _patch_live_price(monkeypatch)
    from app.imports import create_import
    create_import('data.xlsx', 'data.xlsx', 'hash123', '2026-06-04',
                  'daily_portfolio', rows_imported=1)

    from app.manual_portfolio import refresh_prices_and_snapshot
    res = refresh_prices_and_snapshot()
    assert res['backfilled'] == 0
    assert _snap_on('2026-06-03') is None            # no fabricated history


# ── US trading calendar + number locale ───────────────────────────────────────

def test_us_trading_calendar():
    from app.utils.trading_calendar import is_us_non_trading_day
    assert is_us_non_trading_day('2026-06-20') is True       # Saturday
    assert is_us_non_trading_day('2026-06-21') is True       # Sunday
    assert is_us_non_trading_day('2026-01-01') is True       # New Year's Day (NYSE holiday)
    assert is_us_non_trading_day('2026-06-22') is False      # Monday, trading day


def test_number_locale():
    from app.currency import number_locale
    assert number_locale('ILS') == 'he-IL'
    assert number_locale('USD') == 'en-US'
    assert number_locale('EUR') == 'de-DE'
    assert number_locale('XYZ', 'he') == 'he-IL'             # unknown → UI lang
    assert number_locale('XYZ', 'en') == 'en-US'


# ── Audit remediation: hardening fixes ────────────────────────────────────────

def test_backfill_fifo_matches_tax_lots_with_fractional_shares(monkeypatch):
    """FIFO cost-basis replay (incl. commission) matches the live engine for fractional shares."""
    get_db(); init_default_settings()
    from app.manual_portfolio import record_trade
    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    record_trade(hid, 'buy', '2026-06-01', shares=10.5, price=100.0, commission=7.0)
    record_trade(hid, 'buy', '2026-06-03', shares=3.25, price=120.0, commission=3.0)
    record_trade(hid, 'sell', '2026-06-04', shares=5.0, price=130.0)
    _patch_history(monkeypatch)

    from app.backfill import rebuild_daily_history
    rebuild_daily_history(end_date='2026-06-05')

    from app.tax_lots import get_all_lots
    live_open_cost = sum(l['total_cost'] for l in get_all_lots()
                         if l['holding_id'] == hid and not l['is_closed'])
    last = _snap_on('2026-06-05')
    assert abs(last['total_cost_basis'] - round(live_open_cost, 2)) < 0.10


def test_prefer_session_regular_records_regular_not_post(monkeypatch):
    """Scheduler path (prefer_session='regular') records the regular close, not the post print."""
    get_db(); init_default_settings()
    from app.manual_portfolio import record_trade, refresh_prices_and_snapshot
    from app.daily_prices import get_price
    from datetime import date as _date

    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    record_trade(hid, 'buy', '2026-06-01', shares=10, price=100.0)

    # marketState POST with both prices present — regular close must win.
    monkeypatch.setattr('app.utils.translation_service.fetch_rich_info_from_yfinance',
                        lambda t: {'market_state': 'POST', 'regular_price': 150.0,
                                   'post_price': 175.0, 'current_price': 175.0})
    res = refresh_prices_and_snapshot(prefer_session='regular')
    assert res['session'] == 'regular'
    today = _date.today().isoformat()
    row = get_price(hid, today)            # regular session
    assert row is not None and row['price'] == 150.0   # not the 175.0 post print


def test_add_daily_price_update_preserves_import_id():
    get_db(); init_default_settings()
    from app.daily_prices import add_daily_price, get_price
    hid = add_holding(name_he='Apple', ticker='AAPL', security_type='stock', currency='USD')
    add_daily_price(hid, 'AAPL', '2026-06-18', 100.0, 1, 100.0, 90.0, 'USD', 5, session='regular')
    # A later session/refresh write with import_id=None must not wipe the audit link.
    add_daily_price(hid, 'AAPL', '2026-06-18', 101.0, 1, 101.0, 90.0, 'USD', None, session='regular')
    row = get_price(hid, '2026-06-18')
    assert row['price'] == 101.0 and row['import_id'] == 5
    # An explicit import_id still overwrites.
    add_daily_price(hid, 'AAPL', '2026-06-18', 102.0, 1, 102.0, 90.0, 'USD', 7, session='regular')
    assert get_price(hid, '2026-06-18')['import_id'] == 7
