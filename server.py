"""Flask server for the HTML frontend."""

import sys
import os
import re
import math
import hmac
import signal
import functools
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response, send_file, Response, g
from flask_wtf.csrf import CSRFProtect
from app.connection import get_db, close_db, flush_db
from app.settings import init_default_settings
from app.importers import import_daily_portfolio
from app.transactions import add_deposit, add_withdrawal, add_dividend
from app.i18n import get_translations, get_translations_json, t as _t
from app.analytics import (
    get_portfolio_value,
    get_transaction_log,
    get_transaction_summary,
    get_monthly_chart_data,
    get_daily_summary,
    get_daily_details,
    get_pivot_by_security,
    get_daily_type_chart_data,
    get_pivot_by_date,
    get_trade_history,
    get_closed_positions,
    compute_yearly_tax,
    compute_potential_tax,
    get_position_data,
    get_positions_list,
    get_historical_performance,
    get_allocation_history,
    get_top_positions_pnl,
)

from app.lib_check import startup_check

_secret_key = os.environ.get('SECRET_KEY', '')
_insecure_default = 'tradevault-dev-key-change-in-production'
_is_production = os.environ.get('TRADEVAULT_ENV', '').lower() == 'production'
if not _secret_key or _secret_key == _insecure_default:
    if _is_production:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set or is using the insecure default. "
            "Set a strong random value (e.g. `python -c 'import secrets; print(secrets.token_hex(32))'`) "
            "in the SECRET_KEY environment variable before starting in production."
        )
    import secrets as _secrets
    _secret_key = _secrets.token_hex(32)
    print(
        "WARNING: SECRET_KEY not set. Using a temporary random key — sessions will reset on restart. "
        "Set SECRET_KEY environment variable for persistent sessions.",
        file=sys.stderr,
    )

app = Flask(__name__)
app.secret_key = _secret_key
app.config['WTF_CSRF_TIME_LIMIT'] = None  # tokens don't expire within session
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB upload limit
debug_mode = os.environ.get('DEBUG', 'false').lower() == 'true'
app.jinja_env.auto_reload = debug_mode

csrf = CSRFProtect(app)

# ── Jinja2 template filters ───────────────────────────────────────────────────
from app.i18n import format_date as _format_date
app.add_template_filter(_format_date, 'format_date')

# ── SIGTERM handler ───────────────────────────────────────────────────────────
# Flush TinyDB's CachingMiddleware write cache before the process exits.
# atexit covers graceful shutdown (Ctrl+C, gunicorn --graceful-timeout), but
# SIGTERM (e.g. `kill <pid>`) bypasses atexit on some platforms.

def _handle_sigterm(signum, frame):
    flush_db()
    close_db()
    sys.exit(0)

try:
    signal.signal(signal.SIGTERM, _handle_sigterm)
except (OSError, ValueError):
    pass  # Windows restricts signal registration to the main thread


# ── One-time startup ──────────────────────────────────────────────────────────
_startup_done = False


def _run_startup():
    """Run one-time startup tasks: lib-update check, DB open, default settings.

    Called from wsgi.py (production) and from the ``if __name__ == '__main__':``
    block (dev server).  Guarded by _startup_done so it is idempotent even if
    the WSGI loader imports the module more than once.
    """
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    startup_check()
    get_db()
    init_default_settings()

    # I18N-M4: assert every TRANSLATIONS key has both 'he' and 'en' entries
    from app.i18n import TRANSLATIONS as _TRANSLATIONS
    _bad_keys = [
        f"'{k}' missing {', '.join(l for l in ('he', 'en') if l not in v)}"
        for k, v in _TRANSLATIONS.items()
        if not isinstance(v, dict) or 'he' not in v or 'en' not in v
    ]
    if _bad_keys:
        _i18n_msg = 'TRANSLATIONS incomplete: ' + '; '.join(_bad_keys)
        if _is_production:
            raise RuntimeError(_i18n_msg)
        app.logger.warning(_i18n_msg)

    # Repair historical snapshots whose net_invested was stored as 0
    # because deposits were imported after the snapshot was first written.
    from app.snapshots import repair_net_invested as _repair_ni
    _repaired = _repair_ni()
    if _repaired:
        app.logger.info('net_invested repaired on %d historical snapshot(s)', _repaired)

    # Repair lot states that were reset by a DB import (is_closed=False, realized_pnl=0
    # even though sell transactions exist against them).
    from app.tax_lots import repair_lot_states as _repair_lots
    _lots_repaired = _repair_lots()
    if _lots_repaired:
        app.logger.info('lot state repaired on %d tax lot(s)', _lots_repaired)


# ── Background TASE refresh state ─────────────────────────────────────────────
_tase_lock = threading.Lock()
_tase_status: dict = {'running': False, 'updated': 0, 'failed': 0, 'done': True}


DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'daily_data')

# Month names for folder naming
MONTH_NAMES = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec',
}


def _get_lang():
    """Read language from cookie, default to Hebrew."""
    return request.cookies.get('lang', 'he')


# ── Admin authentication ──────────────────────────────────────────────────────

_ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')


def _check_admin_auth():
    """Return True if the request carries valid admin credentials."""
    auth = request.authorization
    if not auth or not _ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(auth.password, _ADMIN_PASSWORD)


def require_admin(f):
    """Decorator: protect a route with HTTP Basic Auth using ADMIN_PASSWORD env var."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not _ADMIN_PASSWORD:
            # No password configured — block all access rather than allow all
            return Response(
                'Admin access is disabled. Set ADMIN_PASSWORD environment variable.',
                403,
            )
        if not _check_admin_auth():
            return Response(
                'Authentication required.',
                401,
                {'WWW-Authenticate': 'Basic realm="TradeVault Admin"'},
            )
        return f(*args, **kwargs)
    return decorated


APP_VERSION = '0.8.7'


_DEFAULT_DISPLAY_PREFS_HE = {
    'portfolio_holdings_name':   'name_tase_he',
    'portfolio_holdings_symbol': 'symbol',
    'positions_open_name':       'name_tase_he',
    'positions_open_symbol':     'symbol',
    'positions_closed_name':     'name_tase_he',
    'positions_closed_symbol':   'symbol',
    'daily_summary_best_worst':  'symbol',
    'daily_details_name':        'name_tase_he',
    'daily_details_symbol':      'symbol',
    'rebalance_name':            'name_tase_he',
    'trades_name':               'name_tase_he',
    'trades_symbol':             'symbol',
    'trades_closed_name':        'name_tase_he',
    'graphs_pnl_labels':         'symbol',
    'graphs_treemap_labels':     'symbol',
}

_DEFAULT_DISPLAY_PREFS_EN = {
    'portfolio_holdings_name':   'name_tase_en',
    'portfolio_holdings_symbol': 'symbol_en',
    'positions_open_name':       'name_tase_en',
    'positions_open_symbol':     'symbol_en',
    'positions_closed_name':     'name_tase_en',
    'positions_closed_symbol':   'symbol_en',
    'daily_summary_best_worst':  'symbol_en',
    'daily_details_name':        'name_tase_en',
    'daily_details_symbol':      'symbol_en',
    'rebalance_name':            'name_tase_en',
    'trades_name':               'name_tase_en',
    'trades_symbol':             'symbol_en',
    'trades_closed_name':        'name_tase_en',
    'graphs_pnl_labels':         'symbol_en',
    'graphs_treemap_labels':     'symbol_en',
}


def _default_display_prefs(lang):
    return _DEFAULT_DISPLAY_PREFS_HE if lang == 'he' else _DEFAULT_DISPLAY_PREFS_EN


@app.context_processor
def inject_translations():
    """Make t, lang, dir, t_json, app_version, and display_prefs available in every template."""
    from app.settings import get_setting
    lang = _get_lang()
    if not hasattr(g, 'display_prefs'):
        saved_all = get_setting('display_name_prefs', {}) or {}
        saved_prefs = saved_all.get(lang, {}) if isinstance(saved_all, dict) else {}
        g.display_prefs = {**_default_display_prefs(lang), **saved_prefs}
    return {
        't': get_translations(lang),
        't_json': get_translations_json(lang),
        'lang': lang,
        'dir': 'ltr' if lang == 'en' else 'rtl',
        'app_version': APP_VERSION,
        'display_prefs': g.display_prefs,
    }


@app.before_request
def ensure_db():
    get_db()


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
    resp.set_cookie('lang', lang, max_age=365 * 24 * 3600, samesite='Lax')
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

    # Validate file extension
    if not file.filename.lower().endswith(('.xlsx', '.xls')):
        flash(_t('flash_invalid_file_type', lang), 'error')
        return redirect(url_for('index'))

    # Warn if the date embedded in the filename doesn't match the form date
    _fn_date = re.search(r'\d{4}-\d{2}-\d{2}', file.filename)
    if _fn_date and date_str and _fn_date.group() != date_str:
        flash(_t('flash_date_filename_mismatch', lang,
                 filename_date=_fn_date.group(), form_date=date_str), 'warning')

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
    except Exception:
        app.logger.exception('Daily import failed for %s', date_str)
        flash(_t('flash_import_error', lang), 'error')

    flush_db()
    return redirect(url_for('index'))


@app.route('/transactions')
def transactions_view():
    from app.snapshots import list_snapshots
    start = request.args.get('start')
    end = request.args.get('end')
    log = get_transaction_log()
    # Show deposits, withdrawals, dividends, and monthly summaries (not buy/sell trades)
    log = [e for e in log if e['action'] in ('deposit', 'withdrawal', 'dividend', 'month_summary')]
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

    snapshots = sorted(list_snapshots(), key=lambda s: s['date'])
    allocation_history = get_allocation_history()
    from app.transactions import list_transactions as _list_txns
    deposit_dates = [d['date'] for d in _list_txns(type_='deposit')]

    return render_template('transactions.html', log=log, summary=summary,
                           start=start, end=end, snapshots=snapshots,
                           allocation_history=allocation_history,
                           deposit_dates=deposit_dates)


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

    if not math.isfinite(amount) or amount <= 0:
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
    except Exception:
        app.logger.exception('Add deposit failed')
        flash(_t('flash_deposit_error', lang), 'error')

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

    if not math.isfinite(amount) or amount <= 0:
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
    except Exception:
        app.logger.exception('Add withdrawal failed')
        flash(_t('flash_withdrawal_error', lang), 'error')

    flush_db()
    return redirect(url_for('transactions_view'))


@app.route('/add-dividend', methods=['POST'])
def add_dividend_route():
    """Add a dividend income entry via the web form."""
    lang = _get_lang()
    amount_str = request.form.get('amount', '').strip()
    date_str = request.form.get('date', '').strip()
    ticker = request.form.get('ticker', '').strip() or None
    tax_str = request.form.get('tax', '').strip()
    notes = request.form.get('notes', '').strip() or None

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

    if not math.isfinite(amount) or amount <= 0:
        flash(_t('flash_invalid_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        flash(_t('flash_invalid_date', lang), 'error')
        return redirect(url_for('transactions_view'))

    tax = 0.0
    if tax_str:
        try:
            tax = float(tax_str)
            if not math.isfinite(tax) or tax < 0:
                tax = 0.0
        except ValueError:
            tax = 0.0

    # Resolve holding_id from ticker if provided
    holding_id = None
    if ticker:
        from app.holdings import list_holdings
        for h in list_holdings(active_only=False):
            if (h.get('ticker') or '').upper() == ticker.upper() or \
               (h.get('tase_symbol') or '').upper() == ticker.upper():
                holding_id = h.doc_id
                break

    try:
        add_dividend(
            date=date_str, amount=amount,
            ticker=ticker, holding_id=holding_id,
            tax=tax if tax else None,
            notes=notes,
        )
        flash(_t('flash_dividend_success', lang,
                 amount=f'{amount:,.0f}', date=date_str), 'success')
    except Exception:
        app.logger.exception('Add dividend failed')
        flash(_t('flash_dividend_error', lang), 'error')

    flush_db()
    return redirect(url_for('transactions_view'))


@app.route('/daily-summary')
def daily_summary_view():
    start = request.args.get('start')
    end = request.args.get('end')
    if not start and not end:
        today = datetime.now().date()
        start = today.strftime('%Y-%m-01')
        end = today.strftime('%Y-%m-%d')
        return redirect(url_for('daily_summary_view') + f'?start={start}&end={end}')
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
    type_chart = get_daily_type_chart_data(start_date=start, end_date=end)
    return render_template('daily_details.html',
                           details=details,
                           pivot_security=pivot_security,
                           pivot_date=pivot_date,
                           type_chart=type_chart,
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


@app.route('/api/transactions/<int:doc_id>/update-price', methods=['POST'])
def update_transaction_price_route(doc_id):
    """Update the price_per_share of a transaction (typically interpolated)."""
    from app.transactions import update_transaction_price
    data = request.get_json(silent=True) or {}
    try:
        price = float(data.get('price_per_share', ''))
    except (ValueError, TypeError):
        return jsonify({'error': 'invalid price'}), 400
    if price <= 0:
        return jsonify({'error': 'price must be positive'}), 400
    ok = update_transaction_price(doc_id, price)
    if not ok:
        return jsonify({'error': 'transaction not found'}), 404
    flush_db()
    return jsonify({'success': True})


@app.route('/api/transactions/<int:doc_id>/delete', methods=['POST'])
def delete_transaction_route(doc_id):
    """Delete a transaction (and its linked tax lot if it was an interpolated buy)."""
    from app.transactions import delete_transaction
    ok = delete_transaction(doc_id)
    if not ok:
        return jsonify({'error': 'transaction not found'}), 404
    flush_db()
    return jsonify({'success': True})


@app.route('/trades')
def trades_view():
    year_param  = request.args.get('year')
    start_param = request.args.get('start')
    end_param   = request.args.get('end')
    if not year_param and not start_param and not end_param:
        today = datetime.now().date()
        _start = today.strftime('%Y-%m-01')
        _end   = today.strftime('%Y-%m-%d')
        return redirect(url_for('trades_view') + f'?start={_start}&end={_end}')

    # Yearly tax with loss carryover
    by_year, tax_years = compute_yearly_tax()
    current_year = datetime.now().year
    selected_year = 'all' if not year_param or year_param == 'all' else int(year_param)

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

    potential_tax_data = compute_potential_tax()

    raw_open = get_positions_list()['open']
    open_positions = []
    for pos in raw_open:
        pnl = pos['unrealized_pnl']
        days = pos.get('days_holding')
        if days is None:
            duration = '—'
        elif days >= 730:
            y, m = days // 365, (days % 365) // 30
            duration = f'{y}y {m}m' if m else f'{y}y'
        elif days >= 365:
            m = (days % 365) // 30
            duration = f'1y {m}m' if m else '1y'
        elif days >= 30:
            duration = f'{days // 30}m'
        else:
            duration = f'{days}d'
        open_positions.append({
            **pos,
            'holding_duration': duration,
            'days_holding': days or 0,
            'potential_tax':  round(max(0,  pnl) * 0.25, 2),
            'loss_offset':    round(max(0, -pnl) * 0.25, 2),
        })

    return render_template('trades.html', trades=trades, closed=closed,
                           sales_summary=sales_summary, tax_years=tax_years,
                           selected_year=selected_year,
                           start=start, end=end,
                           potential_tax_data=potential_tax_data,
                           open_positions=open_positions)


@app.route('/api/graph-layout', methods=['GET'])
def get_graph_layout():
    from app.settings import get_setting
    layout = get_setting('graph_layout', {
        'order': ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
        'widths': {'A': 100, 'B': 100, 'C': 100, 'D': 100, 'E': 100, 'F': 100, 'G': 100},
        'hidden': [],
        'locked': [],
    })
    return jsonify(layout)


@app.route('/api/graph-layout', methods=['POST'])
def save_graph_layout():
    from app.settings import set_setting
    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({'error': 'Invalid JSON'}), 400
    set_setting('graph_layout', data)
    flush_db()
    return jsonify({'ok': True})


@app.route('/graphs')
def graphs_view():
    from app.snapshots import list_snapshots
    from app.settings import get_setting
    from app.analytics.benchmark_analytics import get_benchmark_data
    snapshots = list_snapshots()
    monthly = get_monthly_chart_data()
    historical_perf = get_historical_performance()
    allocation_history = get_allocation_history()
    top_positions = get_top_positions_pnl()
    graph_layout = get_setting('graph_layout', {
        'order': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
        'widths': {'A': 100, 'B': 100, 'C': 100, 'D': 100, 'E': 100, 'F': 100, 'G': 100, 'H': 100},
        'hidden': [],
        'locked': [],
    })

    snap_dates = [s['date'] for s in snapshots]
    try:
        benchmark = get_benchmark_data(snap_dates)
    except Exception:
        app.logger.exception('Benchmark fetch failed')
        benchmark = {'ta125': [], 'ta35': []}

    # Extra data for shared chart partials
    daily_data = get_daily_summary()
    type_chart = get_daily_type_chart_data()
    portfolio = get_portfolio_value()
    closed = get_closed_positions()
    by_year, _ = compute_yearly_tax()
    current_year = datetime.now().year
    year_data = by_year.get(current_year, {})
    sales_summary = year_data if year_data.get('total_gains', 0) > 0 else None

    from app.transactions import list_transactions
    deposit_dates = [d['date'] for d in list_transactions(type_='deposit')]
    potential_tax_data = compute_potential_tax()

    return render_template(
        'graphs.html',
        snapshots=snapshots,
        monthly=monthly,
        historical_perf=historical_perf,
        allocation_history=allocation_history,
        top_positions=top_positions,
        graph_layout=graph_layout,
        benchmark=benchmark,
        data=daily_data,
        type_chart=type_chart,
        portfolio=portfolio,
        closed=closed,
        sales_summary=sales_summary,
        deposit_dates=deposit_dates,
        potential_tax_data=potential_tax_data,
    )


# ── Position routes ──

@app.route('/positions')
def positions_view():
    data = get_positions_list()
    return render_template('positions.html', data=data)


@app.route('/rebalance')
def rebalance_view():
    from app.analytics.portfolio_analytics import get_portfolio_value
    from app.settings import get_setting
    pf = get_portfolio_value()
    saved = get_setting('target_allocations_v2', {}) or {}
    group_targets = saved.get('groups', {})
    holding_targets = saved.get('holdings', {})
    total_value = pf.get('total_value', 0) or 0

    TYPE_ORDER = ['stock', 'mutual_fund', 'etf', 'bond', 'other']

    # Group positions by security_type
    type_groups = {}
    for pos in (pf.get('positions') or []):
        st = pos.get('security_type') or 'other'
        if st not in TYPE_ORDER:
            st = 'other'
        type_groups.setdefault(st, []).append(pos)

    group_data = []
    for stype in TYPE_ORDER:
        positions = type_groups.get(stype, [])
        if not positions:
            continue

        group_value = sum(p.get('market_value', 0) or 0 for p in positions)
        current_group_pct = round(group_value / total_value * 100, 2) if total_value else 0
        target_group_pct = float(group_targets.get(stype, 0))
        group_delta = round(current_group_pct - target_group_pct, 2)
        target_group_value = target_group_pct / 100 * total_value

        # Group-level action ILS
        group_action_ils = round(abs(group_delta / 100 * total_value), 0)
        if group_delta > 0.1:
            group_action = 'sell'
        elif group_delta < -0.1:
            group_action = 'buy'
        else:
            group_action = 'hold'

        holding_rows = []
        for pos in positions:
            hid = str(pos['holding_id'])
            mv = pos.get('market_value', 0) or 0
            current_in_group = round(mv / group_value * 100, 2) if group_value else 0
            target_in_group = float(holding_targets.get(hid, 0))
            delta_in_group = round(current_in_group - target_in_group, 2)
            target_holding_value = target_in_group / 100 * target_group_value
            action_ils = round(abs(mv - target_holding_value), 0)
            if delta_in_group > 0.1:
                action = 'sell'
            elif delta_in_group < -0.1:
                action = 'buy'
            else:
                action = 'hold'
            holding_rows.append({
                **pos,
                'current_in_group': current_in_group,
                'target_in_group': target_in_group,
                'delta_in_group': delta_in_group,
                'action_ils': action_ils,
                'action': action,
            })

        holding_rows.sort(key=lambda r: r['delta_in_group'])

        group_data.append({
            'type': stype,
            'current_pct': current_group_pct,
            'target_pct': target_group_pct,
            'delta_pct': group_delta,
            'group_value': round(group_value, 0),
            'group_action': group_action,
            'group_action_ils': group_action_ils,
            'holdings': holding_rows,
        })

    total_group_targeted = round(sum(float(v) for v in group_targets.values()), 2)

    return render_template('rebalance.html',
        group_data=group_data,
        total_value=total_value,
        total_group_targeted=total_group_targeted,
    )


@app.route('/api/rebalance-targets', methods=['POST'])
def save_rebalance_targets():
    from app.settings import set_setting
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'invalid json'}), 400

    VALID_TYPES = {'stock', 'mutual_fund', 'etf', 'bond', 'other'}
    groups = {}
    for k, v in (data.get('groups') or {}).items():
        if k in VALID_TYPES:
            try:
                pct = float(v)
                if 0 <= pct <= 100:
                    groups[k] = round(pct, 2)
            except (TypeError, ValueError):
                pass

    holdings = {}
    for k, v in (data.get('holdings') or {}).items():
        try:
            pct = float(v)
            if 0 <= pct <= 100:
                holdings[str(k)] = round(pct, 2)
        except (TypeError, ValueError):
            pass

    set_setting('target_allocations_v2', {'groups': groups, 'holdings': holdings})
    return jsonify({'ok': True})


@app.route('/position/<int:holding_id>')
def position_view(holding_id):
    data = get_position_data(holding_id)
    if data is None:
        return redirect(url_for('positions_view'))
    if _get_lang() == 'he' and data.get('yfinance_symbol'):
        from app.utils.translation_service import ensure_hebrew_translations_cached
        yf_data = ensure_hebrew_translations_cached(data['holding'])
        if yf_data:
            data['yfinance_info'] = {**(data['yfinance_info'] or {}), **yf_data}
    return render_template('position.html', data=data)


@app.route('/position/<int:holding_id>/refresh-info', methods=['POST'])
def position_refresh_info(holding_id):
    from app.analytics.position_analytics import refresh_yfinance_info
    refresh_yfinance_info(holding_id)
    return redirect(url_for('position_view', holding_id=holding_id))


@app.route('/api/yfinance/search')
def api_yfinance_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    try:
        import yfinance as yf
        results = yf.Search(q, max_results=8).quotes
        return jsonify([
            {
                'symbol': r['symbol'],
                'name': r.get('longname') or r.get('shortname', ''),
                'exchange': r.get('exchDisp', ''),
            }
            for r in results if r.get('symbol')
        ])
    except Exception:
        return jsonify([])


@app.route('/api/holdings/<int:holding_id>/update-name', methods=['POST'])
def api_update_holding_name(holding_id):
    from app.holdings import get_holding, update_holding
    holding = get_holding(holding_id)
    if not holding:
        return jsonify({'error': 'Not found'}), 404

    data = request.get_json()
    confirm = (data.get('confirm') or '').strip()
    current_name_he = holding.get('name_he', '')

    if confirm != current_name_he:
        return jsonify({'error': 'confirmation_mismatch'}), 400

    updates = {}
    new_name_he = (data.get('name_he') or '').strip()
    if new_name_he:
        updates['name_he'] = new_name_he
    if 'name_en' in data:
        updates['name_en'] = (data['name_en'] or '').strip() or None
    if data.get('ticker'):
        updates['ticker'] = data['ticker'].strip()

    if updates:
        update_holding(holding_id, **updates)

    return jsonify({'success': True})


@app.route('/api/holdings/<int:holding_id>/fetch-tase-name')
def api_fetch_tase_name(holding_id):
    from app.holdings import get_holding
    from app.utils.translation_service import fetch_data_from_tase
    holding = get_holding(holding_id)
    if not holding:
        return jsonify({'error': 'Not found'}), 404
    data = fetch_data_from_tase(holding['tase_id'])
    if data:
        return jsonify({
            'name': data['name'],
            'name_tase_he': data.get('name_tase_he'),
            'ticker': data.get('ticker'),
            'tase_symbol_en': data.get('tase_symbol_en'),
        })
    return jsonify({'error': 'not_found'}), 404


# ── Display preferences routes ──

@app.route('/api/settings/display-prefs', methods=['GET', 'POST'])
def api_display_prefs():
    from app.settings import get_setting, set_setting
    lang = _get_lang()
    if request.method == 'GET':
        saved_all = get_setting('display_name_prefs', {}) or {}
        saved = saved_all.get(lang, {}) if isinstance(saved_all, dict) else {}
        return jsonify({**_default_display_prefs(lang), **saved})
    data = request.get_json(silent=True) or {}
    valid = {k: v for k, v in data.items() if k in _DEFAULT_DISPLAY_PREFS_HE}
    saved_all = get_setting('display_name_prefs', {}) or {}
    if not isinstance(saved_all, dict):
        saved_all = {}
    saved_all[lang] = valid
    set_setting('display_name_prefs', saved_all)
    return jsonify({'success': True})


@app.route('/exports')
def exports_view():
    lang = _get_lang()
    t = get_translations(lang)
    return render_template('exports.html', t=t, lang=lang, dir='rtl' if lang == 'he' else 'ltr',
                           t_json=get_translations_json(lang))


@app.route('/settings/display')
def settings_display():
    from app.settings import get_setting
    lang = _get_lang()
    t = get_translations(lang)
    saved_all = get_setting('display_name_prefs', {}) or {}
    saved = saved_all.get(lang, {}) if isinstance(saved_all, dict) else {}
    defaults = _default_display_prefs(lang)
    prefs = {**defaults, **saved}
    return render_template('settings_display.html', t=t, lang=lang,
                           dir='rtl' if lang == 'he' else 'ltr',
                           prefs=prefs,
                           default_prefs=defaults)


# ── yfinance review routes ──

@app.route('/api/holdings/<int:holding_id>/fetch-yfinance-preview')
def api_fetch_yfinance_preview(holding_id):
    """Return what a yfinance refresh would write, without committing to DB."""
    from app.holdings import get_holding
    from app.utils.translation_service import fetch_info_from_yfinance, get_yfinance_mapping
    holding = get_holding(holding_id)
    if not holding:
        return jsonify({'error': 'Not found'}), 404
    yfinance_symbol = get_yfinance_mapping(holding.get('tase_id'))
    if not yfinance_symbol:
        return jsonify({'error': 'no_mapping'}), 404
    info = fetch_info_from_yfinance(yfinance_symbol)
    if not info:
        return jsonify({'error': 'fetch_failed'}), 502
    return jsonify({
        'current': {
            'name_yf_long': holding.get('name_yf_long'),
            'name_yf_short': holding.get('name_yf_short'),
            'ticker': holding.get('ticker'),
        },
        'proposed': {
            'name_yf_long': info.get('name_long'),
            'name_yf_short': info.get('name_short'),
            'ticker': yfinance_symbol,
        },
        'symbol': yfinance_symbol,
    })


@app.route('/api/holdings/<int:holding_id>/apply-yfinance-data', methods=['POST'])
def api_apply_yfinance_data(holding_id):
    """Write user-reviewed yfinance fields to the holding."""
    from app.holdings import get_holding, update_holding
    holding = get_holding(holding_id)
    if not holding:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(silent=True) or {}
    allowed = {'name_yf_long', 'name_yf_short'}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if updates:
        update_holding(holding_id, **updates)
    return jsonify({'success': True})


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
        data = [e for e in data if e['action'] in ('deposit', 'withdrawal', 'dividend', 'month_summary')]
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


@app.route('/admin')
@require_admin
def admin():
    lang = request.cookies.get('lang', 'he')
    t = get_translations(lang)
    return render_template('admin.html', t=t, lang=lang,
                           dir='rtl' if lang == 'he' else 'ltr')


@app.route('/admin/db-export')
@require_admin
def admin_db_export():
    import tempfile
    from app.db_backup import export_db
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
    tmp.close()
    export_db(tmp.name)
    date_str = datetime.now().strftime('%Y-%m-%d')
    response = send_file(tmp.name, as_attachment=True,
                         download_name=f'tradevault_backup_{date_str}.json',
                         mimetype='application/json')

    @response.call_on_close
    def cleanup():
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return response


@app.route('/admin/db-import', methods=['POST'])
@require_admin
def admin_db_import():
    import tempfile
    from app.db_backup import import_db
    lang = request.cookies.get('lang', 'he')
    file = request.files.get('backup_file')
    if not file or not file.filename:
        flash(_t('admin_no_file', lang), 'error')
        return redirect(url_for('admin'))
    if not file.filename.lower().endswith('.json'):
        flash(_t('admin_import_invalid_type', lang), 'error')
        return redirect(url_for('admin'))
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
    tmp.close()
    file.save(tmp.name)
    try:
        _, migration = import_db(tmp.name)
        migrated_count = migration.get('yfinance_cache_migrated', 0) if migration else 0
        # Repair net_invested on all imported snapshots — the backup may have been
        # created before deposits were present, so those snapshots store 0.
        from app.snapshots import repair_net_invested as _repair_ni
        _repaired = _repair_ni()
        if _repaired:
            app.logger.info('net_invested repaired on %d snapshot(s) after DB import', _repaired)
        from app.tax_lots import repair_lot_states as _repair_lots
        _lots_repaired = _repair_lots()
        if _lots_repaired:
            app.logger.info('lot state repaired on %d tax lot(s) after DB import', _lots_repaired)
        flush_db()  # persist repairs to disk so CLI imports don't clobber them
        flash(_t('admin_import_success', lang, migrated=migrated_count), 'success')
    except (ValueError, PermissionError):
        app.logger.exception('DB import failed')
        flash(_t('admin_import_error', lang), 'error')
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return redirect(url_for('admin'))


def _tase_refresh_worker():
    """Fetch TASE data for all holdings and write results to DB.

    HTTP calls are parallelised (up to 5 concurrent); DB writes are sequential
    so TinyDB's CachingMiddleware is never written from two threads at once.
    """
    from app.holdings import list_holdings, update_holding
    from app.settings import get_setting, set_setting
    from app.utils.translation_service import fetch_data_from_tase

    with _tase_lock:
        _tase_status.update({'running': True, 'updated': 0, 'failed': 0, 'done': False})

    holdings = list_holdings(active_only=False)
    fetch_results: dict = {}  # doc_id -> (holding, data_or_None)

    # Phase 1: parallel HTTP fetches (no DB writes)
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(fetch_data_from_tase, h['tase_id']): h for h in holdings}
            for future in as_completed(futures):
                h = futures[future]
                try:
                    fetch_results[h.doc_id] = (h, future.result())
                except Exception:
                    fetch_results[h.doc_id] = (h, None)
    except Exception:
        app.logger.exception('TASE parallel fetch failed')

    # Phase 2: sequential DB writes
    updated, failed = 0, 0
    try:
        yf_map = get_setting('yfinance_map', {}) or {}
        for doc_id, (h, data) in fetch_results.items():
            if data:
                field_updates = {'name_tase_en': data['name']}
                if data.get('name_tase_he'):
                    field_updates['name_tase_he'] = data['name_tase_he']
                if data.get('tase_symbol_en'):
                    field_updates['tase_symbol_en'] = data['tase_symbol_en']
                if data.get('ticker'):
                    field_updates['ticker'] = data['ticker']
                    yf_map[str(h['tase_id'])] = data['ticker']
                update_holding(doc_id, **field_updates)
                updated += 1
            else:
                failed += 1
        set_setting('yfinance_map', yf_map)
    except Exception:
        app.logger.exception('TASE DB write phase failed')

    with _tase_lock:
        _tase_status.update({'running': False, 'updated': updated, 'failed': failed, 'done': True})


@app.route('/admin/refresh-tase-names', methods=['POST'])
@require_admin
def admin_refresh_tase_names():
    lang = request.cookies.get('lang', 'he')
    with _tase_lock:
        if _tase_status.get('running'):
            flash(_t('admin_tase_refresh_running', lang), 'info')
            return redirect(url_for('admin'))
    thread = threading.Thread(target=_tase_refresh_worker, daemon=True, name='tase-refresh')
    thread.start()
    flash(_t('admin_tase_refresh_started', lang), 'info')
    return redirect(url_for('admin'))


@app.route('/admin/refresh-status')
@require_admin
def admin_refresh_status():
    """Return current TASE refresh status as JSON (for polling)."""
    with _tase_lock:
        return jsonify(dict(_tase_status))


@app.route('/accessibility')
def accessibility_view():
    return render_template('accessibility.html')


@app.route('/docs/cli')
def cli_docs():
    return send_file(os.path.join(os.path.dirname(__file__), 'docs', 'cli.html'))


@app.route('/health')
def health_check():
    try:
        get_db()
        return jsonify({'status': 'ok'}), 200
    except Exception:
        app.logger.exception('Health check failed')
        return jsonify({'status': 'error'}), 503


if __name__ == '__main__':
    _run_startup()
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    port = int(os.environ.get('PORT', 2501))
    print(f"Starting TradeVault server on http://localhost:{port}")
    app.run(host="0.0.0.0", debug=debug, port=port)
