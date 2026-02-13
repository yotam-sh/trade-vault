"""Tax calculation - yearly capital gains tax computation."""

from app.analytics.trade_analytics import get_trade_history, get_closed_positions


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
