"""Position tracking and interpolation logic."""

from datetime import datetime, timedelta
from app.transactions import list_transactions, add_buy, add_sell
from app.tax_lots import create_lot, sell_fifo, get_open_lots
from app.holdings import get_holding, deactivate_holding


def has_nearby_trade(holding_id, date, action_type, days=2):
    """Check if a trade_import transaction exists near the given date.

    Args:
        holding_id: Holding ID to check
        date: ISO date string
        action_type: 'buy' or 'sell'
        days: Number of days before/after to search (default: 2)

    Returns:
        True if a trade_import transaction exists within the window
    """
    d = datetime.strptime(date, '%Y-%m-%d')
    start = (d - timedelta(days=days)).strftime('%Y-%m-%d')
    end = (d + timedelta(days=days)).strftime('%Y-%m-%d')
    txns = list_transactions(type_=action_type, start_date=start, end_date=end)
    for t in txns:
        if t.get('holding_id') == holding_id and t.get('source') == 'trade_import':
            return True
    return False


def interpolate_position_changes(data_date, today_prices):
    """Detect buys/sells by comparing today's holdings with previous day.

    Compares the holdings in today_prices with the previous trading day's
    holdings. New holdings are treated as buys, disappeared holdings as sells.
    Skips interpolation if a nearby trade_import transaction exists.

    Args:
        data_date: ISO date string for today
        today_prices: List of daily price records for today

    Returns:
        Tuple of (interpolated_buys: int, interpolated_sells: int)
    """
    from app.daily_prices import get_prices_by_date, list_dates

    # Find the most recent prior date
    all_dates = list_dates()
    prior_dates = [d for d in all_dates if d < data_date]
    if not prior_dates:
        return 0, 0

    prev_date = max(prior_dates)
    prev_prices = get_prices_by_date(prev_date)

    # Build maps: holding_id -> price record
    prev_map = {}
    for p in prev_prices:
        hid = p.get('holding_id')
        if hid:
            prev_map[hid] = p

    today_map = {}
    for p in today_prices:
        hid = p.get('holding_id')
        if hid:
            today_map[hid] = p

    prev_ids = set(prev_map.keys())
    today_ids = set(today_map.keys())

    new_ids = today_ids - prev_ids  # Potential buys (new positions)
    gone_ids = prev_ids - today_ids  # Potential sells (closed positions)
    common_ids = prev_ids & today_ids  # Existing positions (may have changed qty)

    interp_buys = 0
    interp_sells = 0

    # Handle new holdings (buys)
    for hid in new_ids:
        if has_nearby_trade(hid, data_date, 'buy'):
            continue
        p = today_map[hid]
        holding = get_holding(hid)
        if not holding:
            continue
        ticker = holding.get('ticker') or p.get('ticker', '')
        qty = p.get('quantity', 0)
        price = p.get('price', 0)
        if qty <= 0 or price <= 0:
            continue
        txn_id = add_buy(
            ticker=ticker,
            holding_id=hid,
            date=data_date,
            shares=qty,
            price_per_share=price,
            currency=p.get('currency', 'ILS'),
            source='interpolated',
        )
        create_lot(
            holding_id=hid,
            ticker=ticker,
            buy_transaction_id=txn_id,
            buy_date=data_date,
            buy_price=price,
            shares=qty,
            currency=p.get('currency', 'ILS'),
        )
        interp_buys += 1

    # Handle disappeared holdings (sells)
    for hid in gone_ids:
        if has_nearby_trade(hid, data_date, 'sell'):
            continue
        p = prev_map[hid]
        holding = get_holding(hid)
        if not holding:
            continue
        ticker = holding.get('ticker') or p.get('ticker', '')
        qty = p.get('quantity', 0)
        price = p.get('price', 0)
        if qty <= 0 or price <= 0:
            continue
        try:
            sell_details = sell_fifo(ticker, qty, price, data_date)
        except ValueError:
            continue
        add_sell(
            ticker=ticker,
            holding_id=hid,
            date=data_date,
            shares=qty,
            price_per_share=price,
            sell_lot_details=sell_details,
            currency=p.get('currency', 'ILS'),
            source='interpolated',
        )
        remaining = get_open_lots(ticker)
        if not remaining:
            deactivate_holding(hid, last_sold=data_date)
        interp_sells += 1

    # Handle quantity changes in existing holdings (deepened or reduced positions)
    for hid in common_ids:
        prev_qty = prev_map[hid].get('quantity', 0)
        today_qty = today_map[hid].get('quantity', 0)
        delta = today_qty - prev_qty
        if abs(delta) < 0.001:
            continue  # No meaningful change

        if delta > 0:
            # Deepened position — additional buy
            if has_nearby_trade(hid, data_date, 'buy'):
                continue
            p = today_map[hid]
            holding = get_holding(hid)
            if not holding:
                continue
            ticker = holding.get('ticker') or p.get('ticker', '')
            price = p.get('price', 0)
            if price <= 0:
                continue
            txn_id = add_buy(
                ticker=ticker,
                holding_id=hid,
                date=data_date,
                shares=delta,
                price_per_share=price,
                currency=p.get('currency', 'ILS'),
                source='interpolated',
            )
            create_lot(
                holding_id=hid,
                ticker=ticker,
                buy_transaction_id=txn_id,
                buy_date=data_date,
                buy_price=price,
                shares=delta,
                currency=p.get('currency', 'ILS'),
            )
            interp_buys += 1

        else:
            # Reduced position — partial sell
            if has_nearby_trade(hid, data_date, 'sell'):
                continue
            holding = get_holding(hid)
            if not holding:
                continue
            p = today_map[hid]
            ticker = holding.get('ticker') or p.get('ticker', '')
            shares_sold = abs(delta)
            price = p.get('price', 0)
            if price <= 0:
                continue
            try:
                sell_details = sell_fifo(ticker, shares_sold, price, data_date)
            except ValueError:
                continue
            add_sell(
                ticker=ticker,
                holding_id=hid,
                date=data_date,
                shares=shares_sold,
                price_per_share=price,
                sell_lot_details=sell_details,
                currency=p.get('currency', 'ILS'),
                source='interpolated',
            )
            # No deactivate_holding — holding still exists with reduced quantity
            interp_sells += 1

    return interp_buys, interp_sells
