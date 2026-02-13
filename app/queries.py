"""Portfolio analytics and reporting queries, including frontend view queries."""

import calendar

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

def _count_sun_thu_days(year, month):
    """Count Sunday-Thursday weekdays in a given month (TASE trading days)."""
    _, num_days = calendar.monthrange(year, month)
    count = 0
    for day in range(1, num_days + 1):
        # weekday(): Mon=0 .. Sun=6.  TASE trades Sun(6)-Thu(3)
        wd = calendar.weekday(year, month, day)
        if wd == 6 or wd <= 3:  # Sun, Mon, Tue, Wed, Thu
            count += 1
    return count


def _compute_monthly_summaries():
    """Compute monthly summaries on-the-fly from portfolio snapshots.

    Groups snapshots by month, computes balance and cost-change metrics,
    and flags months with incomplete trading-day coverage.
    """
    snapshots = list_snapshots()
    if not snapshots:
        return []

    deposits = list_transactions(type_='deposit')
    deposits.sort(key=lambda d: d['date'])

    # Group snapshots by YYYY-MM
    by_month = {}
    for snap in snapshots:
        month_key = snap['date'][:7]
        by_month.setdefault(month_key, []).append(snap)

    result = []
    for month_key in sorted(by_month):
        month_snaps = sorted(by_month[month_key], key=lambda s: s['date'])
        last_snap = month_snaps[-1]

        # Cumulative deposits up to end of this month
        cum_deposits = sum(
            d['total_amount'] for d in deposits if d['date'] <= last_snap['date']
        )

        balance = last_snap['total_market_value']
        cost_change_ils = balance - cum_deposits if cum_deposits else 0
        cost_change_pct = cost_change_ils / cum_deposits if cum_deposits else 0

        # Trading day completeness
        year, month = int(month_key[:4]), int(month_key[5:7])
        expected = _count_sun_thu_days(year, month)
        actual = len(month_snaps)

        result.append({
            'date': last_snap['date'],
            'balance': round(balance, 2),
            'cost_change_ils': round(cost_change_ils, 2),
            'cost_change_pct': cost_change_pct,
            'is_partial': actual < expected * 0.8,
            'trading_days': actual,
            'expected_days': expected,
        })

    return result


def get_transaction_log():
    """View 1: Transaction log (כללי) - deposits + computed month-end summaries.

    Deposits come from the transactions table.
    Monthly summaries are computed on-the-fly from portfolio snapshots.
    """
    all_txns = list_transactions()
    log = []

    for txn in all_txns:
        # Skip stored month_summary records — we compute these now
        if txn['type'] == 'month_summary':
            continue

        entry = {
            'date': txn['date'],
            'action': txn['type'],
            'amount': txn['total_amount'],
            'notes': txn.get('notes', ''),
        }

        if txn['type'] == 'deposit':
            entry['balance'] = None
            entry['cost_change_pct'] = txn.get('cost_change_pct')
            entry['cost_change_ils'] = txn.get('cost_change_ils')
            entry['action_key'] = 'action_deposit'
            if txn.get('notes') and '250' in str(txn.get('notes', '')):
                entry['action_key'] = 'action_initial_transfer'
        else:
            entry['balance'] = None
            entry['cost_change_pct'] = txn.get('cost_change_pct')
            entry['cost_change_ils'] = txn.get('cost_change_ils')
            entry['action_key'] = txn['type']

        log.append(entry)

    # Inject computed monthly summaries
    for ms in _compute_monthly_summaries():
        log.append({
            'date': ms['date'],
            'action': 'month_summary',
            'action_key': 'action_month_summary',
            'amount': None,
            'balance': ms['balance'],
            'cost_change_pct': ms['cost_change_pct'],
            'cost_change_ils': ms['cost_change_ils'],
            'notes': '',
            'is_partial': ms['is_partial'],
            'trading_days': ms['trading_days'],
            'expected_days': ms['expected_days'],
        })

    log.sort(key=lambda e: e['date'])
    return log


def get_transaction_summary():
    """View 1: Right-panel aggregate metrics.

    Computed from portfolio snapshots and deposit transactions.
    """
    deposits = get_total_deposits()
    snap = get_latest_snapshot()

    if snap and deposits:
        cost_change_ils = snap['total_market_value'] - deposits
        cost_change_pct = cost_change_ils / deposits
    else:
        cost_change_ils = 0
        cost_change_pct = 0

    return {
        'total_deposits': deposits,
        'deposits_for_change_calc': deposits,
        'cost_change_ils': cost_change_ils,
        'cost_change_pct': cost_change_pct,
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
        # prev_close vs (current + sells - buys) captures everything.
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
                daily_pnl = snap['total_market_value'] - prev_close + sell_total - buy_total

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

def compute_yearly_tax():
    """Compute capital gains tax per calendar year with loss carryover.

    Israeli capital gains tax is 25%. Net losses carry forward to offset
    gains in future years.

    Returns (by_year, years) where:
      - by_year: dict keyed by year int with tax summary per year
      - years: sorted list of year ints that have sell trades
    """
    trades = get_trade_history()
    sells = [t for t in trades if t.get('type') == 'sell']

    # Group by calendar year
    yearly = {}
    for t in sells:
        year = int(t['date'][:4])
        yearly.setdefault(year, []).append(t)

    years = sorted(yearly.keys())
    by_year = {}
    carryover = 0  # negative number carried forward

    for year in years:
        txns = yearly[year]
        total_gains = sum(t['realized_pnl'] for t in txns if (t.get('realized_pnl') or 0) > 0)
        total_losses = sum(t['realized_pnl'] for t in txns if (t.get('realized_pnl') or 0) < 0)
        net_pnl = total_gains + total_losses
        loss_carryover_in = carryover

        adjusted = net_pnl + loss_carryover_in  # loss_carryover_in is <= 0
        taxable = max(0, adjusted)
        # If still negative after this year, carry the remainder forward
        carryover = min(0, adjusted)

        tax_rate = 0.25
        by_year[year] = {
            'year': year,
            'total_gains': total_gains,
            'total_losses': total_losses,
            'net_pnl': net_pnl,
            'loss_carryover_in': loss_carryover_in,
            'taxable': taxable,
            'loss_carryover_out': carryover,
            'tax_on_gains': total_gains * tax_rate,
            'tax_offset_from_losses': abs(total_losses) * tax_rate,
            'net_tax': taxable * tax_rate,
        }

    return by_year, years
