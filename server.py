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

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response, send_file, send_from_directory, Response, g, session
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

# ── Per-session TOTP authentication ───────────────────────────────────────────
# App-native login (Google Authenticator). Enabled when TOTP_SECRET is set, or when
# set up from Settings → Maintenance. Designed to sit behind the existing
# Cloudflare Tunnel: ProxyFix honors X-Forwarded-Proto so Secure cookies engage,
# and the client IP for rate-limiting comes from CF-Connecting-IP.
from datetime import timedelta
import time as _time
import pyotp
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from app import auth_store


def _totp_secret():
    """Active TOTP secret (env var, else web-managed sidecar), or None if disabled."""
    return auth_store.get_totp_secret()


def _admin_password():
    """Bootstrap login password (ADMIN_PASSWORD env), or '' if unset."""
    return os.environ.get('ADMIN_PASSWORD', '').strip()


def _login_required():
    """Auth is enforced when a TOTP secret OR a bootstrap password is configured."""
    return bool(_totp_secret()) or bool(_admin_password())


_SESSION_HOURS = int(os.environ.get('SESSION_LIFETIME_HOURS', '12') or 12)
_TRUST_PROXY = os.environ.get('TRUST_PROXY', 'false').lower() == 'true'
_COOKIE_SECURE = os.environ.get(
    'SESSION_COOKIE_SECURE', 'true' if _TRUST_PROXY else 'false').lower() == 'true'

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=_SESSION_HOURS),
)

if _TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _client_ip():
    """Real client IP behind Cloudflare/cloudflared (for rate-limit + logging)."""
    return (request.headers.get('CF-Connecting-IP')
            or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr or 'unknown')


limiter = Limiter(key_func=_client_ip, app=app, storage_uri='memory://')

_AUTH_EXEMPT_ENDPOINTS = {'login', 'logout', 'health_check', 'static', 'asset'}
_login_guard_lock = threading.Lock()
_login_failures = {}            # ip -> {'count': int, 'until': float}
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCKOUT_SECONDS = 300

if not _login_required():
    print("NOTE: login is DISABLED (no TOTP secret and no ADMIN_PASSWORD). "
          "Set ADMIN_PASSWORD to gate the app, then set up TOTP from the web "
          "Maintenance page (Settings → Maintenance → Login & Security).",
          file=sys.stderr)


def _session_valid():
    if not session.get('authed'):
        return False
    return (_time.time() - session.get('authed_at', 0)) <= _SESSION_HOURS * 3600


@app.before_request
def _require_login():
    if not _login_required():
        return  # auth disabled (no secret or password configured)
    if (request.endpoint or '') in _AUTH_EXEMPT_ENDPOINTS:
        return
    if _session_valid():
        return
    session.clear()
    if request.path.startswith('/api/'):
        return jsonify({'error': 'authentication required'}), 401
    nxt = request.full_path.rstrip('?') if request.method == 'GET' else None
    return redirect(url_for('login', next=nxt) if nxt else url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10/minute;60/hour', exempt_when=lambda: request.method != 'POST')
def login():
    lang = _get_lang()
    secret = _totp_secret()
    password = _admin_password()
    # TOTP takes over once configured; until then the admin password bootstraps login.
    mode = 'totp' if secret else ('password' if password else None)
    if mode is None:
        return redirect(url_for('index'))

    if request.method == 'GET':
        if _session_valid():
            return redirect(url_for('index'))
        return render_template('login.html', mode=mode, next=request.args.get('next', ''))

    ip = _client_ip()
    now = _time.time()
    with _login_guard_lock:
        st = _login_failures.get(ip)
        if st and st['until'] > now:
            flash(_t('login_locked', lang, seconds=int(st['until'] - now)), 'error')
            return redirect(url_for('login'))

    if mode == 'totp':
        code = (request.form.get('code') or '').replace(' ', '').strip()
        ok = bool(code) and pyotp.TOTP(secret).verify(code, valid_window=1)
    else:  # password bootstrap
        supplied = request.form.get('password') or ''
        ok = bool(supplied) and hmac.compare_digest(supplied, password)

    if ok:
        session.clear()
        session['authed'] = True
        session['authed_at'] = now
        session.permanent = True
        with _login_guard_lock:
            _login_failures.pop(ip, None)
        if mode == 'password':
            # Nudge the user to set up TOTP for subsequent logins.
            flash(_t('login_totp_nudge', lang), 'success')
            return redirect(url_for('maintenance'))
        nxt = request.form.get('next') or request.args.get('next')
        if nxt and nxt.startswith('/') and not nxt.startswith('//'):
            return redirect(nxt)
        return redirect(url_for('index'))

    with _login_guard_lock:
        st = _login_failures.setdefault(ip, {'count': 0, 'until': 0})
        st['count'] += 1
        if st['count'] >= _LOGIN_MAX_FAILS:
            st['until'] = now + _LOGIN_LOCKOUT_SECONDS
            st['count'] = 0
    app.logger.warning('Failed login attempt from %s', ip)
    flash(_t('login_failed', lang), 'error')
    return redirect(url_for('login'))


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login') if _login_required() else url_for('index'))


# ── Maintenance (web-managed security + data health) ──────────────────────────
@app.route('/maintenance')
def maintenance():
    return render_template(
        'maintenance.html',
        totp_active=bool(_totp_secret()),
        totp_env_managed=auth_store.is_env_managed(),
    )


@app.route('/maintenance/totp/begin', methods=['POST'])
def maintenance_totp_begin():
    """Generate a candidate secret + QR (SVG). Secret is kept pending until confirmed."""
    if auth_store.is_env_managed():
        return jsonify({'error': 'env_managed'}), 400
    import io
    import qrcode
    import qrcode.image.svg
    secret = pyotp.random_base32()
    session['totp_pending'] = secret
    issuer = os.environ.get('TOTP_ISSUER', 'TradeVault')
    label = os.environ.get('TOTP_LABEL', 'tradevault')
    uri = pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=issuer)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return jsonify({'svg': buf.getvalue().decode('utf-8'), 'secret': secret})


@app.route('/maintenance/totp/confirm', methods=['POST'])
def maintenance_totp_confirm():
    """Verify a code against the pending secret, then activate login."""
    lang = _get_lang()
    if auth_store.is_env_managed():
        return jsonify({'ok': False, 'error': 'env_managed'}), 400
    pending = session.get('totp_pending')
    code = (request.form.get('code') or '').replace(' ', '').strip()
    if not pending or not code or not pyotp.TOTP(pending).verify(code, valid_window=1):
        return jsonify({'ok': False, 'error': _t('login_failed', lang)}), 400
    auth_store.set_totp_secret(pending)
    session.pop('totp_pending', None)
    session['authed'] = True
    session['authed_at'] = _time.time()
    session.permanent = True
    flush_db()
    return jsonify({'ok': True})


@app.route('/maintenance/totp/disable', methods=['POST'])
def maintenance_totp_disable():
    lang = _get_lang()
    if not auth_store.clear_totp_secret():
        flash(_t('totp_env_managed', lang), 'error')
    else:
        flash(_t('totp_disabled_msg', lang), 'success')
    return redirect(url_for('maintenance'))


@app.route('/maintenance/reconcile', methods=['POST'])
def maintenance_reconcile():
    from app.reconcile import reconcile
    issues = [{'sev': s, 'date': d, 'msg': m} for s, d, m in reconcile()]
    return jsonify({'issues': issues})


@app.route('/maintenance/rebuild-lots', methods=['POST'])
def maintenance_rebuild_lots():
    lang = _get_lang()
    from app.recompute import recompute_after_trade_change
    summary = recompute_after_trade_change()
    _spawn_chart_warm()
    flash(f"{_t('rebuild_lots_done', lang)} "
          f"({summary['buys']} buys, {summary['sells']} sells)", 'success')
    return redirect(url_for('maintenance'))


@app.route('/maintenance/sync-holdings', methods=['POST'])
def maintenance_sync_holdings():
    lang = _get_lang()
    from app.holdings import sync_active_holdings
    from app.recompute import recompute_cash
    activated, deactivated = sync_active_holdings()
    recompute_cash()
    flash(_t('sync_holdings_done', lang, activated=activated, deactivated=deactivated), 'success')
    return redirect(url_for('maintenance'))


@app.route('/maintenance/repair/<target>', methods=['POST'])
def maintenance_repair(target):
    lang = _get_lang()
    try:
        if target == 'morning-balance':
            from app.importers.repair_tools import repair_morning_balance_pnl
            repair_morning_balance_pnl()
        elif target == 'interpolated':
            from app.importers.repair_tools import repair_interpolated_trades
            from_date = (request.form.get('from_date') or '').strip() or None
            repair_interpolated_trades(from_date) if from_date else repair_interpolated_trades()
        else:
            flash(_t('flash_trade_error', lang), 'error')
            return redirect(url_for('maintenance'))
        flush_db()
        flash(_t('repair_done', lang, target=target), 'success')
    except Exception:
        app.logger.exception('Repair %s failed', target)
        flash(_t('flash_trade_error', lang), 'error')
    return redirect(url_for('maintenance'))


@app.route('/maintenance/refresh-yfinance', methods=['POST'])
def maintenance_refresh_yfinance():
    lang = _get_lang()
    try:
        from app.utils.translation_service import refresh_info_from_mappings
        results = refresh_info_from_mappings()
        flush_db()
        flash(_t('refresh_yf_done', lang, success=results.get('success', 0),
                 failed=results.get('failed', 0)), 'success')
    except Exception:
        app.logger.exception('refresh-yfinance failed')
        flash(_t('flash_trade_error', lang), 'error')
    return redirect(url_for('maintenance'))


@app.route('/maintenance/check-libs', methods=['POST'])
def maintenance_check_libs():
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'list', '--outdated', '--format=json'],
            capture_output=True, text=True, timeout=60,
        )
        import json as _json
        outdated = _json.loads(result.stdout or '[]')
        return jsonify({'outdated': [
            {'name': p.get('name'), 'version': p.get('version'),
             'latest': p.get('latest_version')} for p in outdated]})
    except Exception:
        app.logger.exception('check-libs failed')
        return jsonify({'outdated': [], 'error': True}), 500


@app.route('/maintenance/upgrade-libs', methods=['POST'])
def maintenance_upgrade_libs():
    """Upgrade all packages in requirements.txt (parity with the former CLI command).

    In Docker the upgrade lives only in the running container's layer and is lost on
    recreate — the durable path is rebuilding the image — so we flag that case.
    """
    lang = _get_lang()
    from app.lib_check import run_upgrade_libs
    try:
        run_upgrade_libs()
    except Exception:
        app.logger.exception('upgrade-libs failed')
        flash(_t('upgrade_libs_error', lang), 'error')
        return redirect(url_for('maintenance'))
    flash(_t('upgrade_libs_done', lang), 'success')
    if os.path.exists('/.dockerenv'):
        flash(_t('upgrade_libs_docker', lang), 'warning')
    return redirect(url_for('maintenance'))


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

    # One-time: relocate formerly-shared yfinance cache/map into the default portfolio.
    from app.db_backup import migrate_shared_yfinance_to_portfolios, migrate_daily_price_sessions
    migrate_shared_yfinance_to_portfolios()
    # One-time: stamp session='regular' on pre-extended-hours daily_prices rows (per portfolio).
    migrate_daily_price_sessions()

    # Refuse to run an unauthenticated app in production (would be open to the web).
    if _is_production and not _login_required():
        raise RuntimeError(
            "Refusing to start in production with no authentication. Set ADMIN_PASSWORD "
            "(bootstrap login) and/or configure TOTP via the Maintenance page."
        )

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

    # Daily-close scheduler (manual/US portfolios) + gap-fill for days missed while
    # the container was down. Both no-op unless ENABLE_SCHEDULER is set.
    from app.scheduler import start_scheduler, spawn_startup_catchup
    start_scheduler()
    spawn_startup_catchup()


# ── Background TASE refresh state ─────────────────────────────────────────────
_tase_lock = threading.Lock()
_tase_status: dict = {'running': False, 'updated': 0, 'failed': 0, 'bp_updated': 0, 'total': 0, 'done': True}


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
    'trades_tax_name':           'name_tase_he',
    'daily_details_pivot_name':  'name_tase_he',
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
    'trades_tax_name':           'name_tase_en',
    'daily_details_pivot_name':  'name_tase_en',
    'graphs_pnl_labels':         'symbol_en',
    'graphs_treemap_labels':     'symbol_en',
}


def _default_display_prefs(lang):
    return _DEFAULT_DISPLAY_PREFS_HE if lang == 'he' else _DEFAULT_DISPLAY_PREFS_EN


# Inline SVG icon helper for the v1.0 redesigned templates (base.html and pages
# that extend it). Available as {{ tv_icon('name', size) }} in every template.
from app.icons import tv_icon as _tv_icon
app.jinja_env.globals['tv_icon'] = _tv_icon


# Brand SVGs live in asset/ (separate from static/ JS/CSS). Served here since Flask's
# default static handler only covers static/.
_ASSET_DIR = os.path.join(app.root_path, 'asset')


@app.route('/asset/<path:filename>')
def asset(filename):
    return send_from_directory(_ASSET_DIR, filename, max_age=86400)


@app.context_processor
def inject_translations():
    """Make t, lang, dir, t_json, app_version, and display_prefs available in every template."""
    from app.settings import get_setting
    lang = _get_lang()
    if not hasattr(g, 'display_prefs'):
        saved_all = get_setting('display_name_prefs', {}) or {}
        saved_prefs = saved_all.get(lang, {}) if isinstance(saved_all, dict) else {}
        g.display_prefs = {**_default_display_prefs(lang), **saved_prefs}
    from app import portfolios
    if not hasattr(g, 'portfolio_list'):
        g.portfolio_list = portfolios.list_portfolios()
    pid = getattr(g, 'active_portfolio_id', None) or portfolios.default_id()
    active = next((p for p in g.portfolio_list if p['id'] == pid), None)
    from app.currency import currency_symbol as _sym, is_agorot as _is_ag, number_locale as _loc
    currency = (active or {}).get('currency', 'ILS')
    symbol = _sym(currency)
    # Which trading session the current value reflects (extended hours), for a
    # dashboard badge. Only relevant when it's today and not a regular session.
    from app.schemas import today_iso
    market_session = get_setting('market_session', {}) or {}
    today_session = market_session.get('session') if market_session.get('date') == today_iso() else None
    t_map = get_translations(lang)
    t_json = get_translations_json(lang)
    # Display-only currency: swap the hardcoded ₪ in labels/flashes/JS for the
    # active portfolio's symbol. ILS is the default and left byte-for-byte unchanged.
    if currency != 'ILS':
        t_map = {k: (v.replace('₪', symbol) if isinstance(v, str) else v)
                 for k, v in t_map.items()}
        t_json = t_json.replace('₪', symbol)
    return {
        't': t_map,
        't_json': t_json,
        'lang': lang,
        'dir': 'ltr' if lang == 'en' else 'rtl',
        'app_version': APP_VERSION,
        'display_prefs': g.display_prefs,
        'active_portfolio': active,
        'portfolio_list': g.portfolio_list,
        'currency': currency,
        'currency_symbol': symbol,
        'number_locale': _loc(currency, lang),
        'is_agorot': _is_ag(currency),
        'market_session': today_session,
    }


@app.before_request
def ensure_db():
    # Resolve the active portfolio from the session (default when unset/unknown),
    # then open its db. The contextvar token is reset in teardown.
    from app import portfolios
    from app.connection import set_active_portfolio
    pid = session.get('portfolio_id')
    if not pid or not portfolios.exists(pid):
        pid = portfolios.default_id()
    g._pid_token = set_active_portfolio(pid)
    g.active_portfolio_id = pid
    get_db()


@app.teardown_request
def _reset_active_portfolio(exception=None):
    from app.connection import reset_active_portfolio
    token = getattr(g, '_pid_token', None)
    if token is not None:
        reset_active_portfolio(token)


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


# ── Portfolio switcher ──

@app.route('/portfolio/switch', methods=['POST'])
def portfolio_switch():
    from app import portfolios
    pid = request.form.get('portfolio_id', '')
    if portfolios.exists(pid):
        session['portfolio_id'] = pid
    return redirect(request.referrer or url_for('index'))


@app.route('/portfolio/new', methods=['POST'])
def portfolio_new():
    from app import portfolios
    lang = _get_lang()
    name = (request.form.get('name') or '').strip()
    if not name:
        flash(_t('portfolio_name_required', lang), 'error')
        return redirect(request.referrer or url_for('index'))
    currency = (request.form.get('currency') or 'ILS').strip()
    pid = portfolios.create_portfolio(name, currency=currency)
    session['portfolio_id'] = pid  # switch to the new portfolio
    flash(_t('portfolio_created', lang, name=name), 'success')
    return redirect(url_for('index'))


@app.route('/portfolio/rename', methods=['POST'])
def portfolio_rename():
    from app import portfolios
    pid = request.form.get('portfolio_id', '')
    name = (request.form.get('name') or '').strip()
    portfolios.rename_portfolio(pid, name)
    return redirect(request.referrer or url_for('index'))


@app.route('/portfolio/delete', methods=['POST'])
def portfolio_delete():
    from app import portfolios
    lang = _get_lang()
    pid = request.form.get('portfolio_id', '')
    ok, msg = portfolios.delete_portfolio(pid)
    if ok and session.get('portfolio_id') == pid:
        session.pop('portfolio_id', None)  # fall back to default
    flash(_t('portfolio_deleted', lang) if ok else msg, 'success' if ok else 'error')
    return redirect(request.referrer or url_for('index'))


@app.route('/portfolio/currency', methods=['POST'])
def portfolio_currency():
    from app import portfolios
    lang = _get_lang()
    pid = request.form.get('portfolio_id', '')
    code = request.form.get('currency', '')
    if portfolios.set_currency(pid, code):
        flash(_t('portfolio_currency_saved', lang), 'success')
    return redirect(request.referrer or url_for('settings_portfolios'))


@app.route('/holdings/new', methods=['POST'])
def holdings_new():
    """Add a position: create the security (TASE or non-TASE) AND its opening buy,
    then materialize it into today's snapshot so it shows immediately."""
    from app import portfolios
    from app.holdings import add_holding
    from app.manual_portfolio import record_trade
    from app.snapshots import materialize_position_in_snapshot
    lang = _get_lang()
    name = (request.form.get('name') or '').strip()
    ticker = (request.form.get('ticker') or '').strip().upper() or None
    sec_type = (request.form.get('security_type') or 'stock').strip()
    currency = (request.form.get('currency') or '').strip()
    raw_tase = (request.form.get('tase_id') or '').strip()
    try:
        tase_id = int(raw_tase) if raw_tase else None
    except ValueError:
        tase_id = None

    if not name and not ticker:
        flash(_t('holding_add_need_name', lang), 'error')
        return redirect(request.referrer or url_for('positions_view'))
    if not currency:
        pid = getattr(g, 'active_portfolio_id', None) or portfolios.default_id()
        currency = portfolios.get_currency(pid)

    try:
        date = (request.form.get('date') or '').strip()
        shares = float(request.form.get('shares'))
        price = float(request.form.get('price'))
        commission = float(request.form.get('commission') or 0)
    except (TypeError, ValueError):
        flash(_t('position_add_need_trade', lang), 'error')
        return redirect(request.referrer or url_for('positions_view'))

    hid = add_holding(tase_id=tase_id, tase_symbol=ticker or name, name_he=name or ticker,
                      security_type=sec_type, currency=currency, ticker=ticker,
                      name_en=name or ticker, first_bought=date)
    try:
        record_trade(hid, 'buy', date, shares, price, commission=commission)
        materialize_position_in_snapshot(hid, price)  # show at entered price
        flash(_t('position_added', lang, name=name or ticker), 'success')
    except ValueError as e:
        flash(str(e) or _t('flash_trade_error', lang), 'error')
    flush_db()
    _spawn_chart_warm()
    return redirect(url_for('positions_view'))


@app.route('/trades/new', methods=['POST'])
def trades_new():
    """Record a manual buy/sell against a holding, then reflect it in the snapshot."""
    from app.manual_portfolio import record_trade
    from app.snapshots import materialize_position_in_snapshot
    lang = _get_lang()
    try:
        hid = int(request.form.get('holding_id'))
        action = request.form.get('action', '')
        date = (request.form.get('date') or '').strip()
        raw_shares = request.form.get('shares')
        shares = float(raw_shares) if raw_shares not in (None, '') else 0.0  # blank for Close
        price = float(request.form.get('price'))
        commission = float(request.form.get('commission') or 0)
        record_trade(hid, action, date, shares, price, commission=commission)
        materialize_position_in_snapshot(hid, price)  # upsert/remove at entered price
        flash(_t('trade_added', lang), 'success')
    except ValueError as e:
        flash(str(e) or _t('flash_trade_error', lang), 'error')
    except Exception:
        app.logger.exception('manual trade failed')
        flash(_t('flash_trade_error', lang), 'error')
    flush_db()
    _spawn_chart_warm()
    return redirect(request.referrer or url_for('trades_view'))


@app.route('/portfolio/refresh-prices', methods=['POST'])
def portfolio_refresh_prices():
    """Price open positions from Yahoo Finance and write today's snapshot (manual books)."""
    from app.manual_portfolio import refresh_prices_and_snapshot
    lang = _get_lang()
    try:
        res = refresh_prices_and_snapshot()
        flash(_t('prices_refreshed', lang, positions=res['positions'],
                 priced=res['priced'], stale=res['stale']), 'success')
        if res.get('backfilled'):
            flash(_t('prices_backfilled', lang, days=res['backfilled']), 'info')
    except Exception:
        app.logger.exception('price refresh failed')
        flash(_t('flash_import_error', lang), 'error')
    _spawn_chart_warm()
    return redirect(request.referrer or url_for('index'))


@app.route('/portfolio/make-default', methods=['POST'])
def portfolio_make_default():
    from app import portfolios
    lang = _get_lang()
    pid = request.form.get('portfolio_id', '')
    if portfolios.set_default(pid):
        flash(_t('portfolio_made_default', lang), 'success')
    return redirect(request.referrer or url_for('index'))


@app.route('/settings/portfolios')
def settings_portfolios():
    from app import portfolios
    active_id = getattr(g, 'active_portfolio_id', None) or portfolios.default_id()
    default = portfolios.default_id()
    plist = portfolios.list_portfolios()
    rows = [{
        **p,
        'is_active': p['id'] == active_id,
        'is_default': p['id'] == default,
        'stats': portfolios.portfolio_stats(p['id']),
    } for p in plist]
    from app.currency import SUPPORTED as _currencies
    return render_template('portfolios.html', rows=rows, can_delete=len(plist) > 1,
                           currencies=_currencies)


@app.route('/')
def index():
    from app.analytics.portfolio_analytics import get_overview
    overview = get_overview(_get_lang())
    portfolio = overview['portfolio'] if overview else None
    return render_template('index.html', portfolio=portfolio, ov=overview)


def _upload_trades(lang):
    """Save uploaded trade files (DDMMYYYY.xlsx) and import each."""
    from werkzeug.utils import secure_filename
    from app.importers import import_trades
    from app.recompute import recompute_cash
    files = [f for f in request.files.getlist('file') if f and f.filename]
    if not files:
        flash(_t('flash_no_file', lang), 'error')
        return redirect(url_for('index'))
    trades_dir = os.path.join(os.path.dirname(DATA_DIR), 'trades')
    os.makedirs(trades_dir, exist_ok=True)
    buys = sells = dups = errs = 0
    for f in files:
        if not f.filename.lower().endswith(('.xlsx', '.xls')):
            errs += 1
            continue
        path = os.path.join(trades_dir, secure_filename(f.filename))
        f.save(path)
        try:
            r = import_trades(path)
            if r.get('status') == 'duplicate':
                dups += 1
            else:
                buys += r.get('buys', 0)
                sells += r.get('sells', 0)
        except Exception:
            app.logger.exception('Trade import failed for %s', f.filename)
            errs += 1
    recompute_cash()  # refresh snapshot cash from the new buys/sells (also flushes)
    _spawn_chart_warm()
    flash(_t('flash_trades_imported', lang, buys=buys, sells=sells, dups=dups, errors=errs),
          'success' if not errs else 'warning')
    return redirect(url_for('index'))


def _upload_morning_balance(lang):
    """Save uploaded morning-balance files to a temp folder and import the folder."""
    import tempfile
    from werkzeug.utils import secure_filename
    from app.importers import import_morning_balance_folder
    from app.recompute import recompute_cash
    files = [f for f in request.files.getlist('file') if f and f.filename]
    if not files:
        flash(_t('flash_no_file', lang), 'error')
        return redirect(url_for('index'))
    tmpdir = tempfile.mkdtemp(prefix='mb-')
    saved = 0
    for f in files:
        if not f.filename.lower().endswith(('.xlsx', '.xls')):
            continue
        f.save(os.path.join(tmpdir, secure_filename(f.filename)))
        saved += 1
    try:
        result = import_morning_balance_folder(tmpdir)
        recompute_cash()
        flash(_t('flash_morning_imported', lang, count=saved,
                 status=result.get('status', 'done')), 'success')
    except Exception:
        app.logger.exception('Morning-balance import failed')
        flash(_t('flash_import_error', lang), 'error')
    return redirect(url_for('index'))


@app.route('/upload', methods=['POST'])
def upload_daily():
    """Upload an Excel file (daily / trades / morning-balance) and import it."""
    lang = _get_lang()
    import_type = request.form.get('import_type', 'daily')
    if import_type == 'trades':
        return _upload_trades(lang)
    if import_type == 'morning-balance':
        return _upload_morning_balance(lang)

    # ── daily portfolio (default) ──
    file = request.files.get('file')
    date_str = request.form.get('date')

    if not file or not file.filename:
        flash(_t('flash_no_file', lang), 'error')
        return redirect(url_for('index'))

    # Validate file extension (.csv = IBI Smart US export; xlsx/xls = IBI daily)
    if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
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

    # Build filename: data_<YYYY-MM-DD>.<ext> — preserve .csv (US) vs .xlsx (IBI)
    ext = '.csv' if file.filename.lower().endswith('.csv') else '.xlsx'
    safe_name = f"data_{date_str}{ext}"
    target_path = os.path.join(target_dir, safe_name)

    # Save the uploaded file
    file.save(target_path)

    # Import into database
    try:
        force = request.form.get('force') in ('on', 'true', '1')
        result = import_daily_portfolio(target_path, data_date=date_str, force=force)
        if result['status'] == 'duplicate':
            flash(f"{_t('flash_duplicate', lang)} ({date_str})", 'warning')
        elif result['status'] in ('failed', 'rejected'):
            flash(_t('flash_import_rejected', lang, date=date_str,
                     reason=result.get('reason', '')), 'error')
        else:
            imported = result['rows_imported']
            new_h = result['new_holdings']
            flash(_t('flash_import_success', lang, rows=imported, new=new_h, date=date_str), 'success')
            if result.get('rows_skipped'):
                flash(_t('flash_import_partial', lang, skipped=result['rows_skipped']), 'warning')
    except Exception:
        app.logger.exception('Daily import failed for %s', date_str)
        flash(_t('flash_import_error', lang), 'error')

    flush_db()
    _spawn_chart_warm()
    return redirect(url_for('index'))


def _spawn_chart_warm():
    """Precompute the heavy /graphs payloads in a background thread after a data change.

    Best-effort UX: the lazy cache in chart_cache.cached() already guarantees
    correctness on the next visit; this just makes that first visit warm. Must be
    called AFTER the route's final flush so the daemon thread never races unflushed
    writes in the request thread.
    """
    from app.analytics.chart_cache import warm_charts
    from app.connection import current_portfolio_id, using_portfolio
    pid = current_portfolio_id()  # capture the active portfolio for the worker

    def _worker():
        try:
            with using_portfolio(pid):
                warm_charts()
        except Exception:
            app.logger.exception('chart warm failed')

    threading.Thread(target=_worker, daemon=True, name='chart-warm').start()


def _cash_card_context():
    """Context for the shared cash status card (latest snapshot)."""
    from app.snapshots import get_latest_snapshot
    snap = get_latest_snapshot()
    if not snap:
        return {'current_cash': None, 'cash_pct': None, 'cash_as_of': None}
    cash = snap.get('cash_balance')
    equity = snap.get('total_equity') or 0
    pct = (cash / equity * 100) if (cash is not None and equity) else None
    return {'current_cash': cash, 'cash_pct': pct, 'cash_as_of': snap.get('date')}


@app.route('/analytics')
def analytics_view():
    """Statistics deep-dive (Analytics page) on the v1.0 shell."""
    from app.analytics.portfolio_analytics import get_analytics
    return render_template('analytics.html', a=get_analytics(_get_lang()))


@app.route('/activity')
def activity_view():
    """Unified activity timeline (trades + dividends + cash) on the v1.0 shell."""
    from app.analytics.trade_analytics import get_activity
    return render_template('activity.html', rows=get_activity(_get_lang()))


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
                           deposit_dates=deposit_dates, **_cash_card_context())


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

    from app.recompute import recompute_cash
    recompute_cash()  # refresh snapshot cash/equity (also flushes)
    return redirect(url_for('transactions_view'))


@app.route('/set-cash', methods=['POST'])
def set_cash_route():
    """Record the authoritative idle-cash balance (anchors the cash series)."""
    lang = _get_lang()
    amount_str = request.form.get('amount', '').strip()
    date_str = request.form.get('date', '').strip()

    if not amount_str:
        flash(_t('flash_no_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    try:
        amount = float(amount_str)
    except ValueError:
        flash(_t('flash_invalid_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    if not math.isfinite(amount) or amount < 0:
        flash(_t('flash_invalid_amount', lang), 'error')
        return redirect(url_for('transactions_view'))

    if date_str:
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            flash(_t('flash_invalid_date', lang), 'error')
            return redirect(url_for('transactions_view'))

    try:
        from app.snapshots import set_cash_anchor
        anchor = set_cash_anchor(amount, date=date_str or None)
        flash(_t('flash_cash_success', lang,
                 amount=f'{amount:,.2f}', date=anchor['date']), 'success')
    except Exception:
        app.logger.exception('Set cash balance failed')
        flash(_t('flash_cash_error', lang), 'error')

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

    from app.recompute import recompute_cash
    recompute_cash()
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

    from app.recompute import recompute_cash
    recompute_cash()
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
    from app.analytics.chart_cache import cached
    data = cached(f'daily_summary:{start}:{end}',
                  lambda: get_daily_summary(start_date=start, end_date=end))
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

    from app.analytics.chart_cache import cached
    key = f'{start}:{end}'
    details = cached(f'daily_details:{key}',
                     lambda: get_daily_details(start_date=start, end_date=end))
    return render_template('daily_details.html', details=details, start=start, end=end)


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
    from app.recompute import recompute_after_trade_change
    recompute_after_trade_change()  # FIFO replay + cash refresh (also flushes)
    return jsonify({'success': True})


@app.route('/api/transactions/<int:doc_id>/delete', methods=['POST'])
def delete_transaction_route(doc_id):
    """Delete a transaction (and its linked tax lot if it was an interpolated buy)."""
    from app.transactions import delete_transaction
    ok = delete_transaction(doc_id)
    if not ok:
        return jsonify({'error': 'transaction not found'}), 404
    from app.recompute import recompute_after_trade_change
    recompute_after_trade_change()  # rebuild lots/P&L + cash after the delete
    return jsonify({'success': True})


@app.route('/trades')
def trades_view():
    # Retired in v1.0 — trade entry moved to the Quick-Add drawer and trade history
    # now lives in the Activity timeline. Kept as a redirect so old links don't 404.
    return redirect(url_for('activity_view'))


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
    from app.analytics.chart_cache import cached
    snapshots = list_snapshots()
    monthly = cached('graphs:monthly', get_monthly_chart_data)
    historical_perf = cached('graphs:historical_perf', get_historical_performance)
    allocation_history = cached('graphs:allocation_history', get_allocation_history)
    top_positions = cached('graphs:top_positions', get_top_positions_pnl)
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
    daily_data = cached('graphs:daily_summary', get_daily_summary)
    type_chart = cached('graphs:type_chart', get_daily_type_chart_data)
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
    from app.analytics.portfolio_analytics import get_overview
    from app.analytics.trade_analytics import get_closed_positions
    ov = get_overview(_get_lang())
    closed = get_closed_positions()
    return render_template('holdings.html', ov=ov, closed=closed)


@app.route('/rebalance')
def rebalance_view():
    # Retired in v1.0 — the rebalance page is not part of the redesigned surface.
    # Kept as a redirect so old links/bookmarks resolve to Holdings.
    return redirect(url_for('positions_view'))


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


@app.route('/api/rebalance-optimize', methods=['POST'])
def api_rebalance_optimize():
    """Compute a suggested allocation (read-only — writes nothing)."""
    from app.analytics.rebalance_optimizer import optimize
    data = request.get_json(force=True, silent=True) or {}
    mode = data.get('mode', 'full')
    method = data.get('method', 'min_variance')
    if mode not in ('full', 'within') or method not in ('min_variance', 'risk_parity', 'max_sharpe'):
        return jsonify({'ok': False, 'error': 'bad_params'}), 400
    try:
        lookback = min(max(float(data.get('lookback_years', 2.0)), 0.25), 30.0)
        max_weight = min(max(float(data.get('max_weight', 30)) / 100.0, 0.01), 1.0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_params'}), 400
    try:
        res = optimize(mode=mode, method=method, lookback_years=lookback, max_weight=max_weight)
    except Exception:
        app.logger.exception('rebalance optimize failed')
        return jsonify({'ok': False, 'error': 'compute_failed'}), 500
    return jsonify(res)


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
    from app.analytics.position_analytics import get_position_drawer
    pd = get_position_drawer(holding_id, _get_lang())
    ph = (data.get('price_history') or [])[-180:]
    return render_template('position.html', data=data, pd=pd,
                           price_series=[{'date': r['date'], 'close': r['close']} for r in ph])


@app.route('/api/holdings-lookup')
def api_holdings_lookup():
    """Active open holdings (id/name/symbol/last price) for Quick-Add autocomplete."""
    from app.analytics.portfolio_analytics import get_overview
    ov = get_overview(_get_lang())
    items = [{'id': h['holding_id'], 'name': h['name'], 'symbol': h['symbol'],
              'price': round(h['market_value'] / h['quantity'], 4) if h['quantity'] else 0}
             for h in (ov['holdings'] if ov else [])]
    return jsonify(items)


@app.route('/api/quick-add', methods=['POST'])
def api_quick_add():
    """Record a buy/sell/deposit/withdrawal from the Quick-Add drawer. Returns JSON."""
    lang = _get_lang()
    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or '').lower()
    date_str = (data.get('date') or '').strip()
    try:
        if not date_str:
            raise ValueError(_t('flash_no_date', lang))
        datetime.strptime(date_str, '%Y-%m-%d')

        if kind in ('buy', 'sell'):
            from app.manual_portfolio import record_trade
            from app.snapshots import materialize_position_in_snapshot
            hid = int(data.get('holding_id'))
            shares = float(data.get('shares'))
            price = float(data.get('price'))
            commission = float(data.get('commission') or 0)
            record_trade(hid, kind, date_str, shares, price, commission=commission)
            materialize_position_in_snapshot(hid, price)
            flush_db()
            message = _t('trade_added', lang)
        elif kind in ('deposit', 'withdraw'):
            amount = float(data.get('amount'))
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError(_t('flash_invalid_amount', lang))
            if kind == 'deposit':
                add_deposit(date=date_str, amount=amount)
            else:
                add_withdrawal(date=date_str, amount=amount)
            from app.recompute import recompute_cash
            recompute_cash()
            message = _t('trade_added', lang)
        else:
            return jsonify({'ok': False, 'error': 'unknown kind'}), 400
        _spawn_chart_warm()
        return jsonify({'ok': True, 'message': message})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e) or _t('flash_trade_error', lang)}), 400
    except Exception:
        app.logger.exception('quick-add failed')
        return jsonify({'ok': False, 'error': _t('flash_trade_error', lang)}), 500


@app.route('/api/position/<int:holding_id>')
def api_position(holding_id):
    """Lightweight JSON for the Overview position deep-dive drawer (no network)."""
    from app.analytics.position_analytics import get_position_drawer
    data = get_position_drawer(holding_id, _get_lang())
    if data is None:
        return jsonify({'error': 'not found'}), 404
    return jsonify(data)


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

    # Setting a ticker also registers the yfinance mapping (set-yfinance parity),
    # so the bulk "Refresh Yahoo Finance data" action can find this holding.
    if updates.get('ticker') and holding.get('tase_id'):
        try:
            from app.utils.translation_service import set_yfinance_mapping
            set_yfinance_mapping(holding['tase_id'], updates['ticker'], update_info=False)
        except Exception:
            app.logger.exception('Failed to register yfinance mapping')

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


def _tase_refresh_worker(pid):
    """Fetch TASE data (and Bizportal names for funds) for all holdings and write to DB.

    HTTP calls are parallelised (up to 5 concurrent); DB writes are sequential
    so TinyDB's CachingMiddleware is never written from two threads at once.
    Funds get name_tase_he from Bizportal <h1>; stocks get it from TASE lang=0.
    """
    from app.connection import set_active_portfolio
    set_active_portfolio(pid)  # bind this thread to the portfolio that triggered it
    from app.holdings import list_holdings, update_holding, SYNTHETIC_TASE_BASE
    from app.settings import get_setting, set_setting
    from app.utils.translation_service import fetch_data_from_tase, fetch_bizportal_name_he

    # Skip non-TASE / manually-added holdings — they have no real TASE number.
    holdings = [h for h in list_holdings(active_only=False)
                if not h.get('manual') and (h.get('tase_id') or 0) < SYNTHETIC_TASE_BASE]
    fund_doc_ids = {h.doc_id for h in holdings if h.get('security_type') == 'mutual_fund'}

    with _tase_lock:
        _tase_status.update({'running': True, 'updated': 0, 'failed': 0,
                              'bp_updated': 0, 'total': len(holdings), 'done': False})

    tase_results: dict = {}  # doc_id -> (holding, data_or_None)
    bp_results: dict = {}    # doc_id -> name_he_or_None

    # Phase 1: parallel HTTP fetches — TASE for all, Bizportal for funds
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            tase_futs = {pool.submit(fetch_data_from_tase, h['tase_id']): h for h in holdings}
            bp_futs = {pool.submit(fetch_bizportal_name_he, h['tase_id']): h
                       for h in holdings if h.doc_id in fund_doc_ids}
            for future in as_completed(list(tase_futs) + list(bp_futs)):
                if future in tase_futs:
                    h = tase_futs[future]
                    try:
                        tase_results[h.doc_id] = (h, future.result())
                    except Exception:
                        tase_results[h.doc_id] = (h, None)
                else:
                    h = bp_futs[future]
                    try:
                        bp_results[h.doc_id] = future.result()
                    except Exception:
                        bp_results[h.doc_id] = None
    except Exception:
        app.logger.exception('TASE parallel fetch failed')

    # Phase 2: sequential DB writes
    updated, failed, bp_updated = 0, 0, 0
    try:
        yf_map = get_setting('yfinance_map', {}) or {}
        for doc_id, (h, data) in tase_results.items():
            if data:
                field_updates = {'name_tase_en': data['name']}
                if doc_id in fund_doc_ids:
                    bp_name = bp_results.get(doc_id)
                    if bp_name:
                        field_updates['name_tase_he'] = bp_name
                        bp_updated += 1
                    elif data.get('name_tase_he'):
                        field_updates['name_tase_he'] = data['name_tase_he']
                elif data.get('name_tase_he'):
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
        _tase_status.update({'running': False, 'updated': updated, 'failed': failed,
                              'bp_updated': bp_updated, 'total': len(holdings), 'done': True})


@app.route('/maintenance/refresh-tase-names', methods=['POST'])
def admin_refresh_tase_names():
    lang = request.cookies.get('lang', 'he')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    with _tase_lock:
        if _tase_status.get('running'):
            if is_ajax:
                return jsonify({'started': False, 'reason': 'already_running'})
            flash(_t('admin_tase_refresh_running', lang), 'info')
            return redirect(url_for('maintenance'))
    from app.connection import current_portfolio_id
    thread = threading.Thread(target=_tase_refresh_worker, args=(current_portfolio_id(),),
                              daemon=True, name='tase-refresh')
    thread.start()
    if is_ajax:
        return jsonify({'started': True})
    flash(_t('admin_tase_refresh_started', lang), 'info')
    return redirect(url_for('maintenance'))


@app.route('/maintenance/refresh-tase-status')
def admin_refresh_status():
    """Return current TASE refresh status as JSON (for polling)."""
    with _tase_lock:
        return jsonify(dict(_tase_status))


# ── Background daily-history backfill state ───────────────────────────────────
_backfill_lock = threading.Lock()
_backfill_status: dict = {'running': False, 'done': True, 'result': None, 'error': None}


def _backfill_worker(pid):
    """Rebuild dense daily history for a manual/non-TASE portfolio (background)."""
    from app.connection import set_active_portfolio
    set_active_portfolio(pid)  # bind this thread to the triggering portfolio
    from app.backfill import rebuild_daily_history
    with _backfill_lock:
        _backfill_status.update({'running': True, 'done': False, 'result': None, 'error': None})
    try:
        result = rebuild_daily_history()
        with _backfill_lock:
            _backfill_status.update({'running': False, 'done': True, 'result': result, 'error': None})
    except Exception as e:
        app.logger.exception('daily-history backfill failed')
        with _backfill_lock:
            _backfill_status.update({'running': False, 'done': True, 'result': None,
                                     'error': type(e).__name__})


@app.route('/maintenance/rebuild-history', methods=['POST'])
def maintenance_rebuild_history():
    """Kick off a background rebuild of the active portfolio's daily history."""
    lang = _get_lang()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    with _backfill_lock:
        if _backfill_status.get('running'):
            if is_ajax:
                return jsonify({'started': False, 'reason': 'already_running'})
            flash(_t('rebuild_history_running', lang), 'info')
            return redirect(url_for('maintenance'))
    from app.connection import current_portfolio_id
    thread = threading.Thread(target=_backfill_worker, args=(current_portfolio_id(),),
                              daemon=True, name='backfill-history')
    thread.start()
    if is_ajax:
        return jsonify({'started': True})
    flash(_t('rebuild_history_running', lang), 'info')
    return redirect(url_for('maintenance'))


@app.route('/maintenance/rebuild-history-status')
def maintenance_rebuild_history_status():
    """Return current backfill status as JSON (for polling)."""
    with _backfill_lock:
        return jsonify(dict(_backfill_status))


@app.route('/accessibility')
def accessibility_view():
    return render_template('accessibility.html')


@app.route('/health')
def health_check():
    try:
        get_db()
        return jsonify({'status': 'ok'}), 200
    except Exception:
        app.logger.exception('Health check failed')
        return jsonify({'status': 'error'}), 503


if __name__ == '__main__':
    from app.connection import install_shutdown_handler
    install_shutdown_handler()  # flush on SIGTERM (dev server; gunicorn handles its own)
    _run_startup()
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    port = int(os.environ.get('PORT', 2501))
    print(f"Starting TradeVault server on http://localhost:{port}")
    app.run(host="0.0.0.0", debug=debug, port=port)
