"""Build a realistic DEMO portfolio in its own isolated portfolio (Phase 2).

One-off dev/demo generator (NOT a shipped feature). Creates a believable "production-
looking" portfolio of well-known TASE securities with multi-month daily history, using
REAL Yahoo Finance prices where available (synthetic random-walk fallback otherwise) and
fabricated quantities/cashflows. Leaves the real db.json untouched — everything lands in
a separate portfolio file under db/portfolios/.

Run:  python scripts/build_demo_portfolio.py
Idempotent: re-running deletes and rebuilds the demo portfolio.
"""

import os
import sys
import io
import math
import random
from datetime import date, timedelta

# UTF-8 console (Hebrew names / arrows) on Windows.
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import portfolios
from app.connection import using_portfolio, flush_db
from app.holdings import add_holding, update_holding
from app.transactions import add_deposit, add_buy, add_sell
from app.daily_prices import add_daily_price
from app.snapshots import generate_snapshot_from_prices, set_cash_anchor
from app.settings import set_setting
from app.recompute import recompute_after_trade_change
from app.utils.translation_service import get_yfinance_history

DEMO_NAME = 'תיק הדגמה (Demo)'
random.seed(42)

# Curated TA-35 names. `ticker` = Yahoo symbol (real history). funds/bond have no Yahoo
# symbol → synthetic series + flagged "excluded" by the optimizer (realistic). `alloc` =
# initial target ILS value (quantities are derived from it, so price units don't matter).
SECURITIES = [
    dict(tase_id=629014,  name_he='טבע',            name_en='Teva Pharmaceutical', name_tase_en='TEVA',        ticker='TEVA.TA', type='stock', alloc=16000),
    dict(tase_id=273011,  name_he='נייס',           name_en='NICE',                name_tase_en='NICE',        ticker='NICE.TA', type='stock', alloc=18000),
    dict(tase_id=1081124, name_he='אלביט מערכות',   name_en='Elbit Systems',       name_tase_en='ELBIT SYS',   ticker='ESLT.TA', type='stock', alloc=17000),
    dict(tase_id=281014,  name_he='איי.סי.אל',      name_en='ICL Group',           name_tase_en='ICL',         ticker='ICL.TA',  type='stock', alloc=12000),
    dict(tase_id=604611,  name_he='לאומי',          name_en='Bank Leumi',          name_tase_en='LEUMI',       ticker='LUMI.TA', type='stock', alloc=15000),
    dict(tase_id=662577,  name_he='פועלים',         name_en='Bank Hapoalim',       name_tase_en='HAPOALIM',    ticker='POLI.TA', type='stock', alloc=15000),
    dict(tase_id=695437,  name_he='מזרחי טפחות',    name_en='Mizrahi Tefahot',     name_tase_en='MIZRAHI TEF', ticker='MZTF.TA', type='stock', alloc=11000),
    dict(tase_id=767012,  name_he='הפניקס',         name_en='Phoenix Holdings',    name_tase_en='PHOENIX',     ticker='PHOE.TA', type='stock', alloc=9000),
    dict(tase_id=1084557, name_he='נובה',           name_en='Nova',                name_tase_en='NOVA',        ticker='NVMI.TA', type='stock', alloc=14000),
    dict(tase_id=1082379, name_he='טאואר',          name_en='Tower Semiconductor', name_tase_en='TOWER',       ticker='TSEM.TA', type='stock', alloc=10000),
    dict(tase_id=1119478, name_he='עזריאלי',        name_en='Azrieli Group',       name_tase_en='AZRIELI',     ticker='AZRG.TA', type='stock', alloc=12000),
    dict(tase_id=230011,  name_he='בזק',            name_en='Bezeq',               name_tase_en='BEZEQ',       ticker='BEZQ.TA', type='stock', alloc=8000),
    dict(tase_id=1143564, name_he='קסם תל אביב 125', name_en='Kesem TA-125 ETF',   name_tase_en='KSEM TA-125', ticker=None,      type='etf',   alloc=22000),
    dict(tase_id=1159250, name_he='מגדל S&P 500',   name_en='Migdal S&P 500',      name_tase_en='MGDL SP500',  ticker=None,      type='mutual_fund', alloc=18000),
    dict(tase_id=1135967, name_he='ממשלתי שקלי 0330', name_en='Israel Govt Bond 0330', name_tase_en='GOV ILS 0330', ticker=None, type='bond', alloc=14000),
]

WINDOW_DAYS = 200       # calendar span fetched
MAX_TRADING_DAYS = 130  # cap the series length


def _fetch_prices(sec, start_iso, end_iso):
    """Return {date_iso: close} within [start,end], or {} if none."""
    if not sec['ticker']:
        return {}
    try:
        data = get_yfinance_history(sec['ticker'])
    except Exception:
        data = []
    return {h['date']: h['close'] for h in (data or [])
            if start_iso <= h['date'] <= end_iso and h.get('close')}


def _synthetic_series(dates, base):
    """Deterministic-ish geometric random walk over `dates`, starting near `base`."""
    out, p = {}, float(base)
    for d in dates:
        p *= (1 + random.gauss(0.0004, 0.011))
        out[d] = round(max(p, 0.5), 2)
    return out


def _series_on_calendar(prices, calendar, base):
    """Forward-fill a price map onto the calendar; synthesize if empty."""
    if not prices:
        return _synthetic_series(calendar, base)
    out, last = {}, None
    for d in calendar:
        if d in prices:
            last = prices[d]
        out[d] = last if last is not None else next(iter(prices.values()))
    return out


def build():
    # ── Reset: delete any prior demo, create fresh isolated portfolio ──
    for p in portfolios.list_portfolios():
        if p['name'] == DEMO_NAME:
            portfolios.delete_portfolio(p['id'])
    pid = portfolios.create_portfolio(DEMO_NAME)
    print(f"Created demo portfolio: {pid}")

    end = date.today()
    start = end - timedelta(days=WINDOW_DAYS)
    start_iso, end_iso = start.isoformat(), end.isoformat()

    # ── Fetch real prices; derive the trading calendar from real data ──
    raw = {s['tase_id']: _fetch_prices(s, start_iso, end_iso) for s in SECURITIES}
    real_dates = sorted({d for m in raw.values() for d in m})
    if real_dates:
        calendar = real_dates[-MAX_TRADING_DAYS:]
    else:
        calendar = [(start + timedelta(days=i)).isoformat()
                    for i in range(WINDOW_DAYS) if (start + timedelta(days=i)).weekday() < 5][-MAX_TRADING_DAYS:]
    n_fetched = sum(1 for m in raw.values() if m)
    print(f"Calendar: {len(calendar)} trading days ({calendar[0]} → {calendar[-1]}); "
          f"{n_fetched}/{len(SECURITIES)} tickers fetched from Yahoo, rest synthetic.")

    # Realistic ILS start prices. TASE Yahoo data mixes agorot/shekel units, so we pin
    # each series to a sane ILS start price while preserving its real return SHAPE — that
    # keeps positions coherent and P&L authentic without unit guesswork.
    bases = {629014: 18, 273011: 185, 1081124: 1250, 281014: 23, 604611: 35,
             662577: 43, 695437: 145, 767012: 48, 1084557: 920, 1082379: 95,
             1119478: 300, 230011: 5.2, 1143564: 145, 1159250: 210, 1135967: 102}
    series = {}
    for s in SECURITIES:
        tid = s['tase_id']
        raw_series = _series_on_calendar(raw[tid], calendar, bases[tid])
        p0 = raw_series[calendar[0]] or bases[tid]
        factor = bases[tid] / p0 if p0 else 1.0
        series[tid] = {d: round(v * factor, 4) for d, v in raw_series.items()}

    with using_portfolio(pid):
        # Holdings
        hid = {}
        for s in SECURITIES:
            h = add_holding(tase_id=s['tase_id'], tase_symbol=s['name_he'][:8], name_he=s['name_he'],
                            security_type=s['type'], currency='ILS', ticker=s['ticker'],
                            name_en=s['name_en'], first_bought=calendar[0])
            update_holding(h, name_tase_en=s['name_tase_en'], name_tase_he=s['name_he'])
            hid[s['tase_id']] = h

        # ── Trade schedule (events per security) ──
        add_on_day = calendar[len(calendar) // 3]
        sell_day = calendar[2 * len(calendar) // 3]
        events = {s['tase_id']: [] for s in SECURITIES}  # (date, kind, shares, price)
        total_initial = 0.0
        for i, s in enumerate(SECURITIES):
            tid = s['tase_id']
            p0 = series[tid][calendar[0]]
            shares0 = max(1, round(s['alloc'] / p0))
            events[tid].append((calendar[0], 'buy', shares0, p0))
            total_initial += shares0 * p0
            # A few add-on buys and partial sells for realism
            if i % 4 == 0:
                events[tid].append((add_on_day, 'buy', max(1, shares0 // 3), series[tid][add_on_day]))
            if i % 5 == 2:
                events[tid].append((sell_day, 'sell', max(1, shares0 // 4), series[tid][sell_day]))

        # ── Deposits (fund the buys, with a buffer) ──
        add_deposit(date=calendar[0], amount=round(total_initial * 1.06, 2), source='demo')
        add_deposit(date=add_on_day, amount=25000, source='demo')

        # ── Emit transactions ──
        for s in SECURITIES:
            tid = s['tase_id']
            for d, kind, sh, pr in events[tid]:
                if kind == 'buy':
                    add_buy(ticker=s['ticker'] or s['name_en'], holding_id=hid[tid], date=d,
                            shares=sh, price_per_share=round(pr, 4), source='demo')
                else:
                    add_sell(ticker=s['ticker'] or s['name_en'], holding_id=hid[tid], date=d,
                             shares=sh, price_per_share=round(pr, 4), source='demo')

        # ── Per-day daily_prices + snapshot (the importer's path) ──
        for di, d in enumerate(calendar):
            day_rows = []
            for s in SECURITIES:
                tid = s['tase_id']
                # running shares + weighted-avg cost as of day d
                shares, cost = 0.0, 0.0
                for ed, kind, sh, pr in sorted(events[tid]):
                    if ed > d:
                        break
                    if kind == 'buy':
                        shares += sh; cost += sh * pr
                    else:
                        if shares > 0:
                            cost -= (sh / shares) * cost
                        shares -= sh
                if shares <= 0:
                    continue
                price = series[tid][d]
                prev = series[tid][calendar[di - 1]] if di > 0 else price
                mv = round(shares * price, 2)
                cb = round(cost, 2)
                day_rows.append({
                    'holding_id': hid[tid], 'ticker': s['ticker'] or s['name_en'], 'date': d,
                    'price': round(price, 4), 'quantity': shares, 'market_value': mv,
                    'cost_basis': cb, 'currency': 'ILS',
                    'daily_pnl': round(shares * (price - prev), 2),
                    'price_change_pct': round((price / prev - 1) * 100, 2) if prev else 0,
                })
            for r in day_rows:
                add_daily_price(import_id=None, **r)
            generate_snapshot_from_prices(d, day_rows)

        set_setting('last_import_date', calendar[-1])

        # ── Finalize: tax lots, a clean cash figure, sensible rebalance targets ──
        recompute_after_trade_change()
        set_cash_anchor(8650.0, date=calendar[-1])
        set_setting('target_allocations_v2', {
            'groups': {'stock': 60, 'etf': 18, 'mutual_fund': 14, 'bond': 8},
            'holdings': {},  # leave holding-level targets for the optimizer to suggest
        })
        flush_db()

    print(f"Demo portfolio '{DEMO_NAME}' built with {len(SECURITIES)} holdings over "
          f"{len(calendar)} trading days. Switch to it from the portfolio switcher.")
    return pid


if __name__ == '__main__':
    build()
