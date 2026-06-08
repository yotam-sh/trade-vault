"""Daily portfolio import functionality."""

import os
import pandas as pd
from app.column_map import DAILY_COLUMNS, get_security_type, clean_currency, clean_percent
from app.daily_prices import add_daily_price
from app.snapshots import generate_snapshot_from_prices, list_snapshots
from app.settings import set_setting, get_setting
from app.schemas import today_iso
from app.utils.holding_resolver import find_or_create_holding
from app.utils.file_utils import check_duplicate
from app.imports import create_import, find_by_date_and_type
from app.importers.position_tracker import interpolate_position_changes


def import_daily_portfolio(filepath, data_date=None, interpolate=True, force=False):
    """Import a daily portfolio Excel file (data.xlsx format).

    Args:
        filepath: Path to the Excel file
        data_date: Trading date this data represents (default: today)
        interpolate: If True, detect buys/sells by comparing with previous day
        force: Bypass the value-deviation guard (CLI --force). The zero-rows guard
            is never bypassable.

    Returns:
        dict with import results
    """
    filepath = os.path.abspath(filepath)
    data_date = data_date or today_iso()

    # Hash-based duplicate check (same exact file bytes)
    is_dup, existing, fhash = check_duplicate(filepath)
    if is_dup:
        print(f"File already imported on {existing['import_date']} (status: {existing['status']})")
        create_import(
            filename=os.path.basename(filepath),
            filepath=os.path.basename(filepath),
            file_hash=fhash,
            data_date=data_date,
            import_type='daily_portfolio',
            status='duplicate',
            rows_imported=0,
        )
        return {'status': 'duplicate', 'import_id': existing.doc_id}

    # Content-level duplicate check: same trading date already imported successfully
    existing_date = find_by_date_and_type(data_date, 'daily_portfolio')
    if existing_date:
        print(f"Data for {data_date} already imported on {existing_date['import_date']} "
              f"(import #{existing_date.doc_id}). Use --force to overwrite.")
        create_import(
            filename=os.path.basename(filepath),
            filepath=os.path.basename(filepath),
            file_hash=fhash,
            data_date=data_date,
            import_type='daily_portfolio',
            status='duplicate',
            rows_imported=0,
        )
        return {'status': 'duplicate', 'import_id': existing_date.doc_id}

    # Read Excel
    df = pd.read_excel(filepath)
    df.rename(columns=DAILY_COLUMNS, inplace=True)

    rows_imported = 0
    rows_skipped = 0
    new_holdings = 0
    errors = []
    securities = []
    daily_prices_list = []
    name_changes = []

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
            holding_id, is_new, holding, name_change = find_or_create_holding(
                tase_id=tase_id,
                tase_symbol=symbol,
                name_he=name_he,
                security_type=sec_type,
                currency=currency,
                quantity=quantity,
                update_active=True,
                data_date=data_date,
            )
            if is_new:
                new_holdings += 1
            if name_change:
                name_changes.append(name_change)

            # Parse price fields
            price = round(float(row.get('price', 0)), 4)
            market_value = round(float(row.get('market_value', 0)), 2)
            cost_basis = round(float(row.get('cost_basis', 0)), 2)
            daily_pnl = round(float(row.get('daily_pnl', 0)), 2) if pd.notna(row.get('daily_pnl')) else 0
            price_change_pct = clean_percent(row.get('price_change_pct'))
            fifo_cost = round(float(row.get('fifo_cost', 0)), 2) if pd.notna(row.get('fifo_cost')) else None
            fifo_change_pct = clean_percent(row.get('fifo_change_pct'))
            fifo_change_ils = round(float(row.get('fifo_change_ils', 0)), 2) if pd.notna(row.get('fifo_change_ils')) else None
            fifo_avg_price = round(float(row.get('fifo_avg_price', 0)), 4) if pd.notna(row.get('fifo_avg_price')) else None

            ticker_for_record = (holding and holding.get('ticker')) or symbol or name_he

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
                'fifo_cost': fifo_cost,
                'fifo_change_pct': fifo_change_pct,
                'fifo_change_ils': fifo_change_ils,
                'fifo_avg_price': fifo_avg_price,
            }
            daily_prices_list.append(dp_data)
            securities.append(tase_id)
            rows_imported += 1

        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")
            rows_skipped += 1

    # ── Integrity guards: never let a bad/partial file poison the time series ──
    new_total = sum((dp.get('market_value') or 0)
                    for dp in daily_prices_list if (dp.get('quantity') or 0) > 0)

    # Guard 1 (non-bypassable): zero parsed rows usually means a wrong file or a
    # broken column mapping. Record the failure, but write NO snapshot.
    if rows_imported == 0:
        create_import(
            filename=os.path.basename(filepath),
            filepath=os.path.basename(filepath),
            file_hash=fhash,
            data_date=data_date,
            import_type='daily_portfolio',
            status='failed',
            rows_imported=0,
            rows_skipped=rows_skipped,
            errors=errors,
        )
        print(f"Import REJECTED for {data_date}: 0 rows parsed "
              f"(check the file / column mapping). {rows_skipped} skipped.")
        return {'status': 'failed', 'reason': 'no_rows', 'rows_imported': 0,
                'rows_skipped': rows_skipped, 'errors': errors}

    # Guard 2 (bypassable with force): reject if today's total deviates wildly from
    # the most recent prior snapshot — a sign of a wrong-account/partial file.
    prev_snaps = [s for s in list_snapshots() if s.get('date', '') < data_date]
    if prev_snaps and not force:
        prev_total = sorted(prev_snaps, key=lambda s: s['date'])[-1].get('total_market_value', 0) or 0
        threshold = get_setting('import_deviation_threshold', 0.5) or 0.5
        if prev_total > 0 and abs(new_total - prev_total) / prev_total > threshold:
            create_import(
                filename=os.path.basename(filepath),
                filepath=os.path.basename(filepath),
                file_hash=fhash,
                data_date=data_date,
                import_type='daily_portfolio',
                status='rejected',
                rows_imported=0,
                rows_skipped=rows_skipped,
                errors=errors,
            )
            dev_pct = abs(new_total - prev_total) / prev_total * 100
            print(f"Import REJECTED for {data_date}: total ₪{new_total:,.0f} deviates "
                  f"{dev_pct:.0f}% from prior ₪{prev_total:,.0f} "
                  f"(threshold {threshold*100:.0f}%). Re-run with --force to override.")
            return {'status': 'rejected', 'reason': 'deviation', 'new_total': new_total,
                    'prev_total': prev_total, 'deviation_pct': round(dev_pct, 1),
                    'rows_imported': rows_imported, 'rows_skipped': rows_skipped,
                    'errors': errors}

    # Create import record
    import_id = create_import(
        filename=os.path.basename(filepath),
        filepath=os.path.basename(filepath),
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
        ib, is_ = interpolate_position_changes(data_date, daily_prices_list, import_id=import_id)
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
        'name_changes': name_changes,
    }

    interp_msg = ''
    if interpolated_buys or interpolated_sells:
        interp_msg = f", interpolated: {interpolated_buys} buys, {interpolated_sells} sells"
    print(f"Imported {rows_imported} rows ({new_holdings} new holdings, "
          f"{rows_skipped} skipped{interp_msg})")
    for nc in name_changes:
        print(f"  Name change (tase_id {nc['tase_id']}): {nc['old_name_he']} → {nc['new_name_he']}")
    if errors:
        for e in errors:
            print(f"  Error: {e}")

    return result
