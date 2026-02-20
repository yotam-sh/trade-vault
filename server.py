"""Flask server for the HTML frontend."""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response
from app.connection import get_db, close_db, flush_db
from app.settings import init_default_settings
from app.importers import import_daily_portfolio
from app.transactions import add_deposit, add_withdrawal
from app.i18n import get_translations, get_translations_json, t as _t
from app.analytics import (
    get_portfolio_value,
    get_transaction_log,
    get_transaction_summary,
    get_daily_summary,
    get_daily_details,
    get_pivot_by_security,
    get_pivot_by_date,
    get_trade_history,
    get_closed_positions,
    compute_yearly_tax,
)

app = Flask(__name__)
app.secret_key = 'tradevault-dev-key'

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'daily_data')

# Month names for folder naming
MONTH_NAMES = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec',
}


def _get_lang():
    """Read language from cookie, default to Hebrew."""
    return request.cookies.get('lang', 'he')


@app.context_processor
def inject_translations():
    """Make t, lang, dir, and t_json available in every template."""
    lang = _get_lang()
    return {
        't': get_translations(lang),
        't_json': get_translations_json(lang),
        'lang': lang,
        'dir': 'ltr' if lang == 'en' else 'rtl',
    }


@app.before_request
def ensure_db():
    get_db()
    init_default_settings()


@app.teardown_appcontext
def shutdown_db(exception=None):
    pass  # DB stays open for the app's lifetime; flushed via atexit


@app.route('/set-lang/<lang>')
def set_lang(lang):
    """Switch UI language and redirect back."""
    if lang not in ('he', 'en'):
        lang = 'he'
    referrer = request.referrer or url_for('index')
    resp = make_response(redirect(referrer))
    resp.set_cookie('lang', lang, max_age=365 * 24 * 3600)
    return resp


@app.route('/')
def index():
    portfolio = get_portfolio_value()
    return render_template('index.html', portfolio=portfolio)


@app.route('/upload', methods=['POST'])
def upload_daily():
    """Upload a daily portfolio Excel file, save to data/daily_data/<month>/, and import."""
    lang = _get_lang()
    file = request.files.get('file')
    date_str = request.form.get('date')

    if not file or not file.filename:
        flash(_t('flash_no_file', lang), 'error')
        return redirect(url_for('index'))

    if not date_str:
        flash(_t('flash_no_date', lang), 'error')
        return redirect(url_for('index'))

    # Validate date
    try:
        data_date = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        flash(_t('flash_invalid_date', lang), 'error')
        return redirect(url_for('index'))

    # Build target folder: data/daily_data/<mon>_<year>/
    month_folder = f"{MONTH_NAMES[data_date.month]}_{data_date.year}"
    target_dir = os.path.join(DATA_DIR, month_folder)
    os.makedirs(target_dir, exist_ok=True)

    # Build filename: data_<YYYY-MM-DD>.xlsx
    safe_name = f"data_{date_str}.xlsx"
    target_path = os.path.join(target_dir, safe_name)

    # Save the uploaded file
    file.save(target_path)

    # Import into database
    try:
        result = import_daily_portfolio(target_path, data_date=date_str)
        if result['status'] == 'duplicate':
            flash(f"{_t('flash_duplicate', lang)} ({date_str})", 'warning')
        else:
            imported = result['rows_imported']
            new_h = result['new_holdings']
            flash(_t('flash_import_success', lang, rows=imported, new=new_h, date=date_str), 'success')
    except Exception as e:
        flash(f"{_t('flash_import_error', lang)}: {str(e)}", 'error')

    flush_db()
    return redirect(url_for('index'))


@app.route('/transactions')
def transactions_view():
    start = request.args.get('start')
    end = request.args.get('end')
    log = get_transaction_log()
    # Show deposits, withdrawals, and monthly summaries (not buy/sell trades)
    log = [e for e in log if e['action'] in ('deposit', 'withdrawal', 'month_summary')]
    if start:
        log = [e for e in log if e.get('date', '') >= start]
    if end:
        log = [e for e in log if e.get('date', '') <= end]
    summary = get_transaction_summary()

    # Net tax from current year (with loss carryover)
    by_year, _ = compute_yearly_tax()
    current_year = datetime.now().year
    year_tax = by_year.get(current_year, {})
    summary['net_tax'] = year_tax.get('net_tax', 0)

    return render_template('transactions.html', log=log, summary=summary,
                           start=start, end=end)


@app.route('/add-deposit', methods=['POST'])
def add_deposit_route():
    """Add a deposit via the web form."""
    lang = _get_lang()
    amount_str = request.form.get('amount', '').strip()
    date_str = request.form.get('date', '').strip()

    if not amount_str:
        flash(_t('flash_no_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    if not date_str:
        flash(_t('flash_no_date', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        amount = float(amount_str)
    except ValueError:
        flash(_t('flash_invalid_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        flash(_t('flash_invalid_date', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        add_deposit(date=date_str, amount=amount)
        flash(_t('flash_deposit_success', lang, amount=f'{amount:,.0f}', date=date_str), 'success')
    except Exception as e:
        flash(f"{_t('flash_deposit_error', lang)}: {str(e)}", 'error')

    flush_db()
    return redirect(url_for('transactions_view'))


@app.route('/add-withdrawal', methods=['POST'])
def add_withdrawal_route():
    """Add a withdrawal via the web form."""
    lang = _get_lang()
    amount_str = request.form.get('amount', '').strip()
    date_str = request.form.get('date', '').strip()

    if not amount_str:
        flash(_t('flash_no_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    if not date_str:
        flash(_t('flash_no_date', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        amount = float(amount_str)
    except ValueError:
        flash(_t('flash_invalid_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        flash(_t('flash_invalid_date', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        add_withdrawal(date=date_str, amount=amount)
        flash(_t('flash_withdrawal_success', lang, amount=f'{amount:,.0f}', date=date_str), 'success')
    except Exception as e:
        flash(f"{_t('flash_withdrawal_error', lang)}: {str(e)}", 'error')

    flush_db()
    return redirect(url_for('transactions_view'))


@app.route('/daily-summary')
def daily_summary_view():
    start = request.args.get('start')
    end = request.args.get('end')
    data = get_daily_summary(start_date=start, end_date=end)
    return render_template('daily_summary.html', data=data, start=start, end=end)


@app.route('/daily-details')
def daily_details_view():
    start = request.args.get('start')
    end = request.args.get('end')

    # Default to the latest available day when no dates are specified
    if not start and not end:
        from app.daily_prices import list_dates
        dates = list_dates()
        if dates:
            start = end = dates[-1]

    details = get_daily_details(start_date=start, end_date=end)
    pivot_security = get_pivot_by_security(start_date=start, end_date=end)
    pivot_date = get_pivot_by_date(start_date=start, end_date=end)
    return render_template('daily_details.html',
                           details=details,
                           pivot_security=pivot_security,
                           pivot_date=pivot_date,
                           start=start, end=end)


# API endpoints for AJAX filtering
@app.route('/api/daily-details')
def api_daily_details():
    start = request.args.get('start')
    end = request.args.get('end')
    details = get_daily_details(start_date=start, end_date=end)
    pivot_security = get_pivot_by_security(start_date=start, end_date=end)
    pivot_date = get_pivot_by_date(start_date=start, end_date=end)
    return jsonify({
        'details': details,
        'pivot_security': pivot_security,
        'pivot_date': pivot_date,
    })


@app.route('/trades')
def trades_view():
    # Yearly tax with loss carryover
    by_year, tax_years = compute_yearly_tax()
    current_year = datetime.now().year
    year_param = request.args.get('year', str(current_year))
    selected_year = 'all' if year_param == 'all' else int(year_param)

    # Date picker overrides year bounds; otherwise default to selected year
    if selected_year == 'all':
        start = request.args.get('start')
        end = request.args.get('end')
    else:
        start = request.args.get('start') or f'{selected_year}-01-01'
        end = request.args.get('end') or f'{selected_year}-12-31'
    trades = get_trade_history(start_date=start, end_date=end)
    closed = get_closed_positions()

    if selected_year == 'all':
        # Aggregate across all years
        all_gains = sum(y['total_gains'] for y in by_year.values())
        all_losses = sum(y['total_losses'] for y in by_year.values())
        all_net = all_gains + all_losses
        last_year = by_year[tax_years[-1]] if tax_years else {}
        sales_summary = {
            'year': 'all', 'total_gains': all_gains, 'total_losses': all_losses,
            'net_pnl': all_net, 'loss_carryover_in': 0, 'taxable': max(0, all_net),
            'loss_carryover_out': last_year.get('loss_carryover_out', 0),
            'tax_on_gains': all_gains * 0.25,
            'tax_offset_from_losses': abs(all_losses) * 0.25,
            'net_tax': max(0, all_net * 0.25),
        }
    else:
        sales_summary = by_year.get(selected_year, {
            'year': selected_year, 'total_gains': 0, 'total_losses': 0,
            'net_pnl': 0, 'loss_carryover_in': 0, 'taxable': 0,
            'loss_carryover_out': 0, 'tax_on_gains': 0,
            'tax_offset_from_losses': 0, 'net_tax': 0,
        })

    return render_template('trades.html', trades=trades, closed=closed,
                           sales_summary=sales_summary, tax_years=tax_years,
                           selected_year=selected_year,
                           start=start, end=end)


# ── Export routes ──
from app.export import build_dataframe, make_excel_response, make_csv_response, build_tax_report


@app.route('/export/tax-report')
def export_tax_report():
    """Export multi-sheet yearly tax report as Excel."""
    lang = _get_lang()
    return build_tax_report(lang)


@app.route('/export/<view>')
def export_view(view):
    """Export any page's data as Excel or CSV."""
    lang = _get_lang()
    fmt = request.args.get('format', 'xlsx')
    start = request.args.get('start')
    end = request.args.get('end')

    if view == 'portfolio':
        portfolio = get_portfolio_value()
        data = portfolio['positions'] if portfolio else []
        date_label = portfolio['date'] if portfolio else 'empty'
        filename = f"portfolio_{date_label}"
    elif view == 'transactions':
        data = get_transaction_log()
        data = [e for e in data if e['action'] in ('deposit', 'withdrawal', 'month_summary')]
        if start:
            data = [e for e in data if e.get('date', '') >= start]
        if end:
            data = [e for e in data if e.get('date', '') <= end]
        filename = 'transactions'
    elif view == 'trades':
        data = get_trade_history(start_date=start, end_date=end)
        filename = 'trades'
    elif view == 'daily-summary':
        data = get_daily_summary(start_date=start, end_date=end)
        filename = 'daily_summary'
    elif view == 'daily-details':
        data = get_daily_details(start_date=start, end_date=end)
        filename = 'daily_details'
    else:
        return 'Unknown view', 404

    df = build_dataframe(view, data, lang)

    if start and end:
        filename += f"_{start}_to_{end}"
    elif start:
        filename += f"_from_{start}"

    if fmt == 'csv':
        return make_csv_response(df, f"{filename}.csv")
    return make_excel_response(df, f"{filename}.xlsx")


if __name__ == '__main__':
    print("Starting TradeVault server on http://localhost:5000")
    app.run(host="0.0.0.0", debug=True, port=5000)
