"""Daily analytics - daily summary, details, and pivot views."""

"""Portfolio analytics and reporting queries, including frontend view queries."""

import calendar
from datetime import datetime
from collections import defaultdict

from app.holdings import get_holding
from app.snapshots import list_snapshots, get_latest_snapshot
from app.transactions import list_transactions, get_total_deposits, get_total_withdrawals
from app.utils.trading_calendar import active_non_trading_day_fn


def get_daily_summary(start_date=None, end_date=None):
    """View 2: Daily summary (סיכום יומי) - daily portfolio with best/worst.

    Returns list of daily summary records with top/bottom performers.
    """
    from app.utils.data_enrichment import enrich_positions_batch, display_name_fields
    from app.analytics.series import daily_changes

    filtered = list_snapshots(start_date, end_date)
    # Drop non-trading days for the active portfolio's market (TASE for ILS, NYSE for a
    # US book). A manual refresh on a Saturday can write a snapshot for that day; it
    # should not appear as a daily-summary row (mirrors get_daily_details).
    not_trading = active_non_trading_day_fn()
    filtered = [s for s in filtered if not not_trading(s.get('date', ''))]
    # Canonical daily change (morning value + change %) shared with all other views.
    changes = daily_changes()

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
                **display_name_fields(enriched),
                'holding_id': pos.get('holding_id'),
                'daily_pnl': pnl,
                'daily_pnl_pct': round(pnl / pos.get('market_value', 1) * 100, 2) if pos.get('market_value') else 0,
            }

            if best is None or pnl > best['daily_pnl']:
                best = pos_info
            if worst is None or pnl < worst['daily_pnl']:
                worst = pos_info

        deposits_today = 0
        day_txns = list_transactions(type_='deposit', start_date=snap['date'], end_date=snap['date'])
        deposits_today = sum(t['total_amount'] for t in day_txns)

        # Canonical daily P&L / morning value / change % (see app.analytics.series).
        dc = changes.get(snap['date'], {})
        daily_pnl = dc.get('daily_pnl', snap['total_daily_pnl'])
        morning_value = dc.get('morning_value', snap['total_market_value'] - snap['total_daily_pnl'])
        change_pct = dc.get('change_pct', 0)

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
    from app.utils.data_enrichment import enrich_positions_batch, display_name_fields
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

    # Filter out sold positions (qty=0) and extended-hours rows (regular close only)
    records = [rec for rec in records
               if rec.get('quantity', 0) > 0 and rec.get('session', 'regular') == 'regular']

    # Filter out non-trading days for the active portfolio's market (TASE weekends/holidays
    # for an ILS book, NYSE for a US book).
    not_trading = active_non_trading_day_fn()
    records = [rec for rec in records if not not_trading(rec.get('date', ''))]

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
            'name': enriched_data.get('name_he', ''),  # legacy key (sort + fallback)
            **display_name_fields(enriched_data),
            'tase_id': holding.get('tase_id', ''),
            'change_ils': rec.get('daily_pnl', 0),
            'change_pct': rec.get('price_change_pct', 0),
            'market_value': rec.get('market_value', 0),
            'quantity': rec.get('quantity', 0),
            'holding_id': hid,
        })

    return sorted(result, key=lambda r: (r['date'], r['security_type'], r['name']))


def get_daily_type_chart_data(start_date=None, end_date=None):
    """Return daily change ILS aggregated by security type for the stacked bar chart.

    Returns a list of {date, stock, mutual_fund, etf, bond, other, total_value} dicts.
    total_value is the snapshot's market value that day (the % denominator) — the same
    figure the allocation and portfolio-value charts use.
    """
    from app.analytics.series import daily_positions_by_type

    result = []
    for row in daily_positions_by_type(start_date, end_date):
        c = row['change']
        result.append({
            'date': row['date'],
            'stock': c['stock'],
            'mutual_fund': c['mutual_fund'],
            'etf': c['etf'],
            'bond': c['bond'],
            'other': c['other'],
            'total_value': row['total_value'],
        })
    return result


def get_pivot_by_security(start_date=None, end_date=None):
    """View 3 right: Aggregated pivot table by security.

    Groups by security type with subtotals.
    Groups by holding_id to properly aggregate even when tickers change.
    """
    from app.utils.data_enrichment import display_name_fields
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
                'holding_id': holding_id,
                'name': d['name'],   # legacy key (fallback)
                **display_name_fields(d),
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
        entry.update(display_name_fields(d))

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


def get_historical_performance():
    """Return average daily P&L % grouped by day-of-week, week-of-year, and month-of-year.

    Returns {'by_day': [...], 'by_week': [...], 'by_month': [...]}
    Each list contains {label, avg_pct, count} dicts.
    """
    from app.analytics.series import daily_changes

    all_snapshots = sorted(list_snapshots(), key=lambda s: s['date'])
    changes = daily_changes()  # canonical morning value + change %

    day_buckets = defaultdict(list)    # 0=Mon .. 6=Sun
    week_buckets = defaultdict(list)   # 1..53
    month_buckets = defaultdict(list)  # 1..12

    for snap in all_snapshots:
        dc = changes.get(snap['date'], {})
        morning_value = dc.get('morning_value', 0)
        if not morning_value or morning_value <= 0:
            continue
        pct = dc.get('change_pct', 0)

        dt = datetime.fromisoformat(snap['date'])
        day_buckets[dt.weekday()].append(pct)
        week_buckets[dt.isocalendar()[1]].append(pct)
        month_buckets[dt.month].append(pct)

    day_names_he = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']
    day_names_en = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    month_names_he = ['', 'ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני',
                      'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר']
    month_names_en = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    by_day = []
    for dow in sorted(day_buckets):
        vals = day_buckets[dow]
        by_day.append({
            'key': dow,
            'label_he': day_names_he[dow],
            'label_en': day_names_en[dow],
            'avg_pct': round(sum(vals) / len(vals), 3),
            'count': len(vals),
        })

    by_week = []
    for wk in sorted(week_buckets):
        vals = week_buckets[wk]
        by_week.append({
            'key': wk,
            'label_he': f'שב׳ {wk}',
            'label_en': f'Wk {wk}',
            'avg_pct': round(sum(vals) / len(vals), 3),
            'count': len(vals),
        })

    by_month = []
    for mo in sorted(month_buckets):
        vals = month_buckets[mo]
        by_month.append({
            'key': mo,
            'label_he': month_names_he[mo],
            'label_en': month_names_en[mo],
            'avg_pct': round(sum(vals) / len(vals), 3),
            'count': len(vals),
        })

    return {'by_day': by_day, 'by_week': by_week, 'by_month': by_month}
