"""Excel import - backward compatibility facade.

DEPRECATED: This module is maintained for backward compatibility only.
New code should import from app.importers directly.

Example:
    # Old (still works)
    from app.excel_importer import import_daily_portfolio

    # New (preferred)
    from app.importers import import_daily_portfolio
"""

from app.importers import (
    import_daily_portfolio,
    import_transactions,
    import_trades,
    import_trades_folder,
    import_morning_balance_folder,
    repair_morning_balance_pnl,
)

__all__ = [
    'import_daily_portfolio',
    'import_transactions',
    'import_trades',
    'import_trades_folder',
    'import_morning_balance_folder',
    'repair_morning_balance_pnl',
]
