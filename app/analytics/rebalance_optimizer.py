"""Classical portfolio optimizer for the rebalance page.

STRICTLY NON-DESTRUCTIVE: this module only *computes suggested* target weights from
historical risk/return. It never writes holdings, transactions, snapshots, or settings.
The user reviews a suggestion and explicitly applies it; applying writes only the
existing `target_allocations_v2` setting (handled by the route/JS, not here).

The pure solver (`solve` / `covariance` / `expected_returns` / `portfolio_metrics`)
takes plain arrays and is unit-tested without any network.
"""

import numpy as np

TRADING_DAYS = 252
TYPE_ORDER = ['stock', 'mutual_fund', 'etf', 'bond', 'other']


# ── Pure math (no I/O) ───────────────────────────────────────────────────────

def covariance(returns):
    """Annualized covariance via Ledoit-Wolf shrinkage. `returns`: (T, N) array."""
    from sklearn.covariance import LedoitWolf
    returns = np.asarray(returns, float)
    cov = LedoitWolf().fit(returns).covariance_
    return cov * TRADING_DAYS


def expected_returns(returns):
    """Annualized historical mean returns. `returns`: (T, N) array."""
    return np.mean(np.asarray(returns, float), axis=0) * TRADING_DAYS


def portfolio_metrics(w, mu, cov, rf=0.0):
    w = np.asarray(w, float)
    mu = np.asarray(mu, float)
    cov = np.asarray(cov, float)
    ret = float(w @ mu)
    vol = float(np.sqrt(max(float(w @ cov @ w), 0.0)))
    sharpe = (ret - rf) / vol if vol > 1e-12 else 0.0
    return {'ret': ret, 'vol': vol, 'sharpe': sharpe}


def solve(mu, cov, method='min_variance', max_weight=1.0, rf=0.0):
    """Long-only weights summing to 1, each ≤ max_weight, for the given objective."""
    from scipy.optimize import minimize
    cov = np.asarray(cov, float)
    mu = np.asarray(mu, float)
    n = cov.shape[0]
    if n == 0:
        return np.array([])
    if n == 1:
        return np.array([1.0])

    cap = max(float(max_weight), 1.0 / n)  # keep the simplex feasible
    bounds = [(0.0, cap)] * n
    cons = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
    x0 = np.full(n, 1.0 / n)

    if method == 'min_variance':
        obj = lambda w: float(w @ cov @ w)
    elif method == 'max_sharpe':
        def obj(w):
            vol = np.sqrt(max(float(w @ cov @ w), 1e-12))
            return -(float(w @ mu) - rf) / vol
    elif method == 'risk_parity':
        def obj(w):
            port_var = float(w @ cov @ w)
            rc = w * (cov @ w)                 # risk contribution per asset
            return float(np.sum((rc - port_var / n) ** 2))
    else:
        raise ValueError(f'unknown method: {method}')

    res = minimize(obj, x0, method='SLSQP', bounds=bounds, constraints=cons,
                   options={'maxiter': 1000, 'ftol': 1e-12})
    w = np.clip(np.asarray(res.x, float), 0.0, cap)
    s = w.sum()
    return w / s if s > 0 else x0


# ── Data fetch + mapping (I/O; read-only) ────────────────────────────────────

def _cached_history(symbol, ttl_hours=24):
    """Deep price history for a symbol, cached in the shared store (market data)."""
    from datetime import datetime, timedelta
    from app.settings import get_shared_setting, set_shared_setting
    key = f'yf_hist:{symbol}'
    cached = get_shared_setting(key)
    if cached:
        try:
            if datetime.now() - datetime.fromisoformat(cached['fetched']) < timedelta(hours=ttl_hours):
                return cached['data']
        except Exception:
            pass
    from app.utils.translation_service import get_yfinance_history
    data = [{'date': h['date'], 'close': h['close']} for h in get_yfinance_history(symbol)]
    if data:
        set_shared_setting(key, {'fetched': datetime.now().isoformat(), 'data': data})
    return data


def _returns_for(symbols, lookback_years, fetch=None):
    """Aligned daily returns over the lookback window.

    Returns (returns_ndarray (T,N), kept_symbols_in_column_order, dropped_symbols).
    `fetch(symbol) -> [{date, close}]` is injectable for tests (no network).
    """
    import pandas as pd
    from datetime import date, timedelta
    fetch = fetch or _cached_history
    cutoff = (date.today() - timedelta(days=int(lookback_years * 365))).isoformat()

    series, dropped = {}, []
    for sym in symbols:
        hist = fetch(sym)
        s = pd.Series({h['date']: h['close'] for h in (hist or []) if h['date'] >= cutoff})
        if len(s) < 30:
            dropped.append(sym)
        else:
            series[sym] = s
    if len(series) < 2:
        return None, list(series.keys()), dropped

    df = pd.DataFrame(series).sort_index().dropna()  # align on common dates
    rets = df.pct_change().dropna()
    if len(rets) < 20:
        return None, list(df.columns), dropped
    return rets.values, list(df.columns), dropped


def optimize(mode='full', method='min_variance', lookback_years=2.0,
             max_weight=0.30, rf=0.0, fetch=None):
    """Compute a suggested allocation. Read-only — writes nothing.

    Returns a dict consumed by the rebalance page:
      {ok, mode, method, groups, holdings, current, current_groups,
       holding_pct_of_total, metrics, excluded, asset_count}
    `groups`/`holdings` are percentages (group of total; holding within its group).
    """
    from app.analytics.portfolio_analytics import get_portfolio_value
    from app.utils.translation_service import get_yfinance_mapping
    from app.holdings import get_holding
    from app.settings import get_setting

    pf = get_portfolio_value() or {}
    positions = [p for p in (pf.get('positions') or []) if (p.get('quantity') or 0) > 0]
    total_value = pf.get('total_value', 0) or 0
    if not positions:
        return {'ok': False, 'error': 'empty_portfolio', 'excluded': []}

    assets, excluded = [], []
    for p in positions:
        hid = p['holding_id']
        h = get_holding(hid) or {}
        sym = p.get('ticker') or get_yfinance_mapping(h.get('tase_id'))
        name = p.get('name_tase_en') or p.get('name_en') or p.get('name_he')
        st = p.get('security_type') or 'other'
        if st not in TYPE_ORDER:
            st = 'other'
        if not sym:
            excluded.append({'holding_id': hid, 'name': name, 'reason': 'no_symbol'})
            continue
        assets.append({'holding_id': hid, 'symbol': sym, 'security_type': st,
                       'market_value': p.get('market_value', 0) or 0, 'name': name})

    symbols = [a['symbol'] for a in assets]
    rets, kept_syms, dropped = _returns_for(symbols, lookback_years, fetch=fetch)
    for a in assets:
        if a['symbol'] in dropped:
            excluded.append({'holding_id': a['holding_id'], 'name': a['name'],
                             'reason': 'insufficient_history'})
    if rets is None:
        return {'ok': False, 'error': 'insufficient_data', 'excluded': excluded}

    # Reorder kept assets to match the returns columns.
    by_sym = {a['symbol']: a for a in assets}
    kept = [by_sym[s] for s in kept_syms if s in by_sym]
    if len(kept) < 2:
        return {'ok': False, 'error': 'insufficient_data', 'excluded': excluded}

    cov = covariance(rets)
    mu = expected_returns(rets)

    # ── Current weights (for the "already aligned" highlight) ────────────────
    group_value = {}
    for a in kept:
        group_value[a['security_type']] = group_value.get(a['security_type'], 0.0) + a['market_value']
    kept_value = sum(a['market_value'] for a in kept) or 0.0
    current = {str(a['holding_id']): (round(a['market_value'] / group_value[a['security_type']] * 100, 2)
                                      if group_value[a['security_type']] else 0.0) for a in kept}
    current_groups = {t: (round(v / kept_value * 100, 2) if kept_value else 0.0)
                      for t, v in group_value.items()}

    idx = {a['holding_id']: i for i, a in enumerate(kept)}

    # Current full-portfolio weights (market value) → before/after metrics.
    cur_w = np.array([(a['market_value'] / kept_value if kept_value else 0.0) for a in kept])
    current_metrics = portfolio_metrics(cur_w, mu, cov, rf)

    if mode == 'within':
        # Optimize the holdings *inside each group* separately; keep group %s as set.
        holdings_pct = {}
        w_global = np.zeros(len(kept))
        for st in {a['security_type'] for a in kept}:
            members = [a for a in kept if a['security_type'] == st]
            cols = [idx[a['holding_id']] for a in members]
            sub_w = solve(mu[cols], cov[np.ix_(cols, cols)], method, max_weight, rf)
            for a, wi in zip(members, sub_w):
                holdings_pct[str(a['holding_id'])] = round(float(wi) * 100, 2)
                w_global[idx[a['holding_id']]] = wi
        groups_pct = {}  # not proposed in this mode
        # Effective full-portfolio weights for metrics use the user's current group targets.
        gt = (get_setting('target_allocations_v2', {}) or {}).get('groups', {})
        eff = np.zeros(len(kept))
        for a in kept:
            gfrac = float(gt.get(a['security_type'], current_groups.get(a['security_type'], 0))) / 100.0
            eff[idx[a['holding_id']]] = gfrac * w_global[idx[a['holding_id']]]
        eff = eff / eff.sum() if eff.sum() > 0 else w_global
        metrics = portfolio_metrics(eff, mu, cov, rf)
        holding_pct_of_total = {str(a['holding_id']): round(float(eff[idx[a['holding_id']]]) * 100, 2)
                                for a in kept}
    else:  # full
        w = solve(mu, cov, method, max_weight, rf)
        groups_w = {}
        for a in kept:
            groups_w[a['security_type']] = groups_w.get(a['security_type'], 0.0) + float(w[idx[a['holding_id']]])
        groups_pct = {t: round(gw * 100, 2) for t, gw in groups_w.items()}
        holdings_pct = {}
        for a in kept:
            gw = groups_w[a['security_type']]
            wi = float(w[idx[a['holding_id']]])
            holdings_pct[str(a['holding_id'])] = round(wi / gw * 100, 2) if gw > 1e-12 else 0.0
        metrics = portfolio_metrics(w, mu, cov, rf)
        holding_pct_of_total = {str(a['holding_id']): round(float(w[idx[a['holding_id']]]) * 100, 2)
                                for a in kept}

    return {
        'ok': True,
        'mode': mode,
        'method': method,
        'groups': groups_pct,
        'holdings': holdings_pct,
        'current': current,
        'current_groups': current_groups,
        'holding_pct_of_total': holding_pct_of_total,
        'metrics': metrics,
        'current_metrics': current_metrics,
        'excluded': excluded,
        'asset_count': len(kept),
    }
