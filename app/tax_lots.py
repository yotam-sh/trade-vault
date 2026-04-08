"""Tax lot management and FIFO engine."""

from tinydb import Query
from app.connection import get_table, TAX_LOTS
from app.schemas import now_iso, validate_record


def create_lot(holding_id, ticker, buy_transaction_id, buy_date, buy_price,
               shares, currency='ILS', commission=0):
    """Create a new tax lot from a buy transaction. Returns doc_id."""
    table = get_table(TAX_LOTS)

    cost_per_share = buy_price + (commission / shares if shares else 0)

    # Insert with a temporary lot_id, then update it using the stable doc_id.
    # This avoids the len(existing)+1 collision when lots are created concurrently
    # or after any deletion.
    now = now_iso()
    record = {
        'lot_id': '',  # filled in after insert
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
        'created_at': now,
        'updated_at': now,
    }

    doc_id = table.insert(record)
    lot_id = f"{ticker}-{doc_id:04d}"
    table.update({'lot_id': lot_id}, doc_ids=[doc_id])

    return doc_id


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

        remaining_to_sell = round(remaining_to_sell - shares_from_lot, 6)

    # Clamp floating-point dust: any sub-tolerance remainder is treated as sold
    if remaining_to_sell > 0.0001:
        raise ValueError(
            f"FIFO sell incomplete for {ticker}: {remaining_to_sell} shares unsold "
            f"after exhausting all open lots"
        )

    return sell_details


def repair_lot_states():
    """Reconstruct correct lot state for every lot by replaying all sell transactions.

    After a DB import from backup (or any event that resets lot records to their
    initial state), lots can show is_closed=False and realized_pnl=0 even though
    sells have been recorded against them.  This function detects and fixes that
    by:

      1. Scanning every sell transaction that has sell_lot_details.
      2. For each lot referenced, replaying the sell effects (reducing
         remaining_shares, accumulating realized_pnl, marking is_closed) in
         chronological order.
      3. Updating any lot whose stored state differs from the replayed state.

    Safe to call multiple times (idempotent).
    Returns count of lots repaired.
    """
    from app.connection import get_table, TRANSACTIONS
    from tinydb import Query as TQ

    txn_table = get_table(TRANSACTIONS)
    lot_table = get_table(TAX_LOTS)

    # Collect all sells with sell_lot_details, sorted by date
    sells = [t for t in txn_table.search(TQ().type == 'sell')
             if t.get('sell_lot_details')]
    sells.sort(key=lambda t: t.get('date', ''))

    # Build a replay map: lot_id → {remaining_shares, realized_pnl, closed, closed_date}
    # Starting point for each lot: its original_shares from the lot record
    lot_replay = {}  # lot_id → accumulated state dict

    for txn in sells:
        for detail in txn.get('sell_lot_details') or []:
            lot_id = detail.get('lot_id')
            if not lot_id:
                continue
            shares_sold = detail.get('shares_sold') or 0
            pnl = detail.get('realized_pnl') or 0
            sell_date = txn.get('date', '')

            if lot_id not in lot_replay:
                # Look up the lot to get original_shares as starting point
                rows = lot_table.search(TQ().lot_id == lot_id)
                if not rows:
                    continue  # orphaned detail — lot was deleted
                lot = rows[0]
                lot_replay[lot_id] = {
                    'doc_id': lot.doc_id,
                    'remaining': lot.get('original_shares', 0),
                    'pnl': 0.0,
                    'closed': False,
                    'closed_date': None,
                    'cost_per_share': lot.get('cost_per_share', 0),
                }

            state = lot_replay[lot_id]
            state['remaining'] = round(state['remaining'] - shares_sold, 6)
            state['pnl'] = round(state['pnl'] + pnl, 2)
            if state['remaining'] <= 0.0001:
                state['remaining'] = 0
                state['closed'] = True
                state['closed_date'] = sell_date

    # Compare replayed state to stored state and fix differences
    repaired = 0
    for lot_id, state in lot_replay.items():
        rows = lot_table.search(TQ().lot_id == lot_id)
        if not rows:
            continue
        lot = rows[0]
        stored_remaining = lot.get('remaining_shares', 0)
        stored_pnl = lot.get('realized_pnl', 0) or 0
        stored_closed = lot.get('is_closed', False)

        if (abs(stored_remaining - state['remaining']) > 0.0001
                or abs(stored_pnl - state['pnl']) > 0.005
                or stored_closed != state['closed']):
            update = {
                'remaining_shares': state['remaining'],
                'total_cost': round(state['remaining'] * state['cost_per_share'], 2),
                'realized_pnl': state['pnl'],
                'is_closed': state['closed'],
                'updated_at': now_iso(),
            }
            if state['closed'] and state['closed_date']:
                update['closed_date'] = state['closed_date']
            lot_table.update(update, doc_ids=[state['doc_id']])
            repaired += 1

    return repaired


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
