"""Transactions CRUD - buys, sells, deposits, dividends, etc."""

from tinydb import Query
from app.connection import get_table, TRANSACTIONS
from app.schemas import now_iso, validate_record


def add_transaction(type_, date, total_amount, currency, source, **kwargs):
    """Add a transaction. Returns doc_id."""
    table = get_table(TRANSACTIONS)
    now = now_iso()

    record = {
        'holding_id': kwargs.get('holding_id'),
        'ticker': kwargs.get('ticker'),
        'type': type_,
        'date': date,
        'shares': kwargs.get('shares'),
        'price_per_share': kwargs.get('price_per_share'),
        'total_amount': total_amount,
        'currency': currency,
        'lot_id': kwargs.get('lot_id'),
        'sell_lot_details': kwargs.get('sell_lot_details'),
        'commission': kwargs.get('commission'),
        'tax': kwargs.get('tax'),
        'fees_other': kwargs.get('fees_other'),
        'fx_rate': kwargs.get('fx_rate'),
        'amount_ils': kwargs.get('amount_ils'),
        'source': source,
        'import_id': kwargs.get('import_id'),
        'notes': kwargs.get('notes'),
        'tags': kwargs.get('tags', []),
        'cost_change_pct': kwargs.get('cost_change_pct'),
        'cost_change_ils': kwargs.get('cost_change_ils'),
        'balance': kwargs.get('balance'),
        'created_at': now,
        'updated_at': now,
    }

    valid, errors = validate_record('transactions', record)
    if not valid:
        raise ValueError(f"Invalid transaction record: {errors}")

    return table.insert(record)


def add_buy(ticker, holding_id, date, shares, price_per_share, currency='ILS',
            source='manual', **kwargs):
    """Convenience: add a buy transaction."""
    total = round(shares * price_per_share, 2)
    commission = kwargs.get('commission', 0)
    return add_transaction(
        type_='buy', date=date, total_amount=total, currency=currency,
        source=source, ticker=ticker, holding_id=holding_id,
        shares=shares, price_per_share=price_per_share,
        commission=commission, **kwargs
    )


def add_sell(ticker, holding_id, date, shares, price_per_share, currency='ILS',
             source='manual', **kwargs):
    """Convenience: add a sell transaction."""
    total = round(shares * price_per_share, 2)
    return add_transaction(
        type_='sell', date=date, total_amount=total, currency=currency,
        source=source, ticker=ticker, holding_id=holding_id,
        shares=shares, price_per_share=price_per_share, **kwargs
    )


def add_deposit(date, amount, currency='ILS', source='manual', **kwargs):
    """Add a deposit transaction."""
    return add_transaction(
        type_='deposit', date=date, total_amount=amount, currency=currency,
        source=source, **kwargs
    )


def add_withdrawal(date, amount, currency='ILS', source='manual', **kwargs):
    """Add a withdrawal transaction."""
    return add_transaction(
        type_='withdrawal', date=date, total_amount=amount, currency=currency,
        source=source, **kwargs
    )


def list_transactions(type_=None, ticker=None, start_date=None, end_date=None):
    """List transactions with optional filters."""
    table = get_table(TRANSACTIONS)
    T = Query()

    conditions = []
    if type_:
        conditions.append(T.type == type_)
    if ticker:
        conditions.append(T.ticker == ticker)
    if start_date:
        conditions.append(T.date >= start_date)
    if end_date:
        conditions.append(T.date <= end_date)

    if conditions:
        query = conditions[0]
        for c in conditions[1:]:
            query = query & c
        results = table.search(query)
    else:
        results = table.all()

    return sorted(results, key=lambda t: t['date'])


def get_total_deposits():
    """Sum of all deposit transactions."""
    deposits = list_transactions(type_='deposit')
    return sum(d['total_amount'] for d in deposits)


def get_total_withdrawals():
    """Sum of all withdrawal transactions."""
    withdrawals = list_transactions(type_='withdrawal')
    return sum(w['total_amount'] for w in withdrawals)


