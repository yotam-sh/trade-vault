"""Daily portfolio import functionality."""

import os
import pandas as pd
from app.column_map import DAILY_COLUMNS, get_security_type, clean_currency, clean_percent
from app.daily_prices import add_daily_price
from app.snapshots import generate_snapshot_from_prices
from app.settings import set_setting
from app.schemas import today_iso
from app.utils.holding_resolver import find_or_create_holding
from app.utils.file_utils import check_duplicate
from app.imports import create_import
from app.importers.position_tracker import interpolate_position_changes


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
    is_dup, existing, fhash = check_duplicate(filepath)
    if is_dup:
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
    from app.settings import get_setting
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

            # Find or create holding using utility
            holding_id, is_new, holding = find_or_create_holding(
                tase_id=tase_id,
                tase_symbol=symbol,
                name_he=name_he,
                security_type=sec_type,
                currency=currency,
                quantity=quantity,
                update_active=True,
            )
            if is_new:
                new_holdings += 1

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
        ib, is_ = interpolate_position_changes(data_date, daily_prices_list)
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
