"""Data repair tools for morning balance and interpolated trade imports."""

from app.connection import get_table, DAILY_PRICES, IMPORTS, PORTFOLIO_SNAPSHOTS, TRANSACTIONS, TAX_LOTS
from app.snapshots import generate_snapshot_from_prices
from app.utils.date_utils import is_tase_weekend
from tinydb import Query


def repair_morning_balance_pnl():
    """Recompute daily P&L for all morning balance imports.

    Fixes the issue where quantity changes (buys/sells between days) were
    incorrectly counted as P&L. Now only price movement on shares held
    across both days is counted.
    """
    imports_table = get_table(IMPORTS)
    Q = Query()
    mb_imports = imports_table.search(Q.import_type == 'morning_balance')
    mb_import_ids = {imp.doc_id for imp in mb_imports}

    if not mb_import_ids:
        print("No morning balance imports found.")
        return

    prices_table = get_table(DAILY_PRICES)
    all_prices = prices_table.all()
    mb_prices = [p for p in all_prices if p.get('import_id') in mb_import_ids]

    if not mb_prices:
        print("No morning balance daily prices found.")
        return

    # Group by date
    by_date = {}
    for p in mb_prices:
        by_date.setdefault(p['date'], []).append(p)

    dates = sorted(by_date.keys())
    print(f"Repairing P&L for {len(dates)} dates, {len(mb_prices)} records...")

    prev_map = None  # holding_id -> {'market_value': mv, 'quantity': qty}
    fixed_count = 0

    for date in dates:
        records = by_date[date]
        date_prices = []

        for rec in records:
            hid = rec.get('holding_id')
            mv = rec.get('market_value', 0)
            qty = rec.get('quantity', 0)

            old_pnl = rec.get('daily_pnl', 0)
            new_pnl = 0
            price_change_pct = None

            if prev_map and hid in prev_map:
                prev = prev_map[hid]
                prev_mv = prev['market_value']
                prev_qty = prev['quantity']

                if prev_qty > 0 and qty > 0:
                    prev_price_per = prev_mv / prev_qty
                    today_price_per = mv / qty

                    if abs(qty - prev_qty) < 0.001:
                        new_pnl = mv - prev_mv
                    else:
                        common_qty = min(prev_qty, qty)
                        new_pnl = common_qty * (today_price_per - prev_price_per)

                    if prev_price_per > 0:
                        price_change_pct = (today_price_per - prev_price_per) / prev_price_per * 100

            # Update record if P&L changed or price_change_pct is missing
            pnl_changed = abs(new_pnl - old_pnl) > 0.01
            old_pct = rec.get('price_change_pct')
            pct_missing = price_change_pct is not None and old_pct is None

            if pnl_changed or pct_missing:
                update_data = {'daily_pnl': round(new_pnl, 2)}
                if price_change_pct is not None:
                    update_data['price_change_pct'] = round(price_change_pct, 4)
                prices_table.update(update_data, doc_ids=[rec.doc_id])
                fixed_count += 1
                if pnl_changed:
                    print(f"  {date} {rec.get('ticker',''):15s} "
                          f"pnl: {old_pnl:>10.2f} -> {new_pnl:>10.2f}  "
                          f"(qty: {qty}, prev_qty: {prev_map[hid]['quantity'] if prev_map and hid in prev_map else 'N/A'})")

            updated_rec = dict(rec)
            updated_rec['daily_pnl'] = round(new_pnl, 2)
            if price_change_pct is not None:
                updated_rec['price_change_pct'] = round(price_change_pct, 4)
            date_prices.append(updated_rec)

        # Regenerate snapshot for this date
        generate_snapshot_from_prices(date, date_prices)

        # Build prev_map for next date
        prev_map = {}
        for rec in records:
            hid = rec.get('holding_id')
            if hid:
                prev_map[hid] = {
                    'market_value': rec.get('market_value', 0),
                    'quantity': rec.get('quantity', 0),
                }

    print(f"\nFixed {fixed_count} records across {len(dates)} dates.")

    # Phase 2: Remove zero-change days (non-trading days)
    _remove_zero_change_days(prices_table, by_date, dates)


def _remove_zero_change_days(prices_table, by_date, dates):
    """Remove non-trading days (zero P&L on TASE weekends) from morning balance data.

    Args:
        prices_table: TinyDB daily_prices table
        by_date: dict mapping date -> list of price records
        dates: sorted list of date strings
    """
    snapshots_table = get_table(PORTFOLIO_SNAPSHOTS)
    removed_count = 0

    for date in dates:
        if not is_tase_weekend(date):
            continue

        records = by_date.get(date, [])
        if not records:
            continue

        # Check if all records have zero P&L
        all_zero = all(abs(r.get('daily_pnl', 0)) < 0.01 for r in records)
        if not all_zero:
            continue

        # Remove price records
        doc_ids = [r.doc_id for r in records]
        prices_table.remove(doc_ids=doc_ids)

        # Remove snapshot
        Q = Query()
        snapshots_table.remove(Q.date == date)

        removed_count += len(records)
        print(f"  Removed {date}: {len(records)} zero-change records (non-trading day)")

    if removed_count > 0:
        print(f"\nRemoved {removed_count} zero-change records across non-trading days.")


def repair_interpolated_trades(from_date='2026-02-02'):
    """Clear and re-run interpolated trade inference from a given date.

    Removes all transactions with source='interpolated' from from_date onwards,
    reverses their effects on tax lots, then re-runs interpolation date-by-date
    with the latest logic (including quantity-change detection).

    Args:
        from_date: ISO date string; only interpolated transactions on or after
                   this date are affected.
    """
    from app.transactions import list_transactions
    from app.importers.position_tracker import interpolate_position_changes
    from app.daily_prices import get_prices_by_date, list_dates
    from app.schemas import now_iso

    table_txns = get_table(TRANSACTIONS)
    table_lots = get_table(TAX_LOTS)
    Q = Query()

    # Fetch all interpolated transactions from from_date onwards
    all_txns = list_transactions(start_date=from_date)
    interp_txns = [t for t in all_txns if t.get('source') == 'interpolated']

    if not interp_txns:
        print(f"No interpolated transactions found from {from_date} onwards.")
    else:
        print(f"Found {len(interp_txns)} interpolated transactions from {from_date} — cleaning up...")

    # Step 1: Reverse interpolated sell effects (newest-first to preserve FIFO integrity)
    sells = sorted(
        [t for t in interp_txns if t['type'] == 'sell'],
        key=lambda t: t['date'],
        reverse=True,
    )
    reversed_sells = 0
    for sell_txn in sells:
        sell_lot_details = sell_txn.get('sell_lot_details') or []
        for detail in sell_lot_details:
            lot_id = detail.get('lot_id')
            shares_sold = detail.get('shares_sold', 0)
            realized = detail.get('realized_pnl', 0)
            if not lot_id or shares_sold <= 0:
                continue
            lot_recs = table_lots.search(Q.lot_id == lot_id)
            if not lot_recs:
                continue
            lot = lot_recs[0]
            new_remaining = round(lot['remaining_shares'] + shares_sold, 4)
            cost_per = lot['cost_per_share']
            new_cost = round(new_remaining * cost_per, 2)
            new_realized = round((lot.get('realized_pnl') or 0) - realized, 2)
            table_lots.update({
                'remaining_shares': new_remaining,
                'total_cost': new_cost,
                'is_closed': False,
                'closed_date': None,
                'realized_pnl': new_realized,
                'updated_at': now_iso(),
            }, doc_ids=[lot.doc_id])
        reversed_sells += 1

    # Step 2: Remove tax lots created by interpolated buys
    buys = [t for t in interp_txns if t['type'] == 'buy']
    removed_lots = 0
    for buy_txn in buys:
        txn_doc_id = buy_txn.doc_id
        lot_recs = table_lots.search(Q.buy_transaction_id == txn_doc_id)
        if lot_recs:
            table_lots.remove(doc_ids=[r.doc_id for r in lot_recs])
            removed_lots += len(lot_recs)

    # Step 3: Delete all interpolated transactions from from_date onwards
    interp_doc_ids = [t.doc_id for t in interp_txns]
    if interp_doc_ids:
        table_txns.remove(doc_ids=interp_doc_ids)

    print(f"  Reversed {reversed_sells} sells, removed {removed_lots} tax lots, "
          f"deleted {len(interp_doc_ids)} transactions.")

    # Step 4: Re-run interpolation date-by-date in chronological order
    all_dates = sorted(d for d in list_dates() if d >= from_date)
    print(f"\nRe-running interpolation for {len(all_dates)} date(s) from {from_date}...")

    total_buys, total_sells = 0, 0
    for date in all_dates:
        prices = get_prices_by_date(date)
        ib, is_ = interpolate_position_changes(date, prices)
        total_buys += ib
        total_sells += is_
        if ib or is_:
            print(f"  {date}: {ib} buy(s), {is_} sell(s) interpolated")

    print(f"\nRepair complete: {total_buys} buys and {total_sells} sells interpolated across {len(all_dates)} dates.")
