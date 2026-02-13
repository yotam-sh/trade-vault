"""Portfolio analytics - backward compatibility facade.

DEPRECATED: This module is maintained for backward compatibility only.
New code should import from app.analytics directly.

Example:
    # Old (still works)
    from app.queries import get_portfolio_value

    # New (preferred)
    from app.analytics import get_portfolio_value
"""

from app.analytics import (
    get_portfolio_value,
    get_pnl_summary,
    get_transaction_log,
    get_transaction_summary,
    get_daily_summary,
    get_daily_details,
    get_pivot_by_security,
    get_pivot_by_date,
    get_trade_history,
    get_closed_positions,
    compute_yearly_tax,
)

__all__ = [
    'get_portfolio_value',
    'get_pnl_summary',
    'get_transaction_log',
    'get_transaction_summary',
    'get_daily_summary',
    'get_daily_details',
    'get_pivot_by_security',
    'get_pivot_by_date',
    'get_trade_history',
    'get_closed_positions',
    'compute_yearly_tax',
]
