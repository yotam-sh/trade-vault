"""US daily portfolio import (IBI Smart CSV).

Sibling of ``daily_importer`` for the US/USD export. Same pipeline
(daily_prices → snapshot → interpolation) and the same ``daily_portfolio``
import type, but parses a CSV with English headers and resolves holdings by
ticker (non-TASE, synthetic ids, USD).

File shape:
    line 1:  undefined (YYYY-MM-DD)            ← title (account name blank + date)
    line 2:  Symbol,Qty,Last Price,Change %,Bid,Bid Size,Ask,Ask Size,Mkt. Value,Total Cost,Unr. P/L %,Consensus
    rows  :  ASTS,4,79.9,-6.47,...,319.6,312.34,2.32,Neutral
"""

import os
import re
import pandas as pd

from app.daily_prices import add_daily_price
from app.snapshots import generate_snapshot_from_prices, list_snapshots
from app.settings import set_setting, get_setting
from app.schemas import today_iso
from app.utils.holding_resolver import find_or_create_holding_by_ticker
from app.utils.file_utils import check_duplicate
from app.imports import create_import, find_by_date_and_type
from app.importers.position_tracker import interpolate_position_changes

# US CSV header → internal field names.
US_COLUMNS = {
    'Symbol': 'ticker',
    'Qty': 'quantity',
    'Last Price': 'price',
    'Change %': 'price_change_pct',
    'Mkt. Value': 'market_value',
    'Total Cost': 'cost_basis',
}

_DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')


def _looks_like_us_csv(filepath):
    """Header sniff: True if this CSV is the IBI Smart US export."""
    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            head = f.read(400)
    except OSError:
        return False
    return 'Symbol' in head and 'Last Price' in head


def _resolve_date(filepath, fallback):
    """Date from the title line, then the filename, then the caller's fallback."""
    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            first = f.readline()
        m = _DATE_RE.search(first)
        if m:
            return m.group(1)
    except OSError:
        pass
    m = _DATE_RE.search(os.path.basename(filepath))
    return m.group(1) if m else (fallback or today_iso())


def import_us_daily_portfolio(filepath, data_date=None, interpolate=True, force=False):
    """Import an IBI Smart US daily CSV. Returns a result dict (same shape as the
    Hebrew daily importer)."""
    filepath = os.path.abspath(filepath)
    data_date = _resolve_date(filepath, data_date)

    # Exact-bytes duplicate.
    is_dup, existing, fhash = check_duplicate(filepath)
    if is_dup:
        create_import(filename=os.path.basename(filepath), filepath=os.path.basename(filepath),
                      file_hash=fhash, data_date=data_date, import_type='daily_portfolio',
                      status='duplicate', rows_imported=0)
        return {'status': 'duplicate', 'import_id': existing.doc_id}

    # Same trading date already imported.
    existing_date = find_by_date_and_type(data_date, 'daily_portfolio')
    if existing_date:
        create_import(filename=os.path.basename(filepath), filepath=os.path.basename(filepath),
                      file_hash=fhash, data_date=data_date, import_type='daily_portfolio',
                      status='duplicate', rows_imported=0)
        return {'status': 'duplicate', 'import_id': existing_date.doc_id}

    # Row 0 is the title line; real headers are on row 1.
    df = pd.read_csv(filepath, skiprows=1, encoding='utf-8-sig')
    df.rename(columns={k.strip(): v for k, v in US_COLUMNS.items()}, inplace=True)
    df.columns = [str(c).strip() for c in df.columns]
    df.rename(columns=US_COLUMNS, inplace=True)

    rows_imported = rows_skipped = new_holdings = 0
    errors, securities, daily_prices_list = [], [], []

    for idx, row in df.iterrows():
        try:
            ticker = str(row.get('ticker', '')).strip().upper()
            if not ticker or ticker.lower() == 'nan':
                rows_skipped += 1
                continue
            quantity = float(row.get('quantity', 0) or 0)
            price = round(float(row.get('price', 0) or 0), 4)
            market_value = round(float(row.get('market_value', 0) or 0), 2)
            cost_basis = round(float(row.get('cost_basis', 0) or 0), 2)
            price_change_pct = row.get('price_change_pct')
            try:
                price_change_pct = round(float(price_change_pct), 2)
            except (TypeError, ValueError):
                price_change_pct = None

            holding_id, is_new, holding, _ = find_or_create_holding_by_ticker(
                ticker=ticker, currency='USD', quantity=quantity,
                security_type='stock', exchange='US',
            )
            if is_new:
                new_holdings += 1

            daily_prices_list.append({
                'holding_id': holding_id,
                'ticker': ticker,
                'date': data_date,
                'price': price,
                'quantity': quantity,
                'market_value': market_value,
                'cost_basis': cost_basis,
                'currency': 'USD',
                'price_change_pct': price_change_pct,
            })
            securities.append(holding_id)
            rows_imported += 1
        except Exception as e:
            errors.append(f"Row {idx}: {e}")
            rows_skipped += 1

    # Guard 1 (non-bypassable): zero rows → record failure, write no snapshot.
    if rows_imported == 0:
        create_import(filename=os.path.basename(filepath), filepath=os.path.basename(filepath),
                      file_hash=fhash, data_date=data_date, import_type='daily_portfolio',
                      status='failed', rows_imported=0, rows_skipped=rows_skipped, errors=errors)
        return {'status': 'failed', 'reason': 'no_rows', 'rows_imported': 0,
                'rows_skipped': rows_skipped, 'errors': errors}

    # Guard 2 (bypassable): wild deviation from the prior snapshot.
    new_total = sum((dp.get('market_value') or 0) for dp in daily_prices_list
                    if (dp.get('quantity') or 0) > 0)
    prev_snaps = [s for s in list_snapshots() if s.get('date', '') < data_date]
    if prev_snaps and not force:
        prev_total = sorted(prev_snaps, key=lambda s: s['date'])[-1].get('total_market_value', 0) or 0
        threshold = get_setting('import_deviation_threshold', 0.5) or 0.5
        if prev_total > 0 and abs(new_total - prev_total) / prev_total > threshold:
            create_import(filename=os.path.basename(filepath), filepath=os.path.basename(filepath),
                          file_hash=fhash, data_date=data_date, import_type='daily_portfolio',
                          status='rejected', rows_imported=0, rows_skipped=rows_skipped, errors=errors)
            dev_pct = abs(new_total - prev_total) / prev_total * 100
            return {'status': 'rejected', 'reason': 'deviation', 'new_total': new_total,
                    'prev_total': prev_total, 'deviation_pct': round(dev_pct, 1),
                    'rows_imported': rows_imported, 'rows_skipped': rows_skipped, 'errors': errors}

    import_id = create_import(
        filename=os.path.basename(filepath), filepath=os.path.basename(filepath),
        file_hash=fhash, data_date=data_date, import_type='daily_portfolio',
        rows_imported=rows_imported, rows_skipped=rows_skipped,
        new_holdings=new_holdings, errors=errors, securities=securities,
    )

    inserted = []
    for dp in daily_prices_list:
        add_daily_price(import_id=import_id, **dp)
        dp['import_id'] = import_id
        inserted.append(dp)

    generate_snapshot_from_prices(data_date, inserted, import_id=import_id)
    set_setting('last_import_date', data_date)

    interpolated_buys = interpolated_sells = 0
    if interpolate:
        interpolated_buys, interpolated_sells = interpolate_position_changes(
            data_date, daily_prices_list, import_id=import_id)

    # Heal snapshot cash after interpolation (the snapshot above predates the new
    # buy/sell transactions), so sale proceeds land in idle cash automatically.
    if interpolated_buys or interpolated_sells:
        from app.recompute import recompute_cash
        recompute_cash()

    return {
        'status': 'success' if not errors else 'partial',
        'import_id': import_id,
        'rows_imported': rows_imported,
        'rows_skipped': rows_skipped,
        'new_holdings': new_holdings,
        'interpolated_buys': interpolated_buys,
        'interpolated_sells': interpolated_sells,
        'errors': errors,
        'name_changes': [],
        'format': 'us_csv',
    }
