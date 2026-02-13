"""Trade analytics - trade history and closed positions."""

from app.holdings import get_holding
from app.transactions import list_transactions
from app.analytics.daily_analytics import get_daily_details


def get_trade_history(start_date=None, end_date=None):
    """Get all buy/sell transactions enriched with holding names and P&L.

    Returns list of trade records sorted by date.
    """
    all_txns = list_transactions(start_date=start_date, end_date=end_date)

    # Separate buys/sells and sort by date for position-type detection
    buy_sell_txns = [t for t in all_txns if t['type'] in ('buy', 'sell')]
    buy_sell_txns.sort(key=lambda t: (t['date'], t.doc_id))

    # Track running share balance per holding to determine position type
    positions = {}  # holding_id -> running share count

    trades = []
    for txn in buy_sell_txns:
        hid = txn.get('holding_id')
        holding = get_holding(hid) if hid else None
        shares = txn.get('shares', 0) or 0

        realized_pnl = 0
        if txn.get('sell_lot_details'):
            realized_pnl = sum(d.get('realized_pnl', 0) for d in txn['sell_lot_details'])

        # Determine position type from running balance
        current_shares = positions.get(hid, 0)

        if txn['type'] == 'buy':
            if current_shares <= 0:
                position_type = 'פתיחה'
            else:
                position_type = 'הגדלה'
            positions[hid] = current_shares + shares
        else:  # sell
            remaining = current_shares - shares
            positions[hid] = remaining
            if remaining <= 0.0001:
                position_type = 'סגירה'
                positions[hid] = 0
            else:
                position_type = 'צמצום'

        trades.append({
            'id': txn.doc_id,
            'date': txn['date'],
            'type': txn['type'],
            'ticker': txn.get('ticker', ''),
            'name_he': holding['name_he'] if holding else txn.get('ticker', ''),
            'symbol': holding['tase_symbol'] if holding else '',
            'shares': shares,
            'price_per_share': txn.get('price_per_share', 0),
            'total_amount': txn.get('total_amount', 0),
            'currency': txn.get('currency', 'ILS'),
            'realized_pnl': realized_pnl,
            'position_type': position_type,
            'holding_id': hid,
        })

    return trades


def get_closed_positions():
    """Get summary of fully closed positions with realized P&L.

    Derived from trade transactions (buy/sell) to stay consistent with the
    trade history view.  Uses sell_lot_details for P&L when available,
    otherwise computes from buy/sell amounts.

    Returns list of closed position summaries.
    """
    trades = get_trade_history()

    # Group trades by holding_id
    by_holding = {}
    for t in trades:
        hid = t.get('holding_id')
        if hid:
            by_holding.setdefault(hid, []).append(t)

    closed = []
    for hid, htrades in by_holding.items():
        # Compute final share balance
        balance = 0
        for t in htrades:
            if t['type'] == 'buy':
                balance += t['shares']
            else:
                balance -= t['shares']

        # Only include fully closed positions
        if balance > 0.0001:
            continue

        sells = [t for t in htrades if t['type'] == 'sell']
        buys = [t for t in htrades if t['type'] == 'buy']
        if not sells:
            continue

        total_buy_shares = sum(t['shares'] for t in buys)
        total_buy_amount = sum(t['total_amount'] for t in buys)
        total_sell_shares = sum(t['shares'] for t in sells)
        total_sell_amount = sum(t['total_amount'] for t in sells)

        avg_buy = total_buy_amount / total_buy_shares if total_buy_shares else 0
        avg_sell = total_sell_amount / total_sell_shares if total_sell_shares else 0

        # Use realized P&L from sell_lot_details when available
        total_pnl = sum(s.get('realized_pnl', 0) or 0 for s in sells)
        if total_pnl == 0:
            total_pnl = total_sell_amount - total_buy_amount

        holding = get_holding(hid)
        name_he = holding['name_he'] if holding else htrades[0].get('name_he', '')
        symbol = holding.get('tase_symbol', '') if holding else htrades[0].get('symbol', '')
        security_type = holding.get('security_type', '') if holding else ''

        buy_dates = sorted(set(t['date'] for t in buys))
        sell_dates = sorted(set(t['date'] for t in sells))
        pnl_pct = (total_pnl / total_buy_amount * 100) if total_buy_amount else 0

        closed.append({
            'holding_id': hid,
            'name_he': name_he,
            'symbol': symbol,
            'security_type': security_type,
            'total_shares': total_buy_shares,
            'avg_buy_price': round(avg_buy, 2),
            'avg_sell_price': round(avg_sell, 2),
            'total_cost': round(total_buy_amount, 2),
            'total_pnl': round(total_pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'buy_dates': buy_dates,
            'sell_dates': sell_dates,
            'period': f"{buy_dates[0]} - {sell_dates[-1]}" if buy_dates and sell_dates else '',
        })

    return sorted(closed, key=lambda c: c.get('sell_dates', [''])[-1] if c.get('sell_dates') else '', reverse=True)


def get_pivot_by_date(start_date=None, end_date=None):
    """View 3 right: Daily totals across all securities.

    Returns list of per-date aggregate records.
    """
    details = get_daily_details(start_date, end_date)

    by_date = {}
    for d in details:
        date = d['date']
        if date not in by_date:
            by_date[date] = {'date': date, 'total_change_ils': 0, 'total_market_value': 0, 'count': 0}
        by_date[date]['total_change_ils'] += d.get('change_ils', 0) or 0
        by_date[date]['total_market_value'] += d.get('market_value', 0) or 0
        by_date[date]['count'] += 1

    result = sorted(by_date.values(), key=lambda r: r['date'])
    for r in result:
        r['total_change_ils'] = round(r['total_change_ils'], 2)
        # Compute portfolio-level pct: change / morning_value
        morning = r['total_market_value'] - r['total_change_ils']
        r['total_change_pct'] = round(r['total_change_ils'] / morning * 100, 2) if morning else 0

    return result


# ─── Yearly Tax Computation ───

