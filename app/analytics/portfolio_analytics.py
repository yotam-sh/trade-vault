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
    return {
        'date': snap['date'],
        'total_value': snap['total_market_value'],
        'total_cost': net_invested,
        'unrealized_pnl': snap['total_market_value'] - net_invested,
        'unrealized_pnl_pct': ((snap['total_market_value'] - net_invested) / net_invested * 100) if net_invested else 0,
        'daily_pnl': snap['total_daily_pnl'],
        'num_positions': snap['num_positions'],
        'positions': positions,
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
