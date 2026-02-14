"""Export module — DataFrame building and file response generation."""

import io
import pandas as pd
from flask import Response
from app.i18n import get_translations


# ── Column definitions per view ──
# Each is a list of (field_name, i18n_key) tuples.

PORTFOLIO_COLUMNS = [
    ('name_he', 'th_name'),
    ('name_en', 'export_name_en'),
    ('symbol', 'th_symbol'),
    ('ticker', 'export_ticker_en'),
    ('quantity', 'th_quantity'),
    ('market_value', 'th_value_ils'),
    ('cost_basis', 'th_cost_ils'),
    ('unrealized_pnl', 'th_pnl_ils'),
    ('unrealized_pnl_pct', 'th_pnl_pct'),
    ('weight', 'th_weight'),
]

TRANSACTIONS_COLUMNS = [
    ('date', 'th_date'),
    ('action_label', 'th_action'),
    ('amount', 'th_amount'),
    ('balance', 'th_balance'),
    ('cost_change_pct_display', 'th_cost_change_pct'),
    ('cost_change_ils', 'th_cost_change_ils'),
    ('notes', 'th_notes'),
]

TRADES_COLUMNS = [
    ('date', 'th_date'),
    ('type', 'th_trade_action'),
    ('position_type', 'th_trade_type'),
    ('name_he', 'th_name'),
    ('name_en', 'export_name_en'),
    ('symbol', 'th_symbol'),
    ('ticker', 'export_ticker_en'),
    ('shares', 'th_quantity'),
    ('price_per_share', 'th_price_ils'),
    ('total_amount', 'th_amount_ils'),
    ('realized_pnl', 'th_pnl_ils'),
]

CLOSED_COLUMNS = [
    ('name_he', 'th_name'),
    ('name_en', 'export_name_en'),
    ('symbol', 'th_symbol'),
    ('ticker', 'export_ticker_en'),
    ('security_type', 'th_trade_type'),
    ('total_shares', 'th_quantity'),
    ('avg_buy_price', 'th_avg_buy'),
    ('avg_sell_price', 'th_avg_sell'),
    ('total_pnl', 'th_pnl_ils'),
    ('pnl_pct', 'th_pnl_pct'),
    ('period', 'th_period'),
]

DAILY_SUMMARY_COLUMNS = [
    ('date', 'th_date'),
    ('morning_value', 'th_morning_value'),
    ('current_value', 'th_current_value'),
    ('deposits', 'th_deposits'),
    ('daily_pnl', 'th_daily_pnl'),
    ('change_pct', 'th_change_pct'),
    ('best_ticker', 'th_best_stock'),
    ('best_pnl_ils', 'export_best_pnl_ils'),
    ('best_pnl_pct', 'export_best_pnl_pct'),
    ('worst_ticker', 'th_worst_stock'),
    ('worst_pnl_ils', 'export_worst_pnl_ils'),
    ('worst_pnl_pct', 'export_worst_pnl_pct'),
]

DAILY_DETAILS_COLUMNS = [
    ('date', 'th_date'),
    ('security_type', 'label_type'),
    ('name', 'th_name'),
    ('name_en', 'export_name_en'),
    ('tase_id', 'th_tase_id'),
    ('symbol', 'th_symbol'),
    ('ticker', 'export_ticker_en'),
    ('change_ils', 'th_change_ils'),
    ('change_pct', 'th_change_pct_col'),
]

COLUMN_MAP = {
    'portfolio': PORTFOLIO_COLUMNS,
    'transactions': TRANSACTIONS_COLUMNS,
    'trades': TRADES_COLUMNS,
    'closed': CLOSED_COLUMNS,
    'daily-summary': DAILY_SUMMARY_COLUMNS,
    'daily-details': DAILY_DETAILS_COLUMNS,
}


def _flatten_daily_summary(data, lang='he'):
    """Flatten nested best/worst dicts in daily summary rows.

    Args:
        data: Daily summary data with best/worst nested dicts
        lang: Language code ('en' or 'he') for ticker selection
    """
    flat = []
    for row in data:
        r = dict(row)
        best = r.pop('best', None) or {}
        worst = r.pop('worst', None) or {}

        # Language-aware ticker selection
        if lang == 'en':
            r['best_ticker'] = best.get('ticker_en') or best.get('symbol', '')
            r['worst_ticker'] = worst.get('ticker_en') or worst.get('symbol', '')
        else:
            r['best_ticker'] = best.get('symbol', '')
            r['worst_ticker'] = worst.get('symbol', '')

        r['best_pnl_ils'] = best.get('daily_pnl', '')
        r['best_pnl_pct'] = best.get('daily_pnl_pct', '')
        r['worst_pnl_ils'] = worst.get('daily_pnl', '')
        r['worst_pnl_pct'] = worst.get('daily_pnl_pct', '')
        flat.append(r)
    return flat


def _enrich_portfolio(positions):
    """Add computed unrealized_pnl and unrealized_pnl_pct columns."""
    enriched = []
    for pos in positions:
        r = dict(pos)
        cb = r.get('cost_basis', 0) or 0
        mv = r.get('market_value', 0) or 0
        r['unrealized_pnl'] = mv - cb
        r['unrealized_pnl_pct'] = (r['unrealized_pnl'] / cb * 100) if cb else 0
        enriched.append(r)
    return enriched


def _transform_transactions(data):
    """Convert action keys and format cost_change_pct for display."""
    transformed = []
    for row in data:
        r = dict(row)
        r['action_label'] = r.get('action', '')
        pct = r.get('cost_change_pct')
        r['cost_change_pct_display'] = round(pct * 100, 3) if pct is not None else None
        transformed.append(r)
    return transformed


def build_dataframe(view, data, lang='he'):
    """Build a pandas DataFrame for the given view with translated headers."""
    t = get_translations(lang)
    columns = COLUMN_MAP.get(view)
    if not columns:
        return pd.DataFrame()

    if view == 'daily-summary':
        data = _flatten_daily_summary(data, lang)
    elif view == 'portfolio':
        data = _enrich_portfolio(data)
    elif view == 'transactions':
        data = _transform_transactions(data)

    field_names = [c[0] for c in columns]
    headers = [t.get(c[1], c[1]) for c in columns]

    rows = []
    for record in data:
        rows.append([record.get(f, '') for f in field_names])

    return pd.DataFrame(rows, columns=headers)


def make_excel_response(df, filename):
    """Create a Flask Response with an Excel file attachment."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    buf.seek(0)

    return Response(
        buf.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


def make_csv_response(df, filename):
    """Create a Flask Response with a UTF-8 BOM CSV file."""
    buf = io.StringIO()
    buf.write('\ufeff')  # UTF-8 BOM for Excel compatibility
    df.to_csv(buf, index=False)

    return Response(
        buf.getvalue().encode('utf-8'),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


def build_tax_report(lang='he'):
    """Build a multi-sheet Excel tax report workbook."""
    from app.analytics import compute_yearly_tax, get_trade_history, get_closed_positions

    t = get_translations(lang)
    by_year, years = compute_yearly_tax()
    trades = get_trade_history()
    sells = [tr for tr in trades if tr.get('type') == 'sell']
    closed = get_closed_positions()

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        # Sheet 1: Yearly Summary
        summary_rows = []
        for year in years:
            y = by_year[year]
            summary_rows.append({
                t.get('label_tax_year', 'Tax Year'): year,
                t.get('stat_gains', 'Gains'): y['total_gains'],
                t.get('stat_losses', 'Losses'): y['total_losses'],
                t.get('stat_net_balance', 'Net'): y['net_pnl'],
                t.get('stat_loss_carryover', 'Carryover'): y['loss_carryover_in'],
                t.get('export_taxable', 'Taxable'): y['taxable'],
                t.get('stat_net_tax', 'Net Tax'): y['net_tax'],
            })
        sheet_summary = t.get('export_sheet_summary', 'Summary')
        pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name=sheet_summary[:31])

        # Sheet 2: Sell Trades
        sells_df = build_dataframe('trades', sells, lang)
        sheet_sells = t.get('export_sheet_sells', 'Sell Trades')
        sells_df.to_excel(writer, index=False, sheet_name=sheet_sells[:31])

        # Sheet 3: Closed Positions
        closed_df = build_dataframe('closed', closed, lang)
        sheet_closed = t.get('export_sheet_closed', 'Closed Positions')
        closed_df.to_excel(writer, index=False, sheet_name=sheet_closed[:31])

    buf.seek(0)
    year_range = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0]) if years else 'empty'
    filename = f"tax_report_{year_range}.xlsx"

    return Response(
        buf.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
