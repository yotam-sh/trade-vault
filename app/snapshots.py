"""Portfolio snapshots CRUD and generation."""

from tinydb import Query
from app.connection import get_table, PORTFOLIO_SNAPSHOTS
from app.schemas import now_iso, validate_record


def create_snapshot(date, total_market_value, total_cost_basis, total_daily_pnl,
                    positions, **kwargs):
    """Create a portfolio snapshot. Returns doc_id."""
    table = get_table(PORTFOLIO_SNAPSHOTS)

    # Check for duplicate date
    S = Query()
    existing = table.search(S.date == date)
    if existing:
        doc_id = existing[0].doc_id
        updates = {
            'total_market_value': total_market_value,
            'total_cost_basis': total_cost_basis,
            'total_daily_pnl': total_daily_pnl,
            'positions': positions,
        }
        updates.update(kwargs)
        table.update(updates, doc_ids=[doc_id])
        return doc_id

    unrealized = total_market_value - total_cost_basis
    unrealized_pct = (unrealized / total_cost_basis * 100) if total_cost_basis else 0

    total_deposits = kwargs.get('total_deposits', 0)
    total_withdrawals = kwargs.get('total_withdrawals', 0)
    net_invested = total_deposits - total_withdrawals

    record = {
        'date': date,
        'total_market_value': total_market_value,
        'total_cost_basis': total_cost_basis,
        'total_unrealized_pnl': unrealized,
        'total_unrealized_pnl_pct': round(unrealized_pct, 4),
        'total_daily_pnl': total_daily_pnl,
        'total_realized_pnl': kwargs.get('total_realized_pnl', 0),
        'total_deposits': total_deposits,
        'total_withdrawals': total_withdrawals,
        'net_invested': net_invested,
        'num_positions': len([p for p in positions if p.get('quantity', 0) > 0]),
        'total_return_pct': kwargs.get('total_return_pct'),
        'positions': positions,
        'import_id': kwargs.get('import_id'),
        'created_at': now_iso(),
    }

    valid, errors = validate_record('portfolio_snapshots', record)
    if not valid:
        raise ValueError(f"Invalid snapshot record: {errors}")

    return table.insert(record)


def get_latest_snapshot():
    """Get the most recent snapshot."""
    table = get_table(PORTFOLIO_SNAPSHOTS)
    all_snaps = table.all()
    if not all_snaps:
        return None
    return sorted(all_snaps, key=lambda s: s['date'], reverse=True)[0]


def list_snapshots(start_date=None, end_date=None):
    """List snapshots within a date range."""
    table = get_table(PORTFOLIO_SNAPSHOTS)
    S = Query()
    if start_date and end_date:
        results = table.search((S.date >= start_date) & (S.date <= end_date))
    elif start_date:
        results = table.search(S.date >= start_date)
    elif end_date:
        results = table.search(S.date <= end_date)
    else:
        results = table.all()
    return sorted(results, key=lambda s: s['date'])


def generate_snapshot_from_prices(date, daily_prices_list, import_id=None):
    """Generate a portfolio snapshot from a list of daily price records.

    Args:
        date: ISO date string
        daily_prices_list: list of daily_price records for this date
        import_id: optional import doc_id
    """
    total_value = 0
    total_cost = 0
    total_daily_pnl = 0
    positions = []

    for dp in daily_prices_list:
        qty = dp.get('quantity', 0)
        if qty <= 0:
            continue
        mv = dp.get('market_value', 0)
        cb = dp.get('cost_basis', 0)
        dpnl = dp.get('daily_pnl', 0)

        total_value += mv
        total_cost += cb
        total_daily_pnl += dpnl

        positions.append({
            'holding_id': dp.get('holding_id'),
            'ticker': dp.get('ticker'),
            'quantity': qty,
            'market_value': mv,
            'cost_basis': cb,
            'weight': 0,  # calculated after totals
            'daily_pnl': dpnl,
        })

    # Calculate weights
    for pos in positions:
        pos['weight'] = round(pos['market_value'] / total_value * 100, 2) if total_value else 0

    return create_snapshot(
        date=date,
        total_market_value=round(total_value, 2),
        total_cost_basis=round(total_cost, 2),
        total_daily_pnl=round(total_daily_pnl, 2),
        positions=positions,
        import_id=import_id,
    )
