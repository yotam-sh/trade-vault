"""Portfolio overview analytics - current value and P&L summary."""

from app.holdings import get_holding
from app.snapshots import get_latest_snapshot, list_snapshots
from app.transactions import get_total_deposits, get_total_withdrawals, get_total_dividends

from app.utils.data_enrichment import enrich_position_with_holding


def get_portfolio_value():
    """Get current portfolio value and key metrics."""
    snap = get_latest_snapshot()
    if not snap:
        return None

    # Enrich positions with holding names
    positions = []
    for pos in snap['positions']:
        enriched = enrich_position_with_holding(pos)
        positions.append(enriched)

    net_invested = get_total_deposits() - get_total_withdrawals()
    # Total return compares current worth to net invested. Current worth is *equity*
    # (positions + idle cash), not market value alone — otherwise uninvested cash is
    # counted as a loss. This is most visible on books carrying meaningful idle cash
    # (e.g. the US portfolio), where market_value - net_invested understates the return
    # by the whole cash balance.
    cash = snap.get('cash_balance', 0) or 0
    equity = snap.get('total_equity')
    if equity is None:
        equity = snap['total_market_value'] + cash
    total_return = equity - net_invested
    return {
        'date': snap['date'],
        'total_value': snap['total_market_value'],
        'total_cost': net_invested,
        'unrealized_pnl': total_return,
        'unrealized_pnl_pct': (total_return / net_invested * 100) if net_invested else 0,
        'daily_pnl': snap['total_daily_pnl'],
        'num_positions': snap['num_positions'],
        'positions': positions,
    }


# Security-type → (he label, en label, hex color from the Comet series palette).
_TYPE_META = {
    'stock':       ('מניות', 'Stocks', '#a382f7'),
    'etf':         ('תעודות סל', 'ETFs', '#5cc8ff'),
    'mutual_fund': ('קרנות', 'Funds', '#ff9d6b'),
    'bond':        ('אג"ח', 'Bonds', '#46cf83'),
    'other':       ('אחר', 'Other', '#f0ab3e'),
    'cash':        ('מזומן', 'Cash', '#756a8c'),
}


def _display_name(pos, lang):
    """Pick the best display name/symbol for a position in the active language."""
    if lang == 'en':
        name = pos.get('name_en') or pos.get('name_yf_short') or pos.get('name_tase_en') or pos.get('name_he')
        symbol = pos.get('symbol_en') or pos.get('ticker') or pos.get('symbol')
    else:
        name = pos.get('name_he') or pos.get('name_tase_he') or pos.get('name_en')
        symbol = pos.get('symbol') or pos.get('ticker')
    return name or '', symbol or ''


def _realized_ytd():
    """Sum realized P&L from sell transactions dated in the current calendar year."""
    from datetime import date
    from app.transactions import list_transactions
    start = f'{date.today().year}-01-01'
    total = 0.0
    for t in list_transactions(type_='sell', start_date=start):
        for d in (t.get('sell_lot_details') or []):
            total += d.get('realized_pnl', 0) or 0
    return round(total, 2)


def _realized_total():
    """All-time realized P&L across every sell — partial and full closes.

    Reuses the canonical per-sell realizer (``_realized_pnl_from_lots``) so it matches
    the trade-history / closed-position figures.
    """
    from app.transactions import list_transactions
    from app.analytics.trade_analytics import _realized_pnl_from_lots
    total = sum(_realized_pnl_from_lots(t.get('sell_lot_details') or [])
                for t in list_transactions(type_='sell'))
    return round(total, 2)


def get_overview(lang='he'):
    """Assemble everything the redesigned Overview (dashboard) needs in one call.

    Reuses the canonical series/value helpers so the dashboard agrees with every
    other view. Returns None when there is no snapshot yet.
    """
    from app.analytics.series import equity_series, daily_changes
    from app.snapshots import get_latest_snapshot

    pv = get_portfolio_value()
    if not pv:
        return None

    snap = get_latest_snapshot()
    idle_cash = (snap.get('cash_balance', 0) or 0) if snap else 0

    # Today's change % (canonical, includes the manual/US derivation).
    dc = daily_changes().get(pv['date'], {})
    daily_pct = round(dc.get('change_pct', 0), 2)

    # Value chart: equity vs net invested over time, flagging deposit days (a rise in
    # net_invested vs the prior point) so the chart can mark them.
    series = []
    _prev_inv = None
    for s in equity_series():
        inv = round(s['net_invested'], 2)
        series.append({'date': s['date'], 'equity': round(s['total_equity'], 2),
                       'invested': inv, 'deposit': _prev_inv is not None and inv > _prev_inv + 0.01})
        _prev_inv = inv

    # Allocation by security type (+ a cash band so the donut totals to equity).
    by_type = {}
    for p in pv['positions']:
        mv = p.get('market_value', 0) or 0
        if mv <= 0:
            continue
        by_type[p.get('security_type', 'other')] = by_type.get(p.get('security_type', 'other'), 0) + mv
    if idle_cash > 0:
        by_type['cash'] = by_type.get('cash', 0) + idle_cash
    total_alloc = sum(by_type.values()) or 1
    allocation = []
    for tkey, val in sorted(by_type.items(), key=lambda kv: kv[1], reverse=True):
        he, en, color = _TYPE_META.get(tkey, (tkey, tkey, '#f070c4'))
        allocation.append({'key': tkey, 'label': en if lang == 'en' else he,
                           'value': round(val, 2), 'weight': round(val / total_alloc * 100, 1),
                           'color': color})

    # Previous trading day's prices (one query) so we can derive a per-position day
    # change for manual/US books, whose snapshot positions carry daily_pnl=0.
    from app.daily_prices import get_prices_by_date, list_dates
    prior = [d for d in list_dates() if d < pv['date']]
    prev_px = {}
    if prior:
        for r in get_prices_by_date(max(prior)):
            if (r.get('quantity', 0) or 0) > 0:
                prev_px[r.get('holding_id')] = r

    def _day_change(p, mv, dpnl):
        """(day_pnl, day_pct) for a position. Prefer the snapshot's stored daily_pnl
        (IBI); else derive per-share vs the previous trading day (manual/US)."""
        if dpnl:
            morning = mv - dpnl
            return dpnl, (dpnl / morning * 100 if morning else 0)
        prev = prev_px.get(p.get('holding_id'))
        qty = p.get('quantity', 0) or 0
        if not prev or qty <= 0:
            return 0.0, 0.0
        pq = prev.get('quantity', 0) or 0
        if pq <= 0:
            return 0.0, 0.0
        today_pps = mv / qty                 # ILS per share (market_value basis)
        prev_pps = (prev.get('market_value', 0) or 0) / pq
        if prev_pps <= 0:
            return 0.0, 0.0
        return round(qty * (today_pps - prev_pps), 2), round((today_pps / prev_pps - 1) * 100, 2)

    # Holdings + movers, with language-resolved display name/symbol.
    holdings = []
    for p in pv['positions']:
        if (p.get('quantity', 0) or 0) <= 0:
            continue
        name, symbol = _display_name(p, lang)
        mv = p.get('market_value', 0) or 0
        cost = p.get('cost_basis', 0) or 0
        dpnl, dpct = _day_change(p, mv, p.get('daily_pnl', 0) or 0)
        holdings.append({
            'holding_id': p.get('holding_id'), 'name': name,
            # Raw enriched name/symbol fields so templates can honor display_prefs.
            # 'symbol' stays the raw tase symbol (a display_prefs value) — disp_sym reads it.
            'symbol': p.get('symbol') or symbol,
            **{k: p.get(k) for k in (
                'name_he', 'name_en', 'name_tase_he', 'name_tase_en',
                'name_yf_long', 'name_yf_short', 'symbol_en', 'ticker')},
            'security_type': p.get('security_type', 'other'),
            'quantity': p.get('quantity', 0), 'market_value': round(mv, 2),
            'cost_basis': round(cost, 2),
            'pnl': round(mv - cost, 2),
            'pnl_pct': round((mv - cost) / cost * 100, 2) if cost else 0,
            'day_pnl': round(dpnl, 2),
            'day_pct': round(dpct, 2),
            'weight': round(p.get('weight', 0) or 0, 2),
        })
    holdings.sort(key=lambda h: h['market_value'], reverse=True)

    movers = sorted([h for h in holdings], key=lambda h: h['day_pct'])
    gainers = [h for h in reversed(movers) if h['day_pct'] > 0][:3]
    # Reversed so the hardest faller renders last (at the bottom of the list).
    losers = list(reversed([h for h in movers if h['day_pct'] < 0][:3]))

    return {
        'portfolio': pv,
        'daily_pct': daily_pct,
        'idle_cash': round(idle_cash, 2),
        'total_equity': round((pv['total_value'] or 0) + idle_cash, 2),
        'realized_ytd': _realized_ytd(),
        'realized_pnl': _realized_total(),
        'series': series,
        'allocation': allocation,
        'holdings': holdings,
        'gainers': gainers,
        'losers': losers,
    }


def get_analytics(lang='he'):
    """Aggregate the statistics deep-dive (Analytics page). Reuses canonical series.

    Returns summary stats + chart-ready series, or None when there is no history.
    """
    from datetime import date
    from app.analytics.series import equity_series, daily_changes
    from app.analytics.daily_analytics import get_historical_performance

    eq = equity_series()
    if not eq:
        return None

    # Total-return path: (equity − net_invested) / net_invested, per snapshot date.
    ret_path, peak, max_dd = [], None, 0.0
    dd_path = []
    for s in eq:
        inv = s['net_invested'] or 0
        tr_pct = ((s['total_equity'] - inv) / inv * 100) if inv else 0
        ret_path.append({'date': s['date'], 'value': round(tr_pct, 2)})
        peak = s['total_equity'] if peak is None else max(peak, s['total_equity'])
        dd = (s['total_equity'] / peak - 1) * 100 if peak else 0
        dd_path.append({'date': s['date'], 'value': round(dd, 2)})
        max_dd = min(max_dd, dd)

    # Monthly returns from Δ(equity − net_invested) within each calendar month.
    by_month = {}
    for s in eq:
        ym = s['date'][:7]
        tr = (s['total_equity'] - (s['net_invested'] or 0))
        m = by_month.setdefault(ym, {'first_tr': tr, 'first_eq': s['total_equity'], 'last_tr': tr})
        m['last_tr'] = tr
    monthly = []
    for ym in sorted(by_month):
        m = by_month[ym]
        base = m['first_eq'] or 1
        monthly.append({'month': ym, 'pct': round((m['last_tr'] - m['first_tr']) / base * 100, 2)})
    month_pcts = [m['pct'] for m in monthly]
    best_month = max(month_pcts) if month_pcts else 0
    worst_month = min(month_pcts) if month_pcts else 0

    # Win rate from canonical daily changes.
    changes = daily_changes()
    day_items = sorted(changes.items())
    wins = sum(1 for _, c in day_items if (c.get('change_pct') or 0) > 0)
    losses = sum(1 for _, c in day_items if (c.get('change_pct') or 0) < 0)
    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) else 0

    # Annualized from the total-return span.
    pv = get_portfolio_value()
    total_ret_pct = pv['unrealized_pnl_pct'] if pv else 0
    try:
        span = (date.fromisoformat(eq[-1]['date']) - date.fromisoformat(eq[0]['date'])).days or 1
        annualized = round(((1 + total_ret_pct / 100) ** (365.0 / span) - 1) * 100, 2)
    except Exception:
        annualized = 0

    # P&L by position: top 5 winners + bottom 5 losers (dedup when ≤10 holdings).
    ov = get_overview(lang) or {'holdings': []}
    ranked = sorted(
        [{'name': _display_name(h, lang)[0], 'symbol': _display_name(h, lang)[1],
          'pnl': h['pnl'], 'pnl_pct': h['pnl_pct']} for h in ov['holdings']],
        key=lambda x: x['pnl'], reverse=True)
    if len(ranked) > 10:
        pnl_by_pos = ranked[:5] + ranked[-5:]
    else:
        pnl_by_pos = ranked

    # Weekday performance.
    weekday = [{'label': (w['label_en'] if lang == 'en' else w['label_he']), 'pct': w['avg_pct']}
               for w in get_historical_performance().get('by_day', [])]

    # Benchmarks for the cumulative-return chart: portfolio vs S&P 500 / TA-125, each as
    # cumulative % from the first available point (None-safe, aligned to snapshot dates).
    dates = [s['date'] for s in eq]
    try:
        from app.analytics.benchmark_analytics import get_benchmark_data
        bm = get_benchmark_data(dates)
    except Exception:
        bm = {}

    def _cum_pct(raw):
        base = next((v for v in raw if v), None)
        return [None if (v is None or not base) else round((v / base - 1) * 100, 2) for v in raw]

    benchmarks = {key: _cum_pct(bm.get(key) or [])
                  for key in ('sp500', 'ta125', 'ta35', 'ndq', 'nikkei', 'kospi200', 'eurostoxx')}

    # Allocation over time, recolored to the Comet type palette (matches the donut).
    alloc_history = get_allocation_history()

    return {
        'summary': {
            'total_return_pct': round(total_ret_pct, 2),
            'annualized': annualized,
            'best_month': best_month,
            'worst_month': worst_month,
            'max_drawdown': round(max_dd, 2),
            'win_rate': win_rate,
        },
        'return_path': ret_path,
        'benchmarks': benchmarks,
        'drawdown_path': dd_path,
        'monthly': monthly,
        'pnl_by_pos': pnl_by_pos,
        'weekday': weekday,
        'alloc_history': alloc_history,
        'treemap': ov['holdings'],
        'date_range': {'start': eq[0]['date'], 'end': eq[-1]['date']},
    }


def get_pnl_summary():
    """Get comprehensive P&L summary."""
    snap = get_latest_snapshot()
    deposits = get_total_deposits()
    withdrawals = get_total_withdrawals()
    if not snap:
        return {
            'total_deposits': deposits,
            'total_withdrawals': withdrawals,
            'total_dividends': get_total_dividends(),
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
        'total_dividends': get_total_dividends(),
        'total_return': snap['total_market_value'] - (deposits - withdrawals),
    }


def get_allocation_history():
    """Return per-date security-type market value breakdown for stacked area chart.

    Built from the canonical per-day position source so the type values sum to the
    snapshot's market value (and match the by-type daily chart). A cash band is
    appended so the stack totals to portfolio equity.

    Returns list of {date, stock, mutual_fund, etf, bond, other, cash} dicts.
    """
    from app.analytics.series import daily_positions_by_type
    cash_by_date = {s['date']: (s.get('cash_balance', 0) or 0) for s in list_snapshots()}

    result = []
    for row in daily_positions_by_type():
        v = row['value']
        result.append({
            'date': row['date'],
            'stock': v['stock'],
            'mutual_fund': v['mutual_fund'],
            'etf': v['etf'],
            'bond': v['bond'],
            'other': v['other'],
            # Idle cash as its own band so the stack totals to portfolio equity.
            # Floored at 0 for display — early periods with incomplete history
            # may compute a slightly negative cash balance.
            'cash': round(max(0.0, cash_by_date.get(row['date'], 0)), 2),
        })

    return result
