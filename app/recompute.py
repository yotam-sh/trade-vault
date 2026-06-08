"""Recompute derived state after a mutation, so reads are correct immediately.

Derived state (tax lots, realized P&L, snapshot cash/equity/net_invested) used to
self-heal only at startup. These helpers run the same repairs synchronously right
after a web/CLI mutation, then flush, so the cash card and equity charts reflect the
change without a restart.
"""

from app.connection import flush_db


def recompute_cash():
    """Refresh snapshot cash_balance/total_equity/net_invested from transactions.

    Use after a cashflow-only change (deposit / withdrawal / dividend). Tax lots are
    unaffected, so they are not rebuilt.
    """
    from app.snapshots import repair_net_invested
    repaired = repair_net_invested()
    flush_db()
    return repaired


def recompute_after_trade_change():
    """Full recompute after a buy/sell add/edit/delete.

    Rebuilds tax lots (and each sell's realized P&L) via FIFO replay, then refreshes
    snapshot cash/equity. This is what makes editing a price or deleting a trade
    reconcile cost basis, realized P&L, and cash without a restart.
    """
    from app.tax_lots import rebuild_tax_lots
    from app.snapshots import repair_net_invested
    summary = rebuild_tax_lots()
    repair_net_invested()
    flush_db()
    return summary
