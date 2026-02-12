"""Portfolio analytics and reporting queries, including frontend view queries."""

from app.holdings import get_holding
from app.snapshots import list_snapshots, get_latest_snapshot
from app.transactions import list_transactions, get_total_deposits, get_total_withdrawals
from app.dividends import total_dividends
from app.settings import get_setting


# ─── Portfolio Overview Queries ───

def get_portfolio_value():
    """Get current portfolio value and key metrics."""
    snap = get_latest_snapshot()
    if not snap:
        return None

    # Enrich positions with holding names
    positions = []
    for pos in snap['positions']:
        hid = pos.get('holding_id')
        holding = get_holding(hid) if hid else None
        enriched = dict(pos)
        enriched['name_he'] = holding['name_he'] if holding else pos.get('ticker', '')
        enriched['symbol'] = holding['tase_symbol'] if holding else pos.get('ticker', '')
        positions.append(enriched)

    return {
        'date': snap['date'],
        'total_value': snap['total_market_value'],
        'total_cost': snap['total_cost_basis'],
        'unrealized_pnl': snap['total_unrealized_pnl'],
        'unrealized_pnl_pct': snap['total_unrealized_pnl_pct'],
        'daily_pnl': snap['total_daily_pnl'],
        'num_positions': snap['num_positions'],
        'positions': positions,
    }


def get_pnl_summary():
    """Get comprehensive P&L summary."""
    snap = get_latest_snapshot()
    deposits = get_total_deposits()
    withdrawals = get_total_withdrawals()
    divs = total_dividends()

    if not snap:
        return {
            'total_deposits': deposits,
            'total_withdrawals': withdrawals,
            'total_dividends': divs,
        }

    return {
        'total_value': snap['total_market_value'],
        'total_cost': snap['total_cost_basis'],
        'unrealized_pnl': snap['total_unrealized_pnl'],
        'unrealized_pnl_pct': snap['total_unrealized_pnl_pct'],
        'realized_pnl': snap.get('total_realized_pnl', 0),
        'total_deposits': deposits,
        'total_withdrawals': withdrawals,
        'net_invested': deposits - withdrawals,
        'total_dividends': divs,
        'total_return': snap['total_market_value'] - (deposits - withdrawals) + divs,
    }


# ─── Frontend View Queries ───

def get_transaction_log():
    """View 1: Transaction log (כללי) - deposits + month-end summaries.

    Returns list of transaction records for the left panel table.
    """
    # Get deposits and month summaries
    all_txns = list_transactions()
    log = []

    for txn in all_txns:
        entry = {
            'date': txn['date'],
            'action': txn['type'],
            'amount': txn['total_amount'],
            'notes': txn.get('notes', ''),
        }

        if txn['type'] == 'deposit':
            entry['balance'] = None
            # Use values stored directly from Excel
            entry['cost_change_pct'] = txn.get('cost_change_pct')
            entry['cost_change_ils'] = txn.get('cost_change_ils')
            entry['action_he'] = 'הפקדה'
            if txn.get('notes') and '250' in str(txn.get('notes', '')):
                entry['action_he'] = 'העברה ראשונית'
        elif txn['type'] == 'month_summary':
            entry['balance'] = txn.get('balance') or txn['total_amount']
            # Use actual values from Excel import
            entry['cost_change_pct'] = txn.get('cost_change_pct')
            entry['cost_change_ils'] = txn.get('cost_change_ils')
            entry['action_he'] = 'סיכום חודש'
        else:
            entry['balance'] = None
            entry['cost_change_pct'] = txn.get('cost_change_pct')
            entry['cost_change_ils'] = txn.get('cost_change_ils')
            entry['action_he'] = txn['type']

        log.append(entry)

    return log


def get_transaction_summary():
    """View 1: Right-panel aggregate metrics.

    Uses values directly from IBI Excel summary panel.
    """
    ibi_summary = get_setting('ibi_summary', {})
    deposits = get_total_deposits()

    return {
        'total_deposits': ibi_summary.get('total_deposits', deposits),
        'deposits_for_change_calc': ibi_summary.get('deposits_for_change_calc', deposits),
        'cost_change_ils': ibi_summary.get('cost_change_ils', 0),
        'cost_change_pct': ibi_summary.get('cost_change_pct', 0),
    }


def get_daily_summary(start_date=None, end_date=None):
    """View 2: Daily summary (סיכום יומי) - daily portfolio with best/worst.

    Returns list of daily summary records with top/bottom performers.
    """
    # Load all snapshots (not just filtered range) so we can use prev_value
    all_snapshots = list_snapshots()
    filtered = list_snapshots(start_date, end_date)
    filtered_dates = {s['date'] for s in filtered}

    # Build prev_value map: date -> previous day's closing value
    prev_value_map = {}
    sorted_snaps = sorted(all_snapshots, key=lambda s: s['date'])
    for i, snap in enumerate(sorted_snaps):
        if i > 0:
            prev_value_map[snap['date']] = sorted_snaps[i - 1]['total_market_value']

    result = []
    for snap in filtered:
        # Find best and worst performers from positions
        positions = snap.get('positions', [])

        best = None
        worst = None
        for pos in positions:
            pnl = pos.get('daily_pnl', 0)
            if pnl is None:
                continue

            pos_info = {
                'ticker': pos.get('ticker', ''),
                'daily_pnl': pnl,
                'daily_pnl_pct': round(pnl / pos.get('market_value', 1) * 100, 2) if pos.get('market_value') else 0,
            }

            if best is None or pnl > best['daily_pnl']:
                best = pos_info
            if worst is None or pnl < worst['daily_pnl']:
                worst = pos_info

        # Use previous day's closing value as morning value when available,
        # so that sold positions don't create a phantom gap
        prev_close = prev_value_map.get(snap['date'])
        if prev_close is not None:
            morning_value = prev_close
        else:
            morning_value = snap['total_market_value'] - snap['total_daily_pnl']

        deposits_today = 0
        day_txns = list_transactions(type_='deposit', start_date=snap['date'], end_date=snap['date'])
        deposits_today = sum(t['total_amount'] for t in day_txns)

        # Use the file-reported daily P&L (price moves on active positions).
        # On days with sells, also include the day's price impact on sold positions:
        # prev_close vs (current + sells - buys - deposits) captures everything.
        daily_pnl = snap['total_daily_pnl']
        if prev_close is not None:
            # Check if positions changed (morning mismatch)
            implied_morning = snap['total_market_value'] - snap['total_daily_pnl']
            if abs(implied_morning - prev_close) > 1:
                # Positions changed: compute true P&L across all cash flows
                buy_txns = list_transactions(type_='buy', start_date=snap['date'], end_date=snap['date'])
                sell_txns = list_transactions(type_='sell', start_date=snap['date'], end_date=snap['date'])
                buy_total = sum(t['total_amount'] for t in buy_txns)
                sell_total = sum(t['total_amount'] for t in sell_txns)
                daily_pnl = snap['total_market_value'] - prev_close - deposits_today + sell_total - buy_total

        change_pct = (daily_pnl / morning_value * 100) if morning_value else 0

        result.append({
            'date': snap['date'],
            'morning_value': round(morning_value, 2),
            'current_value': snap['total_market_value'],
            'deposits': deposits_today,
            'daily_pnl': round(daily_pnl, 2),
            'change_pct': round(change_pct, 2),
            'best': best,
            'worst': worst,
        })

    return result


def get_daily_details(start_date=None, end_date=None):
    """View 3 left: Per-security per-day data.

    Returns list of per-security daily records.
    """
    from app.daily_prices import list_dates
    from app.connection import get_table, DAILY_PRICES
    from tinydb import Query

    table = get_table(DAILY_PRICES)
    D = Query()

    conditions = []
    if start_date:
        conditions.append(D.date >= start_date)
    if end_date:
        conditions.append(D.date <= end_date)

    if conditions:
        query = conditions[0]
        for c in conditions[1:]:
            query = query & c
        records = table.search(query)
    else:
        records = table.all()

    # Enrich with holding info
    result = []
    holdings_cache = {}
    for rec in records:
        # Skip sold positions (qty=0) - they pollute counts and aggregations
        qty = rec.get('quantity', 0)
        if qty <= 0:
            continue

        hid = rec.get('holding_id')
        if hid and hid not in holdings_cache:
            h = get_holding(hid)
            holdings_cache[hid] = h

        holding = holdings_cache.get(hid, {}) or {}

        result.append({
            'date': rec['date'],
            'security_type': holding.get('security_type', ''),
            'name': holding.get('name_he', rec.get('ticker', '')),
            'tase_id': holding.get('tase_id', ''),
            'symbol': holding.get('tase_symbol', ''),
            'change_ils': rec.get('daily_pnl', 0),
            'change_pct': rec.get('price_change_pct', 0),
            'market_value': rec.get('market_value', 0),
            'quantity': qty,
            'ticker': rec.get('ticker', ''),
            'holding_id': hid,
        })

    return sorted(result, key=lambda r: (r['date'], r['security_type'], r['name']))


def get_pivot_by_security(start_date=None, end_date=None):
    """View 3 right: Aggregated pivot table by security.

    Groups by security type with subtotals.
    """
    details = get_daily_details(start_date, end_date)

    # Group by (security_type, ticker)
    by_security = {}
    for d in details:
        key = (d['security_type'], d['ticker'], d['name'])
        if key not in by_security:
            mv = d.get('market_value', 0) or 0
            change = d.get('change_ils', 0) or 0
            by_security[key] = {
                'name': d['name'],
                'ticker': d['ticker'],
                'security_type': d['security_type'],
                'total_change_ils': 0,
                'max_change_ils': None,
                'min_change_ils': None,
                'total_change_pct': 0,
                'max_change_pct': None,
                'min_change_pct': None,
                'days': 0,
                'first_market_value': mv - change,  # morning value on first day
            }
        entry = by_security[key]
        change_ils = d.get('change_ils', 0) or 0
        change_pct = d.get('change_pct', 0) or 0

        entry['total_change_ils'] += change_ils
        entry['total_change_pct'] += change_pct
        entry['days'] += 1

        if entry['max_change_ils'] is None or change_ils > entry['max_change_ils']:
            entry['max_change_ils'] = change_ils
        if entry['min_change_ils'] is None or change_ils < entry['min_change_ils']:
            entry['min_change_ils'] = change_ils
        if entry['max_change_pct'] is None or change_pct > entry['max_change_pct']:
            entry['max_change_pct'] = change_pct
        if entry['min_change_pct'] is None or change_pct < entry['min_change_pct']:
            entry['min_change_pct'] = change_pct

    # Group by type for subtotals
    type_map = {
        'stock': 'מניות',
        'mutual_fund': 'קרן',
        'etf': 'תעודת סל',
        'bond': 'אג"ח',
        'other': 'אחר',
    }

    result = {}
    for key, entry in by_security.items():
        sec_type = entry['security_type']
        type_label = type_map.get(sec_type, sec_type)
        if type_label not in result:
            result[type_label] = {
                'label': type_label,
                'securities': [],
                'subtotal_change_ils': 0,
                'subtotal_cost_basis': 0,
            }
        entry['total_change_ils'] = round(entry['total_change_ils'], 2)
        entry['total_change_pct'] = round(entry['total_change_pct'], 2)
        result[type_label]['securities'].append(entry)
        result[type_label]['subtotal_change_ils'] += entry['total_change_ils']
        result[type_label]['subtotal_cost_basis'] += entry.get('first_market_value', 0)

    # Compute subtotal pct from ILS and cost basis
    for group in result.values():
        group['subtotal_change_ils'] = round(group['subtotal_change_ils'], 2)
        cb = group['subtotal_cost_basis']
        group['subtotal_change_pct'] = round(group['subtotal_change_ils'] / cb * 100, 2) if cb else 0

    # Grand total
    total_ils = round(sum(g['subtotal_change_ils'] for g in result.values()), 2)
    total_cb = sum(g['subtotal_cost_basis'] for g in result.values())
    grand_total = {
        'total_change_ils': total_ils,
        'total_change_pct': round(total_ils / total_cb * 100, 2) if total_cb else 0,
    }

    return {'groups': list(result.values()), 'grand_total': grand_total}


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

    Returns list of closed position summaries.
    """
    from app.tax_lots import get_all_lots

    all_lots = get_all_lots()

    # Group lots by holding_id
    by_holding = {}
    for lot in all_lots:
        hid = lot['holding_id']
        if hid not in by_holding:
            by_holding[hid] = []
        by_holding[hid].append(lot)

    closed = []
    for hid, lots in by_holding.items():
        # Check if all lots are closed
        all_closed = all(l['is_closed'] for l in lots)
        if not all_closed:
            continue

        holding = get_holding(hid)
        if not holding:
            continue

        total_shares = sum(l['original_shares'] for l in lots)
        total_cost = sum(l['original_shares'] * l['cost_per_share'] for l in lots)
        total_pnl = sum(l.get('realized_pnl', 0) or 0 for l in lots)
        avg_buy = total_cost / total_shares if total_shares else 0

        # Get sell info from transactions
        sell_txns = list_transactions(type_='sell')
        sell_txns_for_holding = [t for t in sell_txns if t.get('holding_id') == hid]
        total_sell_amount = sum(t.get('total_amount', 0) for t in sell_txns_for_holding)
        total_sell_shares = sum(t.get('shares', 0) for t in sell_txns_for_holding)
        avg_sell = total_sell_amount / total_sell_shares if total_sell_shares else 0

        buy_dates = sorted(set(l['buy_date'] for l in lots))
        sell_dates = sorted(set(l.get('closed_date', '') for l in lots if l.get('closed_date')))

        pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0

        closed.append({
            'holding_id': hid,
            'name_he': holding['name_he'],
            'symbol': holding.get('tase_symbol', ''),
            'security_type': holding.get('security_type', ''),
            'total_shares': total_shares,
            'avg_buy_price': round(avg_buy, 2),
            'avg_sell_price': round(avg_sell, 2),
            'total_cost': round(total_cost, 2),
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
