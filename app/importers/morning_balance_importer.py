"""Morning balance import functionality - historic daily imports with P&L computation."""

import os
import glob
import pandas as pd
from app.column_map import MORNING_BALANCE_COLUMNS, MORNING_BALANCE_SKIP_NAMES, clean_percent
from app.daily_prices import add_daily_price, get_prices_by_date
from app.snapshots import generate_snapshot_from_prices
from app.settings import get_setting
from app.utils.date_utils import parse_date_from_filename, is_tase_weekend
from app.utils.file_utils import check_duplicate
from app.utils.holding_resolver import find_holding_by_name
from app.imports import create_import
from app.importers.position_tracker import interpolate_position_changes


def import_morning_balance_folder(folder_path):
    """Import all morning balance Excel files from a folder recursively.

    Reads DDMMYYYY.xlsx files from folder_path (and subfolders), imports them
    chronologically as daily data. Computes daily P&L from consecutive days.

    Args:
        folder_path: Root folder containing morning balance .xlsx files

    Returns:
        dict with aggregated results
    """
    folder_path = os.path.abspath(folder_path)

    # Find all .xlsx files recursively
    files = glob.glob(os.path.join(folder_path, '**', '*.xlsx'), recursive=True)
    if not files:
        print(f"No .xlsx files found in {folder_path}")
        return {'status': 'empty', 'files': 0}

    # Parse dates and sort chronologically
    dated_files = []
    for f in files:
        try:
            date_str = parse_date_from_filename(f)
            dated_files.append((date_str, f))
        except ValueError:
            print(f"Skipping {os.path.basename(f)}: cannot parse date from filename")

    dated_files.sort(key=lambda x: x[0])

    print(f"Found {len(dated_files)} morning balance files in {folder_path}")

    ticker_map = get_setting('ticker_map', {})
    total_rows = 0
    files_imported = 0
    files_skipped = 0
    total_errors = []
    prev_prices_map = None  # holding_id -> {'market_value': mv, 'quantity': qty}

    for data_date, filepath in dated_files:
        # Duplicate check
        is_dup, existing, fhash = check_duplicate(filepath)
        if is_dup:
            files_skipped += 1
            continue

        # Read Excel
        try:
            df = pd.read_excel(filepath)
        except Exception as e:
            total_errors.append(f"{os.path.basename(filepath)}: {str(e)}")
            continue

        df.rename(columns=MORNING_BALANCE_COLUMNS, inplace=True)

        rows_imported = 0
        rows_skipped = 0
        errors = []
        daily_prices_list = []

        for idx, row in df.iterrows():
            try:
                name_raw = str(row.get('name', '')).strip()

                # Skip special rows
                skip = False
                for skip_name in MORNING_BALANCE_SKIP_NAMES:
                    if skip_name in name_raw:
                        skip = True
                        break
                if skip:
                    rows_skipped += 1
                    continue

                quantity = float(row.get('quantity', 0)) if pd.notna(row.get('quantity')) else 0
                market_value = float(row.get('market_value', 0)) if pd.notna(row.get('market_value')) else 0

                # Skip inactive positions (qty=0 and value=0)
                if quantity <= 0 and market_value <= 0:
                    rows_skipped += 1
                    continue

                # Match holding by name
                holding = find_holding_by_name(name_raw)
                if holding is None:
                    errors.append(f"Row {idx}: holding not found for '{name_raw}'")
                    rows_skipped += 1
                    continue
                holding_id = holding.doc_id

                # Parse fields (weight/pct columns may contain '%' strings)
                price = float(row.get('price', 0)) if pd.notna(row.get('price')) else 0
                cost_basis = float(row.get('cost_basis', 0)) if pd.notna(row.get('cost_basis')) else 0
                holding_weight = clean_percent(row.get('holding_weight_pct'))
                fifo_cost = float(row.get('fifo_cost', 0)) if pd.notna(row.get('fifo_cost')) else None
                fifo_change_pct = clean_percent(row.get('fifo_change_pct'))
                fifo_change_ils = float(row.get('fifo_change_ils', 0)) if pd.notna(row.get('fifo_change_ils')) else None
                unrealized_pnl_pct = clean_percent(row.get('unrealized_pnl_pct'))

                # Compute unrealized P&L
                unrealized_pnl = market_value - cost_basis if cost_basis else None

                # Compute daily P&L from previous day
                daily_pnl = 0
                price_change_pct_val = None
                if prev_prices_map and holding_id in prev_prices_map:
                    prev = prev_prices_map[holding_id]
                    prev_mv = prev['market_value']
                    prev_qty = prev['quantity']

                    if prev_qty > 0 and quantity > 0:
                        prev_price_per = prev_mv / prev_qty
                        today_price_per = market_value / quantity

                        if abs(quantity - prev_qty) < 0.001:
                            # Same quantity: simple market value difference
                            daily_pnl = market_value - prev_mv
                        else:
                            # Quantity changed (buy/sell): P&L only from price
                            # movement on shares held across both days
                            common_qty = min(prev_qty, quantity)
                            daily_pnl = common_qty * (today_price_per - prev_price_per)

                        if prev_price_per > 0:
                            price_change_pct_val = (today_price_per - prev_price_per) / prev_price_per * 100

                ticker_for_record = (holding and holding.get('ticker')) or ticker_map.get(name_raw) or name_raw

                dp_data = {
                    'holding_id': holding_id,
                    'ticker': ticker_for_record,
                    'date': data_date,
                    'price': price,
                    'quantity': quantity,
                    'market_value': market_value,
                    'cost_basis': cost_basis,
                    'currency': 'ILS',
                    'price_change_pct': price_change_pct_val,
                    'daily_pnl': daily_pnl,
                    'unrealized_pnl': unrealized_pnl,
                    'unrealized_pnl_pct': unrealized_pnl_pct,
                    'holding_weight_pct': holding_weight,
                    'fifo_cost': fifo_cost,
                    'fifo_change_pct': fifo_change_pct,
                    'fifo_change_ils': fifo_change_ils,
                }
                daily_prices_list.append(dp_data)
                rows_imported += 1

            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
                rows_skipped += 1

        # Skip non-trading days: all P&L zero, TASE weekend, and not the first day
        if prev_prices_map is not None and daily_prices_list and is_tase_weekend(data_date):
            all_zero = all(abs(dp.get('daily_pnl', 0)) < 0.01 for dp in daily_prices_list)
            if all_zero:
                # Still record the import for dedup, but don't create price/snapshot records
                create_import(
                    filename=os.path.basename(filepath),
                    filepath=filepath,
                    file_hash=fhash,
                    data_date=data_date,
                    import_type='morning_balance',
                    rows_imported=0,
                    rows_skipped=rows_imported,
                    errors=[],
                    status='skipped_no_trading',
                )
                files_skipped += 1
                print(f"  {data_date}: skipped (non-trading day)")
                continue

        # Create import record
        import_id = create_import(
            filename=os.path.basename(filepath),
            filepath=filepath,
            file_hash=fhash,
            data_date=data_date,
            import_type='morning_balance',
            rows_imported=rows_imported,
            rows_skipped=rows_skipped,
            errors=errors,
        )

        # Insert daily prices
        inserted_prices = []
        for dp_data in daily_prices_list:
            dp_id = add_daily_price(import_id=import_id, **dp_data)
            dp_data['import_id'] = import_id
            inserted_prices.append(dp_data)

        # Generate portfolio snapshot
        generate_snapshot_from_prices(data_date, inserted_prices, import_id=import_id)

        # Interpolate position changes (detect buys/sells)
        interpolate_position_changes(data_date, daily_prices_list)

        # Build prev_prices_map for next day's daily P&L computation
        prev_prices_map = {}
        for dp in daily_prices_list:
            prev_prices_map[dp['holding_id']] = {
                'market_value': dp['market_value'],
                'quantity': dp['quantity'],
            }

        total_rows += rows_imported
        files_imported += 1
        total_errors.extend(errors)

        print(f"  {data_date}: {rows_imported} securities ({rows_skipped} skipped)")

    print(f"\nTotal: {files_imported} files imported, {total_rows} rows, "
          f"{files_skipped} duplicates skipped")
    if total_errors:
        for e in total_errors:
            print(f"  Error: {e}")

    return {
        'status': 'success' if not total_errors else 'partial',
        'files': files_imported,
        'duplicates': files_skipped,
        'rows_imported': total_rows,
        'errors': total_errors,
    }
