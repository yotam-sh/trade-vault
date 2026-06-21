"""Daily prices CRUD - per-security per-day price data.

Each record carries a ``session`` (``'pre'`` | ``'regular'`` | ``'post'``) so a
holding can have up to three price points for one date (pre-market, regular
close, after-hours). Records written before extended-hours support have no
``session`` field and are treated as ``'regular'`` everywhere (back-compat), so
every reader defaults to ``session='regular'`` and only the current day's
snapshot ever looks at the extended sessions.
"""

from tinydb import Query
from app.connection import get_table, DAILY_PRICES
from app.schemas import now_iso, validate_record


def _session_cond(D, session):
    """Query condition matching a session, treating a missing field as 'regular'."""
    if session == 'regular':
        return (D.session == 'regular') | (~D.session.exists())
    return D.session == session


def add_daily_price(holding_id, ticker, date, price, quantity, market_value,
                    cost_basis, currency, import_id, session='regular', **kwargs):
    """Insert/update a daily price record for (holding_id, date, session). Returns doc_id."""
    table = get_table(DAILY_PRICES)

    # Dedup on (holding_id, date, session) — extended-hours rows coexist with regular.
    D = Query()
    existing = table.search(
        (D.holding_id == holding_id) & (D.date == date) & _session_cond(D, session)
    )
    if existing:
        # Update existing record instead
        doc_id = existing[0].doc_id
        update_data = {
            'ticker': ticker, 'price': price, 'quantity': quantity,
            'market_value': market_value, 'cost_basis': cost_basis,
            'currency': currency, 'session': session,
        }
        # Only overwrite import_id when given one — a later session/refresh write
        # (import_id=None) must not wipe an importer's audit link.
        if import_id is not None:
            update_data['import_id'] = import_id
        update_data.update(kwargs)
        table.update(update_data, doc_ids=[doc_id])
        return doc_id

    record = {
        'holding_id': holding_id,
        'ticker': ticker,
        'date': date,
        'price': price,
        'session': session,
        'price_change_pct': kwargs.get('price_change_pct'),
        'quantity': quantity,
        'market_value': market_value,
        'cost_basis': cost_basis,
        'daily_pnl': kwargs.get('daily_pnl'),
        'fifo_cost': kwargs.get('fifo_cost'),
        'fifo_change_pct': kwargs.get('fifo_change_pct'),
        'fifo_change_ils': kwargs.get('fifo_change_ils'),
        'fifo_avg_price': kwargs.get('fifo_avg_price'),
        'currency': currency,
        'import_id': import_id,
        'created_at': now_iso(),
    }

    valid, errors = validate_record('daily_prices', record)
    if not valid:
        raise ValueError(f"Invalid daily_price record: {errors}")

    return table.insert(record)


def get_price(holding_id, date, session='regular'):
    """Get a price record for a specific holding, date and session."""
    table = get_table(DAILY_PRICES)
    D = Query()
    results = table.search(
        (D.holding_id == holding_id) & (D.date == date) & _session_cond(D, session)
    )
    return results[0] if results else None


def get_latest_price(holding_id, session='regular'):
    """Get the most recent price record for a holding in the given session."""
    table = get_table(DAILY_PRICES)
    D = Query()
    results = table.search((D.holding_id == holding_id) & _session_cond(D, session))
    if not results:
        return None
    return sorted(results, key=lambda r: r['date'], reverse=True)[0]


def get_prices_by_date(date, session='regular'):
    """Get all price records for a specific date in the given session.

    This feeds snapshot generation, so it stays regular-only by default —
    historical snapshots are one-per-day at the regular close.
    """
    table = get_table(DAILY_PRICES)
    D = Query()
    return table.search((D.date == date) & _session_cond(D, session))


def get_price_history(holding_id, start_date=None, end_date=None, session='regular'):
    """Get price history for a holding within an optional date range (one session)."""
    table = get_table(DAILY_PRICES)
    D = Query()
    sess = _session_cond(D, session)
    if start_date and end_date:
        results = table.search(
            (D.holding_id == holding_id) & (D.date >= start_date) & (D.date <= end_date) & sess
        )
    elif start_date:
        results = table.search((D.holding_id == holding_id) & (D.date >= start_date) & sess)
    elif end_date:
        results = table.search((D.holding_id == holding_id) & (D.date <= end_date) & sess)
    else:
        results = table.search((D.holding_id == holding_id) & sess)
    return sorted(results, key=lambda r: r['date'])


def list_dates():
    """List all unique dates in the daily_prices table (all sessions)."""
    table = get_table(DAILY_PRICES)
    dates = set()
    for record in table.all():
        dates.add(record['date'])
    return sorted(dates)
