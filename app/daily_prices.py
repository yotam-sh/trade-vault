"""Daily prices CRUD - per-security per-day price data."""

from tinydb import Query
from app.connection import get_table, DAILY_PRICES
from app.schemas import now_iso, validate_record


def add_daily_price(holding_id, ticker, date, price, quantity, market_value,
                    cost_basis, currency, import_id, **kwargs):
    """Insert a daily price record. Returns doc_id."""
    table = get_table(DAILY_PRICES)

    # Check for duplicate (ticker, date)
    D = Query()
    existing = table.search((D.ticker == ticker) & (D.date == date))
    if existing:
        # Update existing record instead
        doc_id = existing[0].doc_id
        kwargs.update({
            'holding_id': holding_id, 'price': price, 'quantity': quantity,
            'market_value': market_value, 'cost_basis': cost_basis,
            'currency': currency, 'import_id': import_id,
        })
        table.update(kwargs, doc_ids=[doc_id])
        return doc_id

    record = {
        'holding_id': holding_id,
        'ticker': ticker,
        'date': date,
        'price': price,
        'price_change_pct': kwargs.get('price_change_pct'),
        'quantity': quantity,
        'market_value': market_value,
        'cost_basis': cost_basis,
        'daily_pnl': kwargs.get('daily_pnl'),
        'fifo_cost': kwargs.get('fifo_cost'),
        'fifo_change_pct': kwargs.get('fifo_change_pct'),
        'fifo_change_ils': kwargs.get('fifo_change_ils'),
        'fifo_avg_price': kwargs.get('fifo_avg_price'),
        'unrealized_pnl': kwargs.get('unrealized_pnl'),
        'unrealized_pnl_pct': kwargs.get('unrealized_pnl_pct'),
        'holding_weight_pct': kwargs.get('holding_weight_pct'),
        'currency': currency,
        'import_id': import_id,
        'created_at': now_iso(),
    }

    valid, errors = validate_record('daily_prices', record)
    if not valid:
        raise ValueError(f"Invalid daily_price record: {errors}")

    return table.insert(record)


def get_price(ticker, date):
    """Get a price record for a specific ticker and date."""
    table = get_table(DAILY_PRICES)
    D = Query()
    results = table.search((D.ticker == ticker) & (D.date == date))
    return results[0] if results else None


def get_latest_price(ticker):
    """Get the most recent price record for a ticker."""
    table = get_table(DAILY_PRICES)
    D = Query()
    results = table.search(D.ticker == ticker)
    if not results:
        return None
    return sorted(results, key=lambda r: r['date'], reverse=True)[0]


def get_prices_by_date(date):
    """Get all price records for a specific date."""
    table = get_table(DAILY_PRICES)
    D = Query()
    return table.search(D.date == date)


def get_price_history(ticker, start_date=None, end_date=None):
    """Get price history for a ticker within an optional date range."""
    table = get_table(DAILY_PRICES)
    D = Query()
    if start_date and end_date:
        results = table.search(
            (D.ticker == ticker) & (D.date >= start_date) & (D.date <= end_date)
        )
    elif start_date:
        results = table.search((D.ticker == ticker) & (D.date >= start_date))
    elif end_date:
        results = table.search((D.ticker == ticker) & (D.date <= end_date))
    else:
        results = table.search(D.ticker == ticker)
    return sorted(results, key=lambda r: r['date'])


def list_dates():
    """List all unique dates in the daily_prices table."""
    table = get_table(DAILY_PRICES)
    dates = set()
    for record in table.all():
        dates.add(record['date'])
    return sorted(dates)
