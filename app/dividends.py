"""Dividends CRUD."""

from tinydb import Query
from app.connection import get_table, DIVIDENDS
from app.schemas import now_iso, validate_record


def add_dividend(holding_id, ticker, payment_date, amount_per_share,
                 shares_held, gross_amount, net_amount, currency='ILS',
                 source='manual', **kwargs):
    """Add a dividend record. Returns doc_id."""
    table = get_table(DIVIDENDS)
    now = now_iso()

    record = {
        'holding_id': holding_id,
        'ticker': ticker,
        'transaction_id': kwargs.get('transaction_id'),
        'ex_date': kwargs.get('ex_date'),
        'record_date': kwargs.get('record_date'),
        'payment_date': payment_date,
        'amount_per_share': amount_per_share,
        'shares_held': shares_held,
        'gross_amount': gross_amount,
        'tax_withheld': kwargs.get('tax_withheld', 0),
        'net_amount': net_amount,
        'currency': currency,
        'reinvested': kwargs.get('reinvested', False),
        'source': source,
        'notes': kwargs.get('notes'),
        'created_at': now,
        'updated_at': now,
    }

    valid, errors = validate_record('dividends', record)
    if not valid:
        raise ValueError(f"Invalid dividend record: {errors}")

    return table.insert(record)


def get_dividend(doc_id):
    """Get a dividend by doc_id."""
    table = get_table(DIVIDENDS)
    return table.get(doc_id=doc_id)


def list_dividends(ticker=None, holding_id=None, start_date=None, end_date=None):
    """List dividends with optional filters."""
    table = get_table(DIVIDENDS)
    D = Query()

    conditions = []
    if ticker:
        conditions.append(D.ticker == ticker)
    if holding_id:
        conditions.append(D.holding_id == holding_id)
    if start_date:
        conditions.append(D.payment_date >= start_date)
    if end_date:
        conditions.append(D.payment_date <= end_date)

    if conditions:
        query = conditions[0]
        for c in conditions[1:]:
            query = query & c
        results = table.search(query)
    else:
        results = table.all()

    return sorted(results, key=lambda d: d['payment_date'])


def total_dividends(ticker=None, start_date=None, end_date=None):
    """Sum of net dividends received."""
    divs = list_dividends(ticker=ticker, start_date=start_date, end_date=end_date)
    return sum(d['net_amount'] for d in divs)
