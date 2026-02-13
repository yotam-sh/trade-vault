"""Parse IBI daily portfolio and transaction Excel files."""

import os
import hashlib
import pandas as pd
from datetime import datetime

import glob as glob_mod
import re

from app.column_map import (
    DAILY_COLUMNS, TRANSACTION_COLUMNS, SUMMARY_LABELS, TRADE_COLUMNS,
    TRADE_STATUS_MAP, TRADE_ACTION_MAP,
    MORNING_BALANCE_COLUMNS, MORNING_BALANCE_SKIP_NAMES,
    clean_currency, clean_percent, get_security_type, get_action_type,
)
from app.holdings import add_holding, get_holding_by_tase_id, update_holding, deactivate_holding
from app.daily_prices import add_daily_price
from app.snapshots import generate_snapshot_from_prices
from app.transactions import add_transaction, add_buy, add_sell
from app.tax_lots import create_lot, sell_fifo, get_open_lots
from app.imports import create_import, find_by_hash
from app.settings import get_setting, set_setting
from app.schemas import today_iso


def file_hash(filepath):
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def import_daily_portfolio(filepath, data_date=None, interpolate=True):
    """Import a daily portfolio Excel file (data.xlsx format).

    Args:
        filepath: Path to the Excel file
        data_date: Trading date this data represents (default: today)
        interpolate: If True, detect buys/sells by comparing with previous day

    Returns:
        dict with import results
    """
    filepath = os.path.abspath(filepath)
    data_date = data_date or today_iso()

    # Duplicate check
    fhash = file_hash(filepath)
    existing = find_by_hash(fhash)
    if existing:
        print(f"File already imported on {existing['import_date']} (status: {existing['status']})")
        create_import(
            filename=os.path.basename(filepath),
            filepath=filepath,
            file_hash=fhash,
            data_date=data_date,
            import_type='daily_portfolio',
            status='duplicate',
            rows_imported=0,
        )
        return {'status': 'duplicate', 'import_id': existing.doc_id}

    # Read Excel
    df = pd.read_excel(filepath)
    df.rename(columns=DAILY_COLUMNS, inplace=True)

    rows_imported = 0
    rows_skipped = 0
    new_holdings = 0
    errors = []
    securities = []
    daily_prices_list = []

    # Get ticker map from settings
    ticker_map = get_setting('ticker_map', {})

    for idx, row in df.iterrows():
        try:
            sec_type = get_security_type(row.get('security_type', ''))
            if sec_type == 'skip':
                rows_skipped += 1
                continue

            tase_id = int(row['tase_id'])
            name_he = str(row['name']).strip()
            symbol = str(row.get('symbol', '')).strip() if pd.notna(row.get('symbol')) else ''
            currency = clean_currency(row.get('currency', ''))
            quantity = float(row.get('quantity', 0))

            # Find or create holding
            holding = get_holding_by_tase_id(tase_id)
            if holding is None:
                # Look up ticker from settings map
                ticker = ticker_map.get(symbol) or ticker_map.get(name_he)
                doc_id = add_holding(
                    tase_id=tase_id,
                    tase_symbol=symbol,
                    name_he=name_he,
                    security_type=sec_type,
                    currency=currency,
                    ticker=ticker,
                    is_active=quantity > 0,
                )
                new_holdings += 1
                holding_id = doc_id
            else:
                holding_id = holding.doc_id
                # Update active status
                is_active = quantity > 0
                if holding['is_active'] != is_active:
                    update_holding(holding_id, is_active=is_active)

            # Parse price fields
            price = float(row.get('price', 0))
            market_value = float(row.get('market_value', 0))
            cost_basis = float(row.get('cost_basis', 0))
            daily_pnl = float(row.get('daily_pnl', 0)) if pd.notna(row.get('daily_pnl')) else 0
            price_change_pct = clean_percent(row.get('price_change_pct'))
            unrealized_pnl = float(row.get('unrealized_pnl', 0)) if pd.notna(row.get('unrealized_pnl')) else None
            unrealized_pnl_pct = float(row.get('unrealized_pnl_pct', 0)) if pd.notna(row.get('unrealized_pnl_pct')) else None
            holding_weight = float(row.get('holding_weight_pct', 0)) if pd.notna(row.get('holding_weight_pct')) else None
            fifo_cost = float(row.get('fifo_cost', 0)) if pd.notna(row.get('fifo_cost')) else None
            fifo_change_pct = clean_percent(row.get('fifo_change_pct'))
            fifo_change_ils = float(row.get('fifo_change_ils', 0)) if pd.notna(row.get('fifo_change_ils')) else None
            fifo_avg_price = float(row.get('fifo_avg_price', 0)) if pd.notna(row.get('fifo_avg_price')) else None

            ticker_for_record = (holding and holding.get('ticker')) or ticker_map.get(symbol) or symbol or name_he

            # Create daily price record (import_id filled after import record created)
            dp_data = {
                'holding_id': holding_id,
                'ticker': ticker_for_record,
                'date': data_date,
                'price': price,
                'quantity': quantity,
                'market_value': market_value,
                'cost_basis': cost_basis,
                'currency': currency,
                'price_change_pct': price_change_pct,
                'daily_pnl': daily_pnl,
                'unrealized_pnl': unrealized_pnl,
                'unrealized_pnl_pct': unrealized_pnl_pct,
                'holding_weight_pct': holding_weight,
                'fifo_cost': fifo_cost,
                'fifo_change_pct': fifo_change_pct,
                'fifo_change_ils': fifo_change_ils,
                'fifo_avg_price': fifo_avg_price,
            }
            daily_prices_list.append(dp_data)
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
        import_type='daily_portfolio',
        rows_imported=rows_imported,
        rows_skipped=rows_skipped,
        new_holdings=new_holdings,
        errors=errors,
        securities=securities,
    )

    # Now insert daily prices with import_id
    inserted_prices = []
    for dp_data in daily_prices_list:
        dp_id = add_daily_price(import_id=import_id, **dp_data)
        dp_data['import_id'] = import_id
        inserted_prices.append(dp_data)

    # Generate portfolio snapshot
    generate_snapshot_from_prices(data_date, inserted_prices, import_id=import_id)

    # Update last import date
    set_setting('last_import_date', data_date)

    # Interpolation: detect buys/sells from position changes
    interpolated_buys = 0
    interpolated_sells = 0
    if interpolate:
        ib, is_ = _interpolate_position_changes(data_date, daily_prices_list)
        interpolated_buys = ib
        interpolated_sells = is_

    result = {
        'status': 'success' if not errors else 'partial',
        'import_id': import_id,
        'rows_imported': rows_imported,
        'rows_skipped': rows_skipped,
        'new_holdings': new_holdings,
        'interpolated_buys': interpolated_buys,
        'interpolated_sells': interpolated_sells,
        'errors': errors,
    }

    interp_msg = ''
    if interpolated_buys or interpolated_sells:
        interp_msg = f", interpolated: {interpolated_buys} buys, {interpolated_sells} sells"
    print(f"Imported {rows_imported} rows ({new_holdings} new holdings, "
          f"{rows_skipped} skipped{interp_msg})")
    if errors:
        for e in errors:
            print(f"  Error: {e}")

    return result


def _has_nearby_trade(holding_id, date, action_type, days=2):
    """Check if a trade_import transaction exists near the given date."""
    from app.transactions import list_transactions
    from datetime import timedelta
    d = datetime.strptime(date, '%Y-%m-%d')
    start = (d - timedelta(days=days)).strftime('%Y-%m-%d')
    end = (d + timedelta(days=days)).strftime('%Y-%m-%d')
    txns = list_transactions(type_=action_type, start_date=start, end_date=end)
    for t in txns:
        if t.get('holding_id') == holding_id and t.get('source') == 'trade_import':
            return True
    return False


def _interpolate_position_changes(data_date, today_prices):
    """Detect buys/sells by comparing today's holdings with previous day.

    Returns (interpolated_buys, interpolated_sells) counts.
    """
    from app.daily_prices import get_prices_by_date, list_dates
    from app.holdings import get_holding

    # Find the most recent prior date
    all_dates = list_dates()
    prior_dates = [d for d in all_dates if d < data_date]
    if not prior_dates:
        return 0, 0

    prev_date = max(prior_dates)
    prev_prices = get_prices_by_date(prev_date)

    # Build maps: holding_id -> price record
    prev_map = {}
    for p in prev_prices:
        hid = p.get('holding_id')
        if hid:
            prev_map[hid] = p

    today_map = {}
    for p in today_prices:
        hid = p.get('holding_id')
        if hid:
            today_map[hid] = p

    prev_ids = set(prev_map.keys())
    today_ids = set(today_map.keys())

    new_ids = today_ids - prev_ids  # Potential buys
    gone_ids = prev_ids - today_ids  # Potential sells

    interp_buys = 0
    interp_sells = 0

    for hid in new_ids:
        if _has_nearby_trade(hid, data_date, 'buy'):
            continue
        p = today_map[hid]
        holding = get_holding(hid)
        if not holding:
            continue
        ticker = holding.get('ticker') or p.get('ticker', '')
        qty = p.get('quantity', 0)
        price = p.get('price', 0)
        if qty <= 0 or price <= 0:
            continue
        txn_id = add_buy(
            ticker=ticker,
            holding_id=hid,
            date=data_date,
            shares=qty,
            price_per_share=price,
            currency=p.get('currency', 'ILS'),
            source='interpolated',
        )
        create_lot(
            holding_id=hid,
            ticker=ticker,
            buy_transaction_id=txn_id,
            buy_date=data_date,
            buy_price=price,
            shares=qty,
            currency=p.get('currency', 'ILS'),
        )
        interp_buys += 1

    for hid in gone_ids:
        if _has_nearby_trade(hid, data_date, 'sell'):
            continue
        p = prev_map[hid]
        holding = get_holding(hid)
        if not holding:
            continue
        ticker = holding.get('ticker') or p.get('ticker', '')
        qty = p.get('quantity', 0)
        price = p.get('price', 0)
        if qty <= 0 or price <= 0:
            continue
        try:
            sell_details = sell_fifo(ticker, qty, price, data_date)
        except ValueError:
            continue
        add_sell(
            ticker=ticker,
            holding_id=hid,
            date=data_date,
            shares=qty,
            price_per_share=price,
            sell_lot_details=sell_details,
            currency=p.get('currency', 'ILS'),
            source='interpolated',
        )
        remaining = get_open_lots(ticker)
        if not remaining:
            deactivate_holding(hid, last_sold=data_date)
        interp_sells += 1

    return interp_buys, interp_sells


def import_transactions(filepath):
    """Import an IBI transaction history Excel file (IBI.xlsx format).

    Args:
        filepath: Path to the Excel file

    Returns:
        dict with import results
    """
    filepath = os.path.abspath(filepath)

    # Duplicate check
    fhash = file_hash(filepath)
    existing = find_by_hash(fhash)
    if existing:
        print(f"File already imported on {existing['import_date']} (status: {existing['status']})")
        return {'status': 'duplicate', 'import_id': existing.doc_id}

    # Read Excel
    df = pd.read_excel(filepath)

    # Rename known columns
    col_rename = {}
    for col in df.columns:
        if col in TRANSACTION_COLUMNS:
            col_rename[col] = TRANSACTION_COLUMNS[col]
    df.rename(columns=col_rename, inplace=True)

    # Extract summary data from right-side columns (Unnamed: 8, Unnamed: 9)
    summary = {}
    for idx, row in df.iterrows():
        label = row.get('Unnamed: 8') if 'Unnamed: 8' in df.columns else None
        value = row.get('Unnamed: 9') if 'Unnamed: 9' in df.columns else None
        if pd.notna(label) and pd.notna(value):
            eng_key = SUMMARY_LABELS.get(str(label).strip())
            if eng_key:
                summary[eng_key] = float(value)

    rows_imported = 0
    rows_skipped = 0
    errors = []
    data_date = None

    for idx, row in df.iterrows():
        try:
            date_val = row.get('date')
            if pd.isna(date_val):
                rows_skipped += 1
                continue

            if isinstance(date_val, datetime):
                date_str = date_val.strftime('%Y-%m-%d')
            else:
                date_str = str(date_val)

            if data_date is None or date_str > data_date:
                data_date = date_str

            action = row.get('action', '')
            action_type = get_action_type(action)

            amount_raw = row.get('amount')
            if isinstance(amount_raw, str) and amount_raw.strip() == '-':
                amount = 0
            elif pd.notna(amount_raw):
                amount = float(amount_raw)
            else:
                amount = 0

            balance = float(row.get('balance')) if pd.notna(row.get('balance')) else None
            cost_change_pct = float(row.get('cost_change_pct')) if pd.notna(row.get('cost_change_pct')) else None
            cost_change_ils = float(row.get('cost_change_ils')) if pd.notna(row.get('cost_change_ils')) else None
            notes = str(row.get('notes', '')) if pd.notna(row.get('notes')) else None

            if action_type == 'month_summary':
                # Month-end summary row - store balance + cost change from Excel
                add_transaction(
                    type_='month_summary',
                    date=date_str,
                    total_amount=balance or 0,
                    currency='ILS',
                    source='excel_import',
                    notes=notes,
                    tags=['month_end'],
                    balance=balance,
                    cost_change_pct=cost_change_pct,
                    cost_change_ils=cost_change_ils,
                )
            elif action_type in ('deposit', 'withdrawal'):
                add_transaction(
                    type_=action_type,
                    date=date_str,
                    total_amount=amount,
                    currency='ILS',
                    source='excel_import',
                    notes=notes,
                    cost_change_pct=cost_change_pct,
                    cost_change_ils=cost_change_ils,
                )
            else:
                add_transaction(
                    type_=action_type,
                    date=date_str,
                    total_amount=amount,
                    currency='ILS',
                    source='excel_import',
                    notes=notes,
                )

            rows_imported += 1

        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")
            rows_skipped += 1

    # Create import record
    import_id = create_import(
        filename=os.path.basename(filepath),
        filepath=filepath,
        file_hash=fhash,
        data_date=data_date or today_iso(),
        import_type='transaction_history',
        rows_imported=rows_imported,
        rows_skipped=rows_skipped,
        errors=errors,
    )

    # Store summary data as settings
    if summary:
        set_setting('ibi_summary', summary)

    result = {
        'status': 'success' if not errors else 'partial',
        'import_id': import_id,
        'rows_imported': rows_imported,
        'rows_skipped': rows_skipped,
        'errors': errors,
        'summary': summary,
    }

    print(f"Imported {rows_imported} transactions ({rows_skipped} skipped)")
    if summary:
        print(f"  Summary: deposits={summary.get('total_deposits', 'N/A')}, "
              f"change={summary.get('cost_change_pct', 'N/A')}")

    return result


def _parse_trade_date(filename):
    """Parse date from trade filename format DDMMYYYY.xlsx -> ISO date string."""
    base = os.path.splitext(os.path.basename(filename))[0]
    m = re.match(r'^(\d{2})(\d{2})(\d{4})$', base)
    if not m:
        raise ValueError(f"Cannot parse date from filename: {filename}")
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


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
        data_date = _parse_trade_date(filepath)

    # Duplicate check
    fhash = file_hash(filepath)
    existing = find_by_hash(fhash)
    if existing:
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

            # Find or create holding
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
    files = glob_mod.glob(os.path.join(folder_path, '*.xlsx'))

    if not files:
        print(f"No .xlsx files found in {folder_path}")
        return {'status': 'empty', 'files': 0}

    # Parse dates and sort chronologically
    dated_files = []
    for f in files:
        try:
            date_str = _parse_trade_date(f)
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


def _find_holding_by_name(name_he):
    """Find an existing holding by Hebrew name, with fuzzy fallback.

    Matching strategy:
    1. Exact match on name_he
    2. Fuzzy: DB name contains file name or vice versa (handles
       reversed component order like "ת"א-ביטוח.IBI" vs "IBI.ת"א-ביטוח")
    3. Not found: return None

    Returns:
        holding document or None
    """
    from app.holdings import list_holdings
    all_holdings = list_holdings(active_only=False)

    # Exact match
    for h in all_holdings:
        if h.get('name_he') == name_he:
            return h

    # Fuzzy: bidirectional substring
    name_clean = name_he.strip()
    for h in all_holdings:
        db_name = h.get('name_he', '')
        if name_clean in db_name or db_name in name_clean:
            return h

    # Fuzzy: split on dots and hyphens, check component overlap
    name_parts = set(re.split(r'[.\-\s]+', name_clean))
    for h in all_holdings:
        db_name = h.get('name_he', '')
        db_parts = set(re.split(r'[.\-\s]+', db_name))
        if name_parts and db_parts and name_parts == db_parts:
            return h

    return None


def _parse_morning_balance_date(filename):
    """Parse date from morning balance filename DDMMYYYY.xlsx -> ISO date string."""
    base = os.path.splitext(os.path.basename(filename))[0]
    m = re.match(r'^(\d{2})(\d{2})(\d{4})$', base)
    if not m:
        raise ValueError(f"Cannot parse date from filename: {filename}")
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def import_morning_balance_folder(folder_path):
    """Import all morning balance Excel files from a folder recursively.

    Reads DDMMYYYY.xlsx files from folder_path (and subfolders), imports them
    chronologically as daily data. Computes daily P&L from consecutive days.

    Args:
        folder_path: Root folder containing morning balance .xlsx files

    Returns:
        dict with aggregated results
    """
    from app.daily_prices import get_prices_by_date

    folder_path = os.path.abspath(folder_path)

    # Find all .xlsx files recursively
    files = glob_mod.glob(os.path.join(folder_path, '**', '*.xlsx'), recursive=True)
    if not files:
        print(f"No .xlsx files found in {folder_path}")
        return {'status': 'empty', 'files': 0}

    # Parse dates and sort chronologically
    dated_files = []
    for f in files:
        try:
            date_str = _parse_morning_balance_date(f)
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
        fhash = file_hash(filepath)
        existing = find_by_hash(fhash)
        if existing:
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
                holding = _find_holding_by_name(name_raw)
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
        if prev_prices_map is not None and daily_prices_list and _is_tase_weekend(data_date):
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
        _interpolate_position_changes(data_date, daily_prices_list)

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


def repair_morning_balance_pnl():
    """Recompute daily P&L for all morning balance imports.

    Fixes the issue where quantity changes (buys/sells between days) were
    incorrectly counted as P&L. Now only price movement on shares held
    across both days is counted.
    """
    from app.connection import get_table, DAILY_PRICES, IMPORTS
    from app.snapshots import generate_snapshot_from_prices
    from tinydb import Query

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


def _is_tase_weekend(date_str):
    """Check if a date falls on a TASE weekend (non-trading day of week).

    TASE switched from Sun-Thu to Mon-Fri on 2026-01-05.
    Before: Fri + Sat are off.  After: Sat + Sun are off.
    """
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    wd = dt.weekday()  # Mon=0 ... Sun=6
    if date_str < '2026-01-05':
        return wd in (4, 5)   # Fri, Sat
    else:
        return wd in (5, 6)   # Sat, Sun


def _remove_zero_change_days(prices_table, by_date, dates):
    """Remove daily_prices and snapshots for non-trading days.

    Only removes days that have all-zero P&L AND fall on a TASE weekend.
    The first date in the dataset is always kept (baseline).
    """
    from app.connection import get_table, PORTFOLIO_SNAPSHOTS
    from tinydb import Query

    snapshots_table = get_table(PORTFOLIO_SNAPSHOTS)
    S = Query()

    first_date = dates[0] if dates else None
    removed_days = 0
    removed_records = 0

    for date in dates:
        if date == first_date:
            continue  # Keep baseline day

        if not _is_tase_weekend(date):
            continue  # Trading day — keep even if zero change

        records = by_date[date]
        all_zero = all(
            abs(r.get('daily_pnl', 0) or 0) < 0.01
            for r in records
        )
        if not all_zero:
            continue

        # Remove daily_prices for this date
        doc_ids = [r.doc_id for r in records]
        prices_table.remove(doc_ids=doc_ids)

        # Remove snapshot for this date
        snapshots_table.remove(S.date == date)

        removed_records += len(doc_ids)
        removed_days += 1
        print(f"  Removed {date} ({len(doc_ids)} records) - non-trading day")

    if removed_days:
        print(f"\nRemoved {removed_days} non-trading days ({removed_records} records).")
    else:
        print("\nNo non-trading days to remove.")
