"""Portfolio overview analytics - current value and P&L summary."""

from app.holdings import get_holding
from app.snapshots import get_latest_snapshot, list_snapshots
from app.transactions import get_total_deposits, get_total_withdrawals
from app.dividends import total_dividends
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


def get_allocation_history():
    """Return per-date security-type market value breakdown for stacked area chart.

    Returns list of {date, stock, mutual_fund, etf, bond, other} dicts sorted by date.
    """
    snapshots = sorted(list_snapshots(), key=lambda s: s['date'])
    holdings_cache = {}
    result = []

    for snap in snapshots:
        totals = {'stock': 0.0, 'mutual_fund': 0.0, 'etf': 0.0, 'bond': 0.0, 'other': 0.0}
        for pos in snap.get('positions', []):
            hid = pos.get('holding_id')
            mv = pos.get('market_value', 0) or 0
            if mv <= 0:
                continue
            if hid not in holdings_cache:
                holdings_cache[hid] = get_holding(hid)
            holding = holdings_cache.get(hid) or {}
            sec_type = holding.get('security_type', 'other')
            if sec_type not in totals:
                sec_type = 'other'
            totals[sec_type] += mv

        result.append({
            'date': snap['date'],
            'stock': round(totals['stock'], 2),
            'mutual_fund': round(totals['mutual_fund'], 2),
            'etf': round(totals['etf'], 2),
            'bond': round(totals['bond'], 2),
            'other': round(totals['other'], 2),
        })

    return result
