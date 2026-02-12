"""Holdings CRUD - Master Security Registry."""

from tinydb import Query
from app.connection import get_table, HOLDINGS
from app.schemas import now_iso, validate_record


def add_holding(tase_id, tase_symbol, name_he, security_type, currency,
                ticker=None, **kwargs):
    """Add a new holding. Returns doc_id."""
    table = get_table(HOLDINGS)

    # Check for duplicate tase_id
    H = Query()
    existing = table.search(H.tase_id == tase_id)
    if existing:
        return existing[0].doc_id

    now = now_iso()
    record = {
        'ticker': ticker,
        'tase_id': tase_id,
        'tase_symbol': tase_symbol,
        'name_he': name_he,
        'name_en': kwargs.get('name_en'),
        'security_type': security_type,
        'sector': kwargs.get('sector'),
        'industry': kwargs.get('industry'),
        'currency': currency,
        'exchange': kwargs.get('exchange', 'TASE'),
        'is_active': kwargs.get('is_active', True),
        'first_bought': kwargs.get('first_bought'),
        'last_sold': kwargs.get('last_sold'),
        'tags': kwargs.get('tags', []),
        'notes': kwargs.get('notes'),
        'yfinance_data': kwargs.get('yfinance_data'),
        'created_at': now,
        'updated_at': now,
    }

    valid, errors = validate_record('holdings', record)
    if not valid:
        raise ValueError(f"Invalid holding record: {errors}")

    return table.insert(record)


def get_holding(doc_id):
    """Get a holding by doc_id."""
    table = get_table(HOLDINGS)
    return table.get(doc_id=doc_id)


def get_holding_by_ticker(ticker):
    """Get a holding by Yahoo Finance ticker."""
    table = get_table(HOLDINGS)
    H = Query()
    results = table.search(H.ticker == ticker)
    return results[0] if results else None


def get_holding_by_tase_id(tase_id):
    """Get a holding by TASE security number."""
    table = get_table(HOLDINGS)
    H = Query()
    results = table.search(H.tase_id == tase_id)
    return results[0] if results else None


def list_holdings(active_only=True):
    """List all holdings, optionally filtering to active only."""
    table = get_table(HOLDINGS)
    if active_only:
        H = Query()
        return table.search(H.is_active == True)
    return table.all()


def update_holding(doc_id, **kwargs):
    """Update a holding's fields."""
    table = get_table(HOLDINGS)
    kwargs['updated_at'] = now_iso()
    table.update(kwargs, doc_ids=[doc_id])


def deactivate_holding(doc_id, last_sold=None):
    """Mark a holding as inactive."""
    update_holding(doc_id, is_active=False, last_sold=last_sold or now_iso())


def set_ticker(doc_id, ticker):
    """Set the Yahoo Finance ticker for a holding."""
    update_holding(doc_id, ticker=ticker)


def search_holdings(name_fragment):
    """Search holdings by Hebrew name fragment."""
    table = get_table(HOLDINGS)
    H = Query()
    return table.search(H.name_he.search(name_fragment))
