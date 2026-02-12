"""Tax lot management and FIFO engine."""

from tinydb import Query
from app.connection import get_table, TAX_LOTS
from app.schemas import now_iso, validate_record


def create_lot(holding_id, ticker, buy_transaction_id, buy_date, buy_price,
               shares, currency='ILS', commission=0):
    """Create a new tax lot from a buy transaction. Returns doc_id."""
    table = get_table(TAX_LOTS)

    # Generate lot_id
    T = Query()
    existing = table.search(T.ticker == ticker)
    lot_num = len(existing) + 1
    lot_id = f"{ticker}-{lot_num:03d}"

    cost_per_share = buy_price + (commission / shares if shares else 0)

    record = {
        'lot_id': lot_id,
        'holding_id': holding_id,
        'ticker': ticker,
        'buy_transaction_id': buy_transaction_id,
        'buy_date': buy_date,
        'buy_price': buy_price,
        'original_shares': shares,
        'remaining_shares': shares,
        'cost_per_share': round(cost_per_share, 4),
        'total_cost': round(shares * cost_per_share, 2),
        'currency': currency,
        'is_closed': False,
        'closed_date': None,
        'realized_pnl': 0,
        'created_at': now_iso(),
        'updated_at': now_iso(),
    }

    valid, errors = validate_record('tax_lots', record)
    if not valid:
        raise ValueError(f"Invalid tax_lot record: {errors}")

    return table.insert(record)


def get_open_lots(ticker):
    """Get all open (non-closed) lots for a ticker, sorted by buy_date (FIFO)."""
    table = get_table(TAX_LOTS)
    T = Query()
    lots = table.search((T.ticker == ticker) & (T.is_closed == False))
    return sorted(lots, key=lambda l: l['buy_date'])


def get_all_lots(ticker=None):
    """Get all lots, optionally filtered by ticker."""
    table = get_table(TAX_LOTS)
    if ticker:
        T = Query()
        return table.search(T.ticker == ticker)
    return table.all()


def sell_fifo(ticker, shares_to_sell, sell_price, sell_date):
    """Execute a FIFO sell against open lots.

    Returns list of lot details consumed:
    [{"lot_id", "shares_sold", "cost_basis_per_share", "realized_pnl"}, ...]
    """
    table = get_table(TAX_LOTS)
    open_lots = get_open_lots(ticker)

    if not open_lots:
        raise ValueError(f"No open lots for {ticker}")

    total_available = sum(l['remaining_shares'] for l in open_lots)
    if total_available < shares_to_sell - 0.0001:  # float tolerance
        raise ValueError(
            f"Insufficient shares: trying to sell {shares_to_sell}, "
            f"only {total_available} available"
        )

    remaining_to_sell = shares_to_sell
    sell_details = []

    for lot in open_lots:
        if remaining_to_sell <= 0.0001:
            break

        shares_from_lot = min(lot['remaining_shares'], remaining_to_sell)
        realized = round((sell_price - lot['cost_per_share']) * shares_from_lot, 2)

        new_remaining = round(lot['remaining_shares'] - shares_from_lot, 4)
        is_closed = new_remaining <= 0.0001

        update_data = {
            'remaining_shares': 0 if is_closed else new_remaining,
            'total_cost': round(
                (0 if is_closed else new_remaining) * lot['cost_per_share'], 2
            ),
            'is_closed': is_closed,
            'realized_pnl': round((lot.get('realized_pnl', 0) or 0) + realized, 2),
            'updated_at': now_iso(),
        }
        if is_closed:
            update_data['closed_date'] = sell_date

        table.update(update_data, doc_ids=[lot.doc_id])

        sell_details.append({
            'lot_id': lot['lot_id'],
            'shares_sold': shares_from_lot,
            'cost_basis_per_share': lot['cost_per_share'],
            'realized_pnl': realized,
        })

        remaining_to_sell -= shares_from_lot

    return sell_details


def get_lot_report(ticker=None):
    """Generate a report of all lots with current status."""
    lots = get_all_lots(ticker)
    report = {
        'open_lots': [],
        'closed_lots': [],
        'total_cost_basis': 0,
        'total_realized_pnl': 0,
    }

    for lot in lots:
        entry = {
            'lot_id': lot['lot_id'],
            'ticker': lot['ticker'],
            'buy_date': lot['buy_date'],
            'buy_price': lot['buy_price'],
            'original_shares': lot['original_shares'],
            'remaining_shares': lot['remaining_shares'],
            'cost_per_share': lot['cost_per_share'],
            'total_cost': lot['total_cost'],
            'realized_pnl': lot.get('realized_pnl', 0),
        }

        if lot['is_closed']:
            report['closed_lots'].append(entry)
        else:
            report['open_lots'].append(entry)
            report['total_cost_basis'] += lot['total_cost']
        report['total_realized_pnl'] += lot.get('realized_pnl', 0) or 0

    return report
