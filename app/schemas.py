"""Schema definitions and validation for all 8 database tables."""

from datetime import datetime

# Schema definitions: field -> (type, required)
HOLDING_SCHEMA = {
    'ticker': (str, False),
    'tase_id': (int, True),
    'tase_symbol': (str, True),
    'name_he': (str, True),
    'name_en': (str, False),
    'security_type': (str, True),
    'sector': (str, False),
    'industry': (str, False),
    'currency': (str, True),
    'exchange': (str, False),
    'is_active': (bool, True),
    'first_bought': (str, False),
    'last_sold': (str, False),
    'tags': (list, False),
    'notes': (str, False),
    'yfinance_data': (dict, False),
    'created_at': (str, True),
    'updated_at': (str, True),
}

TRANSACTION_SCHEMA = {
    'holding_id': (int, False),
    'ticker': (str, False),
    'type': (str, True),
    'date': (str, True),
    'shares': (float, False),
    'price_per_share': (float, False),
    'total_amount': (float, True),
    'currency': (str, True),
    'lot_id': (str, False),
    'sell_lot_details': (list, False),
    'commission': (float, False),
    'tax': (float, False),
    'fees_other': (float, False),
    'fx_rate': (float, False),
    'amount_ils': (float, False),
    'source': (str, True),
    'import_id': (int, False),
    'notes': (str, False),
    'tags': (list, False),
    'created_at': (str, True),
    'updated_at': (str, True),
}

DAILY_PRICE_SCHEMA = {
    'holding_id': (int, True),
    'ticker': (str, True),
    'date': (str, True),
    'price': (float, True),
    'price_change_pct': (float, False),
    'quantity': (float, True),
    'market_value': (float, True),
    'cost_basis': (float, True),
    'daily_pnl': (float, False),
    'fifo_cost': (float, False),
    'fifo_change_pct': (float, False),
    'fifo_change_ils': (float, False),
    'fifo_avg_price': (float, False),
    'unrealized_pnl': (float, False),
    'unrealized_pnl_pct': (float, False),
    'holding_weight_pct': (float, False),
    'currency': (str, True),
    'import_id': (int, True),
    'created_at': (str, True),
}

PORTFOLIO_SNAPSHOT_SCHEMA = {
    'date': (str, True),
    'total_market_value': (float, True),
    'total_cost_basis': (float, True),
    'total_unrealized_pnl': (float, True),
    'total_unrealized_pnl_pct': (float, True),
    'total_daily_pnl': (float, True),
    'total_realized_pnl': (float, True),
    'total_deposits': (float, True),
    'total_withdrawals': (float, True),
    'net_invested': (float, True),
    'num_positions': (int, True),
    'total_return_pct': (float, False),
    'positions': (list, True),
    'import_id': (int, False),
    'created_at': (str, True),
}

DIVIDEND_SCHEMA = {
    'holding_id': (int, True),
    'ticker': (str, True),
    'transaction_id': (int, False),
    'ex_date': (str, False),
    'record_date': (str, False),
    'payment_date': (str, True),
    'amount_per_share': (float, True),
    'shares_held': (float, True),
    'gross_amount': (float, True),
    'tax_withheld': (float, False),
    'net_amount': (float, True),
    'currency': (str, True),
    'reinvested': (bool, False),
    'source': (str, True),
    'notes': (str, False),
    'created_at': (str, True),
    'updated_at': (str, True),
}

IMPORT_SCHEMA = {
    'filename': (str, True),
    'filepath': (str, True),
    'file_hash': (str, True),
    'import_date': (str, True),
    'data_date': (str, True),
    'status': (str, True),
    'rows_imported': (int, True),
    'rows_skipped': (int, False),
    'new_holdings': (int, False),
    'errors': (list, False),
    'securities': (list, False),
    'import_type': (str, True),
    'created_at': (str, True),
}

SETTINGS_SCHEMA = {
    'key': (str, True),
    'value': (None, True),  # any type
    'updated_at': (str, True),
}

TAX_LOT_SCHEMA = {
    'lot_id': (str, True),
    'holding_id': (int, True),
    'ticker': (str, True),
    'buy_transaction_id': (int, True),
    'buy_date': (str, True),
    'buy_price': (float, True),
    'original_shares': (float, True),
    'remaining_shares': (float, True),
    'cost_per_share': (float, True),
    'total_cost': (float, True),
    'currency': (str, True),
    'is_closed': (bool, True),
    'closed_date': (str, False),
    'realized_pnl': (float, False),
    'created_at': (str, True),
    'updated_at': (str, True),
}

SCHEMAS = {
    'holdings': HOLDING_SCHEMA,
    'transactions': TRANSACTION_SCHEMA,
    'daily_prices': DAILY_PRICE_SCHEMA,
    'portfolio_snapshots': PORTFOLIO_SNAPSHOT_SCHEMA,
    'dividends': DIVIDEND_SCHEMA,
    'imports': IMPORT_SCHEMA,
    'settings': SETTINGS_SCHEMA,
    'tax_lots': TAX_LOT_SCHEMA,
}


def now_iso():
    """Return current datetime as ISO string."""
    return datetime.now().isoformat()


def today_iso():
    """Return current date as ISO string."""
    return datetime.now().strftime('%Y-%m-%d')


def validate_record(table_name, record):
    """Validate a record against its schema.

    Returns (is_valid, errors) tuple.
    """
    schema = SCHEMAS.get(table_name)
    if schema is None:
        return False, [f"Unknown table: {table_name}"]

    errors = []
    for field, (expected_type, required) in schema.items():
        if required and field not in record:
            errors.append(f"Missing required field: {field}")
            continue
        if field in record and expected_type is not None:
            value = record[field]
            if value is not None and not isinstance(value, expected_type):
                # Allow int where float is expected
                if expected_type is float and isinstance(value, int):
                    continue
                errors.append(f"Field '{field}' expected {expected_type.__name__}, got {type(value).__name__}")

    return len(errors) == 0, errors
