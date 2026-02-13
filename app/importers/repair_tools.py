"""Data repair tools for morning balance imports."""

from app.connection import get_table, DAILY_PRICES, IMPORTS, PORTFOLIO_SNAPSHOTS
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
