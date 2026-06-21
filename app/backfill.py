"""Retroactive daily-history backfill for manual / non-TASE portfolios.

A daily-file (IBI) portfolio gets one snapshot per trading day from its imports.
A manual / US portfolio has no such feed, so its value-over-time series would be
sparse (a snapshot only when the user trades or refreshes). This module rebuilds
a dense daily history by reconstructing, for each manual holding:

  * a **quantity timeline** from its buy/sell transactions, and
  * a **FIFO cost-basis timeline** (an in-memory replay mirroring ``tax_lots``),

then pricing each US trading day at Yahoo's regular close (``get_yfinance_history``)
and writing one ``daily_prices`` row + one ``portfolio_snapshot`` per day through
the same idempotent path the importer uses (``generate_snapshot_from_prices``).

It is idempotent (re-running repairs/fills gaps) and never touches a daily-file
portfolio or a real-TASE holding — those get their history from imports.
"""

from datetime import date as _date

from app.holdings import list_holdings, SYNTHETIC_TASE_BASE
from app.transactions import list_transactions


def _is_backfillable(holding):
    """A holding we may fabricate history for: manual or synthetic (non-TASE)."""
    return bool(holding.get('manual')) or (holding.get('tase_id') or 0) >= SYNTHETIC_TASE_BASE


def _portfolio_has_daily_file():
    """True if the active portfolio has any daily-file import (then we refuse)."""
    from app.connection import get_table, IMPORTS
    from tinydb import Query
    I = Query()
    return bool(get_table(IMPORTS).search(I.import_type == 'daily_portfolio'))


def _holding_timeline(hid, close_dates):
    """Yield (date, qty, open_cost) for each trading date the holding was held.

    ``close_dates`` is the sorted list of trading dates (yfinance history). Trades
    are applied via an in-memory FIFO queue (same cost-per-share semantics as
    ``tax_lots.create_lot``/``sell_fifo``) so ``open_cost`` matches a FIFO rebuild.
    """
    trades = [t for t in list_transactions()
              if t.get('holding_id') == hid and t.get('type') in ('buy', 'sell')]
    trades.sort(key=lambda t: (t.get('date', ''), t.doc_id))
    if not trades:
        return

    first_trade = trades[0]['date'][:10]
    queue = []   # FIFO lots: [{'rem': shares, 'cps': cost_per_share}]
    ti = 0
    n = len(trades)

    for d in close_dates:
        if d < first_trade:
            continue
        # Apply every trade dated on or before this trading day.
        while ti < n and trades[ti]['date'][:10] <= d:
            t = trades[ti]
            shares = float(t.get('shares') or 0)
            price = float(t.get('price_per_share') or 0)
            if shares > 0:
                if t['type'] == 'buy':
                    commission = float(t.get('commission') or 0)
                    cps = price + (commission / shares if shares else 0)
                    queue.append({'rem': shares, 'cps': cps})
                else:  # sell — consume FIFO from the front
                    to_sell = shares
                    while to_sell > 1e-6 and queue:
                        lot = queue[0]
                        take = min(lot['rem'], to_sell)
                        lot['rem'] -= take
                        to_sell -= take
                        if lot['rem'] <= 1e-6:
                            queue.pop(0)
            ti += 1
        qty = sum(l['rem'] for l in queue)
        if qty > 1e-6:
            open_cost = sum(l['rem'] * l['cps'] for l in queue)
            yield d, qty, open_cost


def rebuild_daily_history(portfolio_id=None, end_date=None):
    """Rebuild dense daily snapshots for a manual / non-TASE portfolio.

    Runs in the active portfolio context, or wraps ``portfolio_id`` if given.
    Returns a summary dict. Refuses (``skipped='daily_file_portfolio'``) if the
    portfolio is fed by daily-file imports.
    """
    if portfolio_id is not None:
        from app.connection import using_portfolio
        with using_portfolio(portfolio_id):
            return _rebuild_active(end_date)
    return _rebuild_active(end_date)


def _rebuild_active(end_date=None):
    from app.utils.translation_service import get_yfinance_history, get_yfinance_mapping
    from app.daily_prices import add_daily_price
    from app.snapshots import generate_snapshot_from_prices
    from app.connection import flush_db

    if _portfolio_has_daily_file():
        return {'skipped': 'daily_file_portfolio', 'holdings': 0, 'dates': 0}

    end_date = end_date or _date.today().isoformat()

    rows_by_date = {}
    holdings_done = 0
    no_symbol = no_history = 0

    for holding in list_holdings(active_only=False):
        if not _is_backfillable(holding):
            continue
        hid = holding.doc_id
        symbol = get_yfinance_mapping(holding.get('tase_id')) or holding.get('ticker')
        if not symbol:
            no_symbol += 1
            continue
        # Network fetch happens here, outside any DB write/lock.
        hist = get_yfinance_history(symbol)
        if not hist:
            no_history += 1
            continue
        close_map = {h['date']: h['close'] for h in hist if h.get('close')}
        close_dates = sorted(d for d in close_map if d <= end_date)
        if not close_dates:
            no_history += 1
            continue

        ticker = holding.get('ticker') or symbol
        currency = holding.get('currency', 'ILS')
        emitted = False
        for d, qty, open_cost in _holding_timeline(hid, close_dates):
            close = close_map[d]
            rows_by_date.setdefault(d, []).append({
                'holding_id': hid,
                'ticker': ticker,
                'date': d,
                'price': round(float(close), 4),
                'quantity': qty,
                'market_value': round(qty * close, 2),
                'cost_basis': round(open_cost, 2),
                'currency': currency,
            })
            emitted = True
        if emitted:
            holdings_done += 1

    # Write through the shared idempotent path: per-date daily_prices + snapshot.
    dates = sorted(rows_by_date)
    for d in dates:
        rows = rows_by_date[d]
        for r in rows:
            add_daily_price(import_id=None, session='regular', **r)
        generate_snapshot_from_prices(d, rows)
    flush_db()

    return {
        'holdings': holdings_done,
        'dates': len(dates),
        'first_date': dates[0] if dates else None,
        'last_date': dates[-1] if dates else None,
        'no_symbol': no_symbol,
        'no_history': no_history,
    }


def _most_recent_us_trading_day():
    """The latest US trading day on or before today (ISO date string)."""
    from datetime import date, timedelta
    from app.utils.trading_calendar import is_us_non_trading_day
    d = date.today()
    for _ in range(10):
        if not is_us_non_trading_day(d.isoformat()):
            return d.isoformat()
        d -= timedelta(days=1)
    return d.isoformat()


def catch_up_all():
    """Fill the daily-snapshot gap for every manual/US portfolio (startup catch-up).

    For each non-daily-file portfolio whose latest snapshot lags the most recent
    US trading day, run the (idempotent) backfill to fill the missing days left
    while the container was down. Best-effort: a failing portfolio is skipped.
    """
    from app import portfolios
    from app.connection import using_portfolio
    from app.snapshots import get_latest_snapshot

    last_trading = _most_recent_us_trading_day()
    for entry in portfolios.list_portfolios():
        pid = entry['id']
        try:
            with using_portfolio(pid):
                if _portfolio_has_daily_file():
                    continue
                snap = get_latest_snapshot()
                latest = snap.get('date') if snap else None
                if latest is None or latest < last_trading:
                    _rebuild_active()
        except Exception:
            pass
