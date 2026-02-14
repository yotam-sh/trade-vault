"""Daily analytics - daily summary, details, and pivot views."""

"""Portfolio analytics and reporting queries, including frontend view queries."""

import calendar

from app.holdings import get_holding
from app.snapshots import list_snapshots, get_latest_snapshot
from app.transactions import list_transactions, get_total_deposits, get_total_withdrawals
from app.dividends import total_dividends
from app.settings import get_setting


def get_daily_summary(start_date=None, end_date=None):
    """View 2: Daily summary (סיכום יומי) - daily portfolio with best/worst.

    Returns list of daily summary records with top/bottom performers.
    """
    from app.utils.data_enrichment import enrich_positions_batch

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

        # Enrich positions with holding data for proper name/ticker display
        enriched_positions = enrich_positions_batch(positions, holding_id_key='holding_id')

        best = None
        worst = None
        for i, pos in enumerate(positions):
            pnl = pos.get('daily_pnl', 0)
            if pnl is None:
                continue

            enriched = enriched_positions[i]
            pos_info = {
                'ticker': enriched.get('symbol', ''),  # TASE symbol (Hebrew)
                'name_he': enriched.get('name_he', ''),
                'name_en': enriched.get('name_en'),
                'symbol': enriched.get('symbol', ''),  # TASE symbol
                'ticker_en': enriched.get('ticker'),  # Yahoo Finance ticker (English)
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
    from app.utils.data_enrichment import enrich_positions_batch
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

    # Filter out sold positions (qty=0)
    records = [rec for rec in records if rec.get('quantity', 0) > 0]

    # Filter out 2026-01-04 (first Sunday in TASE Mon-Fri schedule change - market closed)
    records = [rec for rec in records if rec.get('date') != '2026-01-04']

    # Use centralized enrichment for holding data
    enriched = enrich_positions_batch(records, holding_id_key='holding_id')

    # Build result with additional fields
    result = []
    holdings_cache = {}
    for i, rec in enumerate(records):
        enriched_data = enriched[i]
        hid = rec.get('holding_id')

        # Get security_type and tase_id from holding (not in enrichment)
        if hid and hid not in holdings_cache:
            h = get_holding(hid)
            holdings_cache[hid] = h
        holding = holdings_cache.get(hid, {}) or {}

        result.append({
            'date': rec['date'],
            'security_type': holding.get('security_type', ''),
            'name': enriched_data.get('name_he', ''),
            'name_en': enriched_data.get('name_en'),
            'tase_id': holding.get('tase_id', ''),
            'symbol': enriched_data.get('symbol', ''),
            'ticker': enriched_data.get('ticker'),
            'change_ils': rec.get('daily_pnl', 0),
            'change_pct': rec.get('price_change_pct', 0),
            'market_value': rec.get('market_value', 0),
            'quantity': rec.get('quantity', 0),
            'holding_id': hid,
        })

    return sorted(result, key=lambda r: (r['date'], r['security_type'], r['name']))


def get_pivot_by_security(start_date=None, end_date=None):
    """View 3 right: Aggregated pivot table by security.

    Groups by security type with subtotals.
    Groups by holding_id to properly aggregate even when tickers change.
    """
    details = get_daily_details(start_date, end_date)

    # Group by holding_id (stable identifier for the same security)
    by_security = {}
    for d in details:
        holding_id = d.get('holding_id')
        if not holding_id:
            continue  # Skip entries without holding_id

        if holding_id not in by_security:
            mv = d.get('market_value', 0) or 0
            change = d.get('change_ils', 0) or 0
            by_security[holding_id] = {
                'name': d['name'],
                'name_en': d.get('name_en'),
                'ticker': d.get('ticker'),  # Will use most recent ticker
                'symbol': d.get('symbol', ''),
                'security_type': d['security_type'],
                'total_change_ils': 0,
                'max_change_ils': None,
                'min_change_ils': None,
                'max_change_pct': None,
                'min_change_pct': None,
                'days': 0,
                'first_market_value': mv - change,  # morning value on first day
            }
        entry = by_security[holding_id]

        # Update to most recent enriched data (in case it changed)
        entry['name_en'] = d.get('name_en')
        entry['ticker'] = d.get('ticker')
        entry['symbol'] = d.get('symbol', '')

        change_ils = d.get('change_ils', 0) or 0
        change_pct = d.get('change_pct', 0) or 0

        entry['total_change_ils'] += change_ils
        entry['days'] += 1

        # Track min/max for both ILS and percentage
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
    for holding_id, entry in by_security.items():
        sec_type = entry['security_type']
        type_label = type_map.get(sec_type, sec_type)
        if type_label not in result:
            result[type_label] = {
                'label': type_label,
                'type_key': sec_type,  # Add key for template translation
                'securities': [],
                'subtotal_change_ils': 0,
                'subtotal_cost_basis': 0,
            }

        # Calculate percentage from total ILS change and cost basis (don't sum percentages!)
        entry['total_change_ils'] = round(entry['total_change_ils'], 2)
        cost_basis = entry.get('first_market_value', 0)
        if cost_basis > 0:
            entry['total_change_pct'] = round((entry['total_change_ils'] / cost_basis) * 100, 2)
        else:
            entry['total_change_pct'] = 0

        result[type_label]['securities'].append(entry)
        result[type_label]['subtotal_change_ils'] += entry['total_change_ils']
        result[type_label]['subtotal_cost_basis'] += cost_basis

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


