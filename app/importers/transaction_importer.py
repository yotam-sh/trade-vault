"""Transaction history import functionality."""

import os
import pandas as pd
from datetime import datetime
from app.column_map import TRANSACTION_COLUMNS, SUMMARY_LABELS, get_action_type
from app.transactions import add_transaction
from app.settings import set_setting
from app.schemas import today_iso
from app.utils.file_utils import check_duplicate
from app.imports import create_import


def import_transactions(filepath):
    """Import an IBI transaction history Excel file (IBI.xlsx format).

    Args:
        filepath: Path to the Excel file

    Returns:
        dict with import results
    """
    filepath = os.path.abspath(filepath)

    # Duplicate check
    is_dup, existing, fhash = check_duplicate(filepath)
    if is_dup:
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
