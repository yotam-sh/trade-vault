"""Analytics layer - public API facade for all portfolio analytics and reporting queries."""

from app.analytics.portfolio_analytics import get_portfolio_value, get_pnl_summary, get_allocation_history
from app.analytics.monthly_summary import get_transaction_log, get_transaction_summary, get_monthly_chart_data
from app.analytics.daily_analytics import (
    get_daily_summary,
    get_daily_details,
    get_pivot_by_security,
    get_daily_type_chart_data,
    get_historical_performance,
)
from app.analytics.trade_analytics import get_trade_history, get_closed_positions, get_pivot_by_date
from app.analytics.tax_calculator import compute_yearly_tax
from app.analytics.position_analytics import get_position_data, get_positions_list, get_top_positions_pnl

__all__ = [
    'get_portfolio_value',
    'get_pnl_summary',
    'get_allocation_history',
    'get_transaction_log',
    'get_transaction_summary',
    'get_monthly_chart_data',
    'get_daily_summary',
    'get_daily_details',
    'get_pivot_by_security',
    'get_daily_type_chart_data',
    'get_historical_performance',
    'get_pivot_by_date',
    'get_trade_history',
    'get_closed_positions',
    'compute_yearly_tax',
    'get_position_data',
    'get_positions_list',
    'get_top_positions_pnl',
]
