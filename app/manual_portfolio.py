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


def refresh_prices_and_snapshot(date=None):
    """Price every open position from Yahoo Finance and write today's snapshot.

    Positions are derived from open tax lots (qty = Σ remaining_shares,
    cost = Σ total_cost per holding). Each is priced via the holding's ticker;
    on a missing ticker or a failed/empty fetch we fall back to the last known
    daily price, then to average cost. Returns a small summary dict.
    """
    from app.daily_prices import add_daily_price, get_latest_price
    from app.snapshots import generate_snapshot_from_prices
    from app.utils.translation_service import fetch_rich_info_from_yfinance
    from app.yfinance_cache import upsert_yfinance_cache
    from app.connection import flush_db

    data_date = date or _date.today().isoformat()

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
        ticker = holding.get('ticker')
        currency = holding.get('currency', 'ILS')

        price = None
        if ticker:
            info = fetch_rich_info_from_yfinance(ticker)
            if info and info.get('current_price'):
                price = float(info['current_price'])
                upsert_yfinance_cache(hid, info)
                priced += 1
        if price is None:
            last = get_latest_price(hid)
            if last and last.get('price'):
                price = float(last['price'])
            else:
                price = cost / qty if qty else 0
            stale += 1
        if price <= 0:
            continue

        rows.append({
            'holding_id': hid,
            'ticker': ticker or holding.get('tase_symbol') or str(hid),
            'date': data_date,
            'price': round(price, 4),
            'quantity': qty,
            'market_value': round(qty * price, 2),
            'cost_basis': round(cost, 2),
            'currency': currency,
        })

    for r in rows:
        add_daily_price(import_id=None, **r)
    if rows:
        generate_snapshot_from_prices(data_date, rows)
    flush_db()
    return {'date': data_date, 'positions': len(rows), 'priced': priced, 'stale': stale}
