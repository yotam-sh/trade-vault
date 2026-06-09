"""Chart cache: version token invalidation, memoization, and pruning."""

from app.connection import get_db, get_table, CHART_CACHE
from app.settings import init_default_settings
from app.holdings import add_holding
from app.snapshots import create_snapshot
from app.analytics.chart_cache import data_version, cached


def _snap(date, mv=5000):
    create_snapshot(date, total_market_value=mv, total_cost_basis=4000,
                    total_daily_pnl=0, positions=[], total_deposits=4000,
                    total_withdrawals=0)


def _seed():
    get_db(); init_default_settings()
    add_holding(tase_id=10, tase_symbol='נ', name_he='נקסטקום',
                security_type='stock', currency='ILS', ticker='NXTM.TA')
    _snap('2026-02-02')


def test_data_version_changes_when_data_changes():
    _seed()
    v1 = data_version()
    _snap('2026-02-03')          # new snapshot → count + latest date change
    v2 = data_version()
    assert v1 != v2


def test_cached_memoizes_until_version_changes():
    _seed()
    calls = {'n': 0}

    def builder():
        calls['n'] += 1
        return [{'value': calls['n']}]

    first = cached('t', builder)
    second = cached('t', builder)               # served from cache, builder NOT re-run
    assert calls['n'] == 1
    assert first == second == [{'value': 1}]

    _snap('2026-02-03')                          # version changes → recompute
    third = cached('t', builder)
    assert calls['n'] == 2
    assert third == [{'value': 2}]


def test_cached_payload_matches_fresh_compute():
    _seed()
    fresh = sorted([3, 1, 2])
    assert cached('sortlist', lambda: sorted([3, 1, 2])) == fresh


def test_prune_drops_stale_version_entries():
    _seed()
    cached('a', lambda: [1])
    cached('b', lambda: [2])
    assert len(get_table(CHART_CACHE)) == 2

    _snap('2026-02-03')                          # bump version
    cached('a', lambda: [1])                     # recompute 'a' → prunes stale 'b'
    rows = get_table(CHART_CACHE).all()
    assert [r['name'] for r in rows] == ['a']    # stale 'b' pruned
    assert rows[0]['version'] == data_version()
