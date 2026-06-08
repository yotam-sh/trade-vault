"""Canonical portfolio time-series — one definition shared by every chart/view.

Three concepts, defined once here so charts that read "the same thing" compute it
identically:

1. Portfolio value / return / drawdown  -> ``total_equity`` (securities + idle cash).
2. Daily market performance %            -> ``daily_pnl / prior-close market value``
   (securities basis, because ``daily_pnl`` is a securities figure).
3. Per-day positions (allocation & by-type breakdowns) -> the snapshot's stored
   ``positions``, so allocation totals == by-type totals == snapshot market value.
"""

from app.snapshots import list_snapshots

SECURITY_TYPES = ('stock', 'mutual_fund', 'etf', 'bond', 'other')


def equity_series(start_date=None, end_date=None):
    """Sorted [{date, total_market_value, cash_balance, total_equity, net_invested}]."""
    snaps = sorted(list_snapshots(start_date, end_date), key=lambda s: s['date'])
    out = []
    for s in snaps:
        mv = s.get('total_market_value', 0) or 0
        cash = s.get('cash_balance', 0) or 0
        out.append({
            'date': s['date'],
            'total_market_value': mv,
            'cash_balance': cash,
            'total_equity': s.get('total_equity', round(mv + cash, 2)),
            'net_invested': s.get('net_invested', 0) or 0,
        })
    return out


def daily_changes(start_date=None, end_date=None):
    """Canonical daily market performance keyed by date.

    morning_value = prior trading day's close (total_market_value); falls back to
    current market value minus daily P&L for the first day. change_pct = daily_pnl
    / morning_value. Returns {date: {daily_pnl, morning_value, change_pct}}.
    """
    all_snaps = sorted(list_snapshots(), key=lambda s: s['date'])
    prev_close = {}
    for i, s in enumerate(all_snaps):
        if i > 0:
            prev_close[s['date']] = all_snaps[i - 1].get('total_market_value', 0) or 0

    result = {}
    for s in all_snaps:
        date = s['date']
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue
        pnl = s.get('total_daily_pnl', 0) or 0
        mv = s.get('total_market_value', 0) or 0
        pc = prev_close.get(date)
        morning = pc if (pc and pc > 0) else (mv - pnl)
        result[date] = {
            'daily_pnl': pnl,
            'morning_value': morning,
            'change_pct': (pnl / morning * 100) if morning else 0,
        }
    return result


def daily_positions_by_type(start_date=None, end_date=None):
    """Per-day type breakdown from the snapshot's stored positions.

    Returns [{date, value:{type->mv}, change:{type->daily_pnl}, total_value}]. Using
    the snapshot positions (not a separate daily_prices scan) guarantees the value
    breakdown sums to the snapshot's market value, so allocation and by-type charts
    agree with the portfolio-value chart.
    """
    from app.holdings import get_holding

    snaps = sorted(list_snapshots(start_date, end_date), key=lambda s: s['date'])
    holdings_cache = {}
    rows = []
    for s in snaps:
        value = {t: 0.0 for t in SECURITY_TYPES}
        change = {t: 0.0 for t in SECURITY_TYPES}
        total_value = 0.0
        for pos in s.get('positions', []):
            mv = pos.get('market_value', 0) or 0
            if mv <= 0:
                continue
            hid = pos.get('holding_id')
            if hid not in holdings_cache:
                holdings_cache[hid] = get_holding(hid)
            holding = holdings_cache.get(hid) or {}
            sec_type = holding.get('security_type', 'other')
            if sec_type not in value:
                sec_type = 'other'
            value[sec_type] += mv
            change[sec_type] += pos.get('daily_pnl', 0) or 0
            total_value += mv
        rows.append({
            'date': s['date'],
            'value': {t: round(value[t], 2) for t in SECURITY_TYPES},
            'change': {t: round(change[t], 2) for t in SECURITY_TYPES},
            'total_value': round(total_value, 2),
        })
    return rows
