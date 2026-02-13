"""Trade history import functionality."""

import os
import glob
import pandas as pd
from app.column_map import (
    TRADE_COLUMNS, TRADE_STATUS_MAP, TRADE_ACTION_MAP, clean_currency
)
from app.holdings import add_holding, update_holding, deactivate_holding
from app.transactions import add_buy, add_sell
from app.tax_lots import create_lot, sell_fifo, get_open_lots
from app.utils.date_utils import parse_date_from_filename
from app.utils.file_utils import check_duplicate
from app.utils.holding_resolver import find_or_create_holding
from app.imports import create_import
from app.settings import get_setting


def import_trades(filepath, data_date=None):
    """Import a trade history Excel file (DDMMYYYY.xlsx format).

    Args:
        filepath: Path to the Excel file
        data_date: Trading date (default: parsed from filename)

    Returns:
        dict with import results
    """
    filepath = os.path.abspath(filepath)

    if data_date is None:
        data_date = parse_date_from_filename(filepath)

    # Duplicate check
    is_dup, existing, fhash = check_duplicate(filepath)
    if is_dup:
        print(f"File already imported on {existing['import_date']} (status: {existing['status']})")
        return {'status': 'duplicate', 'import_id': existing.doc_id}

    # Read Excel
    df = pd.read_excel(filepath)
    df.rename(columns=TRADE_COLUMNS, inplace=True)

    # Get ticker map from settings
    ticker_map = get_setting('ticker_map', {})

    rows_imported = 0
    rows_skipped = 0
    buys = 0
    sells = 0
    new_holdings = 0
    errors = []
    securities = []

    for idx, row in df.iterrows():
        try:
            # Check status - skip cancelled orders
            status_he = str(row.get('status', '')).strip()
            status = TRADE_STATUS_MAP.get(status_he, '')
            if status == 'cancelled' or status == '':
                rows_skipped += 1
                continue

            # Check exec_qty
            exec_qty = row.get('exec_qty')
            if pd.isna(exec_qty) or exec_qty is None or float(exec_qty) == 0:
                rows_skipped += 1
                continue

            exec_qty = float(exec_qty)
            exec_price = float(row.get('exec_price', 0)) / 100  # Agorot -> ILS
            if exec_price == 0:
                rows_skipped += 1
                continue

            # Parse action
            action_he = str(row.get('action', '')).strip()
            action = TRADE_ACTION_MAP.get(action_he)
            if not action:
                rows_skipped += 1
                continue

            # Parse security info
            tase_id = int(row['tase_id'])
            name_he = str(row['name']).strip()
            symbol = str(row.get('symbol', '')).strip() if pd.notna(row.get('symbol')) else ''
            currency = clean_currency(row.get('currency', ''))

            # Find or create holding - use utility for new holdings only
            from app.holdings import get_holding_by_tase_id
            holding = get_holding_by_tase_id(tase_id)
            if holding is None:
                ticker = ticker_map.get(symbol) or ticker_map.get(name_he) or symbol or name_he
                doc_id = add_holding(
                    tase_id=tase_id,
                    tase_symbol=symbol,
                    name_he=name_he,
                    security_type='stock',  # Default; daily import will correct later
                    currency=currency,
                    ticker=ticker,
                    is_active=True,
                    first_bought=data_date if action == 'buy' else None,
                )
                new_holdings += 1
                holding_id = doc_id
                ticker_for_record = ticker
            else:
                holding_id = holding.doc_id
                ticker_for_record = holding.get('ticker') or symbol or name_he

            if action == 'buy':
                txn_id = add_buy(
                    ticker=ticker_for_record,
                    holding_id=holding_id,
                    date=data_date,
                    shares=exec_qty,
                    price_per_share=exec_price,
                    currency=currency,
                    source='trade_import',
                )
                create_lot(
                    holding_id=holding_id,
                    ticker=ticker_for_record,
                    buy_transaction_id=txn_id,
                    buy_date=data_date,
                    buy_price=exec_price,
                    shares=exec_qty,
                    currency=currency,
                )
                # Ensure holding is active
                if holding and not holding.get('is_active'):
                    update_holding(holding_id, is_active=True)
                buys += 1

            elif action == 'sell':
                try:
                    sell_details = sell_fifo(ticker_for_record, exec_qty, exec_price, data_date)
                except ValueError as e:
                    errors.append(f"Row {idx} sell {name_he}: {str(e)}")
                    rows_skipped += 1
                    continue

                add_sell(
                    ticker=ticker_for_record,
                    holding_id=holding_id,
                    date=data_date,
                    shares=exec_qty,
                    price_per_share=exec_price,
                    sell_lot_details=sell_details,
                    currency=currency,
                    source='trade_import',
                )

                # Check if holding fully sold
                remaining_lots = get_open_lots(ticker_for_record)
                if not remaining_lots:
                    deactivate_holding(holding_id, last_sold=data_date)
                sells += 1

            securities.append(ticker_for_record)
            rows_imported += 1

        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")
            rows_skipped += 1

    # Create import record
    import_id = create_import(
        filename=os.path.basename(filepath),
        filepath=filepath,
        file_hash=fhash,
        data_date=data_date,
        import_type='trade_history',
        rows_imported=rows_imported,
        rows_skipped=rows_skipped,
        new_holdings=new_holdings,
        errors=errors,
        securities=securities,
    )

    result = {
        'status': 'success' if not errors else 'partial',
        'import_id': import_id,
        'rows_imported': rows_imported,
        'rows_skipped': rows_skipped,
        'buys': buys,
        'sells': sells,
        'new_holdings': new_holdings,
        'errors': errors,
    }

    print(f"  {data_date}: {rows_imported} trades ({buys} buys, {sells} sells, "
          f"{new_holdings} new holdings, {rows_skipped} skipped)")
    if errors:
        for e in errors:
            print(f"    Error: {e}")

    return result


def import_trades_folder(folder_path):
    """Import all trade files from a folder in chronological order.

    Args:
        folder_path: Path to folder containing DDMMYYYY.xlsx files

    Returns:
        dict with aggregated results
    """
    folder_path = os.path.abspath(folder_path)
    files = glob.glob(os.path.join(folder_path, '*.xlsx'))

    if not files:
        print(f"No .xlsx files found in {folder_path}")
        return {'status': 'empty', 'files': 0}

    # Parse dates and sort chronologically
    dated_files = []
    for f in files:
        try:
            date_str = parse_date_from_filename(f)
            dated_files.append((date_str, f))
        except ValueError as e:
            print(f"Skipping {os.path.basename(f)}: {e}")

    dated_files.sort(key=lambda x: x[0])

    print(f"Importing {len(dated_files)} trade files from {folder_path}...")

    total_imported = 0
    total_skipped = 0
    total_buys = 0
    total_sells = 0
    total_new = 0
    total_errors = []
    duplicates = 0

    for date_str, filepath in dated_files:
        result = import_trades(filepath, data_date=date_str)
        if result['status'] == 'duplicate':
            duplicates += 1
            continue
        total_imported += result['rows_imported']
        total_skipped += result['rows_skipped']
        total_buys += result.get('buys', 0)
        total_sells += result.get('sells', 0)
        total_new += result['new_holdings']
        total_errors.extend(result.get('errors', []))

    print(f"\nTotal: {total_imported} trades ({total_buys} buys, {total_sells} sells), "
          f"{total_new} new holdings, {duplicates} duplicate files skipped")

    return {
        'status': 'success' if not total_errors else 'partial',
        'files': len(dated_files),
        'duplicates': duplicates,
        'rows_imported': total_imported,
        'rows_skipped': total_skipped,
        'buys': total_buys,
        'sells': total_sells,
        'new_holdings': total_new,
        'errors': total_errors,
    }
