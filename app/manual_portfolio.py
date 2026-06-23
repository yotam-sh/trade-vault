"""Manual portfolio tracking — record trades by hand and price positions from Yahoo.

For portfolios with no daily-file source (e.g. a manually-tracked or non-TASE book).
Trades go through the same ledger/FIFO engine as imports; current value is derived
from open tax lots priced via Yahoo Finance, written as a daily snapshot.
"""

from datetime import date as _date

from app.holdings import get_holding
from app.transactions import add_buy, add_sell
from app.tax_lots import get_all_lots
from app.recompute import recompute_after_trade_change


def _open_qty_for(holding_id):
    """Total open (un-closed) lot shares currently held for a holding."""
    return sum((l.get('remaining_shares') or 0) for l in get_all_lots()
               if l.get('holding_id') == holding_id and not l.get('is_closed'))


def record_trade(holding_id, action, date, shares, price, commission=0):
    """Record a manual buy/sell, then rebuild lots/P&L/cash. Returns the txn id.

    Raises ValueError on bad input or an oversell (insufficient open lots) — the
    caller surfaces it to the user rather than silently dropping the trade.
    """
    holding = get_holding(holding_id)
    if not holding:
        raise ValueError('holding not found')
    # Semantic actions from the position page map onto buy/sell:
    #   increase → buy | reduction → sell (entered shares) | close → sell ALL open shares
    action = (action or '').lower()
    if action in ('increase', 'buy'):
        action = 'buy'
    elif action in ('reduction', 'sell'):
        action = 'sell'
    elif action == 'close':
        action = 'sell'
        shares = _open_qty_for(holding_id)  # server fills the full quantity
        if shares <= 0:
            raise ValueError('nothing to close: no open shares')
    else:
        raise ValueError('action must be increase, reduction or close')
    shares = float(shares)
    price = float(price)
    if shares <= 0 or price <= 0:
        raise ValueError('shares and price must be positive')

    ticker = holding.get('ticker') or holding.get('tase_symbol') or str(holding_id)
    currency = holding.get('currency', 'ILS')
    commission = float(commission or 0)

    if action == 'sell':
        available = _open_qty_for(holding_id)
        if available + 1e-6 < shares:
            raise ValueError(
                f'insufficient shares to sell: holding has {available:g}, tried to sell {shares:g}'
            )
        txn_id = add_sell(ticker=ticker, holding_id=holding_id, date=date, shares=shares,
                          price_per_share=price, currency=currency, source='manual',
                          commission=commission)
    else:
        txn_id = add_buy(ticker=ticker, holding_id=holding_id, date=date, shares=shares,
                         price_per_share=price, currency=currency, source='manual',
                         commission=commission)

    # Authoritative recompute: FIFO-replay lots from the ledger (fills sell_lot_details,
    # realized P&L) and refresh snapshot cash/equity. Flushes to disk.
    recompute_after_trade_change()

    # Keep is_active in step with reality: a buy/reopen reactivates, a closing sell
    # (no open shares left) deactivates.
    from app.holdings import update_holding
    is_active = _open_qty_for(holding_id) > 0
    if holding.get('is_active') != is_active:
        update_holding(holding_id, is_active=is_active)
    return txn_id


def _pick_session_price(info):
    """Choose (session, price) from a yfinance info dict using ``market_state``.

    The latest available session wins (post → regular → pre); a missing field for
    the active session falls back to the next available one, then to current_price.
    Returns (session, price) or ('regular', None) when nothing usable is present.
    """
    state = (info.get('market_state') or '').upper()
    pre = info.get('pre_price')
    reg = info.get('regular_price') or info.get('current_price')
    post = info.get('post_price')
    if state in ('POST', 'POSTPOST') and post:
        return 'post', float(post)
    if state == 'PRE' and pre:
        return 'pre', float(pre)
    if reg:
        return 'regular', float(reg)
    # marketState-preferred field missing → take whatever session has a price.
    for s, p in (('post', post), ('regular', reg), ('pre', pre)):
        if p:
            return s, float(p)
    cp = info.get('current_price')
    return ('regular', float(cp)) if cp else ('regular', None)


def refresh_prices_and_snapshot(date=None, prefer_session=None):
    """Price every open position from Yahoo Finance and write today's snapshot.

    Positions are derived from open tax lots (qty = Σ remaining_shares,
    cost = Σ total_cost per holding). Each is priced via the holding's ticker;
    on a missing ticker or a failed/empty fetch we fall back to the last known
    daily price, then to average cost.

    Extended hours (Phase 4): each row is tagged with the session it was priced
    in (``pre`` / ``regular`` / ``post``) and the current-day snapshot reflects
    the latest available session. Pass ``prefer_session='regular'`` to force the
    regular close regardless of ``marketState`` (used by the scheduled close job,
    which runs after-hours but must record the regular close for history).
    Returns a small summary dict.
    """
    from app.daily_prices import add_daily_price, get_latest_price
    from app.snapshots import generate_snapshot_from_prices
    from app.utils.translation_service import fetch_rich_info_from_yfinance
    from app.yfinance_cache import upsert_yfinance_cache
    from app.settings import set_setting
    from app.connection import flush_db
    from app.backfill import backfill_active_gaps

    data_date = date or _date.today().isoformat()

    # Fill any missing trading days (e.g. a skipped refresh) back to the first trade
    # before writing today's live snapshot. No-op + no network when there is no gap.
    gap = backfill_active_gaps()

    # Aggregate open lots → {holding_id: [qty, cost]}
    agg = {}
    for lot in get_all_lots():
        if lot.get('is_closed'):
            continue
        rem = lot.get('remaining_shares') or 0
        if rem <= 0:
            continue
        a = agg.setdefault(lot.get('holding_id'), [0.0, 0.0])
        a[0] += rem
        a[1] += lot.get('total_cost') or 0

    rows = []
    priced = stale = 0
    for hid, (qty, cost) in agg.items():
        holding = get_holding(hid)
        if not holding or qty <= 0:
            continue
        # Never resurrect a closed position from a lingering open lot. is_active is the
        # authoritative "currently held" flag for both portfolio kinds (manual trades keep
        # it in step; daily imports set it from the file). A holding the broker/file shows
        # as closed must stay out of today's snapshot even if a stale lot remains.
        if holding.get('is_active') is False:
            continue
        ticker = holding.get('ticker')
        currency = holding.get('currency', 'ILS')

        session = 'regular'
        price = None
        if ticker:
            info = fetch_rich_info_from_yfinance(ticker)
            if info:
                upsert_yfinance_cache(hid, info)
                if prefer_session == 'regular':
                    # Record the true regular close only. Do NOT fall back to
                    # current_price here — at the scheduler's after-hours run time
                    # that would be the post-market print. If regular_price is
                    # missing, fall through to the last-known regular daily price.
                    p = info.get('regular_price')
                    price = float(p) if p else None
                else:
                    session, price = _pick_session_price(info)
                if price:
                    priced += 1
        if price is None:
            last = get_latest_price(hid)  # regular-session last known
            if last and last.get('price'):
                price = float(last['price'])
            else:
                price = cost / qty if qty else 0
            session = 'regular'
            stale += 1
        if price <= 0:
            continue

        rows.append({
            'holding_id': hid,
            'ticker': ticker or holding.get('tase_symbol') or str(hid),
            'date': data_date,
            'price': round(price, 4),
            'session': session,
            'quantity': qty,
            'market_value': round(qty * price, 2),
            'cost_basis': round(cost, 2),
            'currency': currency,
        })

    for r in rows:
        add_daily_price(import_id=None, **r)
    if rows:
        generate_snapshot_from_prices(data_date, rows)

    # Record which session the current value reflects, for the dashboard badge.
    # The latest non-regular session wins (post outranks pre).
    sessions = {r['session'] for r in rows}
    portfolio_session = 'post' if 'post' in sessions else ('pre' if 'pre' in sessions else 'regular')
    set_setting('market_session', {'session': portfolio_session, 'date': data_date})

    flush_db()
    return {'date': data_date, 'positions': len(rows), 'priced': priced,
            'stale': stale, 'session': portfolio_session,
            'backfilled': gap.get('filled', 0)}
