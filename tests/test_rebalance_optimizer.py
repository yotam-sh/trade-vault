"""Rebalance optimizer: pure-solver properties + non-destructive mapping (no network)."""

import numpy as np

from app.connection import get_db
from app.settings import init_default_settings, get_setting
from app.holdings import add_holding
from app.snapshots import create_snapshot
from app.analytics import rebalance_optimizer as opt


# ── Pure solver ──────────────────────────────────────────────────────────────

def test_min_variance_tilts_low_vol_and_respects_cap():
    cov = np.diag([0.01, 0.04, 0.16])      # vols 10% / 20% / 40%, uncorrelated
    mu = np.zeros(3)
    w = opt.solve(mu, cov, method='min_variance', max_weight=1.0)
    assert abs(w.sum() - 1) < 1e-6 and (w >= -1e-9).all()
    assert w[0] > w[1] > w[2]              # most weight on the lowest-vol asset

    # 0.40 cap is feasible for 3 assets (3·0.40 ≥ 1); the low-vol asset hits the cap.
    capped = opt.solve(mu, cov, method='min_variance', max_weight=0.40)
    assert capped.max() <= 0.40 + 1e-6
    assert abs(capped.sum() - 1) < 1e-6
    assert capped[0] >= capped[2]


def test_risk_parity_equalizes_risk_contributions():
    cov = np.diag([0.01, 0.04, 0.16])
    w = opt.solve(np.zeros(3), cov, method='risk_parity', max_weight=1.0)
    rc = w * (cov @ w)                     # per-asset risk contribution
    assert rc.std() / rc.mean() < 0.05     # ~equal contributions


def test_max_sharpe_beats_equal_weight():
    cov = np.diag([0.04, 0.04, 0.16])
    mu = np.array([0.20, 0.05, 0.05])      # asset 0 clearly superior
    w = opt.solve(mu, cov, method='max_sharpe', max_weight=1.0)
    eq = np.full(3, 1 / 3)
    assert opt.portfolio_metrics(w, mu, cov)['sharpe'] >= opt.portfolio_metrics(eq, mu, cov)['sharpe']
    assert w[0] == w.max()


# ── optimize() mapping + non-destructiveness ─────────────────────────────────

def _price_stub(seed_map):
    """Return a fetch(symbol)->[{date,close}] over ~400 business days (deterministic)."""
    import pandas as pd
    dates = [d.strftime('%Y-%m-%d') for d in pd.bdate_range(end=pd.Timestamp.today(), periods=400)]

    def fetch(symbol):
        rng = np.random.default_rng(seed_map[symbol])
        rets = rng.normal(0.0003, 0.012, len(dates))
        price = 100 * np.cumprod(1 + rets)
        return [{'date': d, 'close': round(float(p), 4)} for d, p in zip(dates, price)]
    return fetch


def _seed_four():
    get_db(); init_default_settings()
    specs = [('AAA.TA', 'stock'), ('BBB.TA', 'stock'), ('CCC.TA', 'etf'), ('DDD.TA', 'etf')]
    positions = []
    for i, (tic, st) in enumerate(specs, start=1):
        add_holding(tase_id=i, tase_symbol=tic[:3], name_he=tic, security_type=st,
                    currency='ILS', ticker=tic)
        positions.append({'holding_id': i, 'ticker': tic, 'quantity': 10,
                          'market_value': 1000 * i, 'cost_basis': 900 * i, 'daily_pnl': 0})
    create_snapshot('2026-02-02', total_market_value=sum(p['market_value'] for p in positions),
                    total_cost_basis=1, total_daily_pnl=0, positions=positions,
                    total_deposits=1, total_withdrawals=0)
    return {'AAA.TA': 1, 'BBB.TA': 2, 'CCC.TA': 3, 'DDD.TA': 4}


def test_optimize_full_maps_to_two_levels_and_writes_nothing():
    seeds = _seed_four()
    res = opt.optimize(mode='full', method='min_variance', max_weight=0.6,
                       fetch=_price_stub(seeds))
    assert res['ok'] and res['asset_count'] == 4
    assert abs(sum(res['groups'].values()) - 100) < 0.5          # group %s of total ≈ 100
    # per-group holding %s sum to ~100 within each group
    by_group = {'stock': ['1', '2'], 'etf': ['3', '4']}
    for hids in by_group.values():
        assert abs(sum(res['holdings'][h] for h in hids) - 100) < 0.5
    assert {'ret', 'vol', 'sharpe'} <= set(res['metrics'])
    # Non-destructive: targets setting untouched by computing a suggestion.
    assert get_setting('target_allocations_v2') is None


def test_optimize_within_mode_keeps_groups_empty():
    seeds = _seed_four()
    res = opt.optimize(mode='within', method='risk_parity', max_weight=1.0,
                       fetch=_price_stub(seeds))
    assert res['ok']
    assert res['groups'] == {}                                   # group %s not proposed
    for hids in (['1', '2'], ['3', '4']):
        assert abs(sum(res['holdings'][h] for h in hids) - 100) < 0.5
    assert get_setting('target_allocations_v2') is None


def test_endpoint_read_only(monkeypatch):
    import server
    monkeypatch.setattr(server, '_login_required', lambda: False)
    monkeypatch.setitem(server.app.config, 'WTF_CSRF_ENABLED', False)
    seeds = _seed_four()
    stub = _price_stub(seeds)
    monkeypatch.setattr(opt, '_cached_history', lambda sym, ttl_hours=24: stub(sym))

    client = server.app.test_client()
    r = client.post('/api/rebalance-optimize',
                    json={'mode': 'full', 'method': 'min_variance', 'lookback_years': 2, 'max_weight': 30})
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] and data['asset_count'] == 4
    assert {'ret', 'vol', 'sharpe'} <= set(data['metrics'])
    # The endpoint must not have written targets (suggestion only).
    assert get_setting('target_allocations_v2') is None
