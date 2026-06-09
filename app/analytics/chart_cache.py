"""Computed-chart cache.

The `/graphs` page (and the daily summary/details pages) recompute several heavy
analytics functions on every request, on a single gunicorn worker/thread. The
underlying data changes about once a day (the daily import), so this memoizes the
computed payloads in the `chart_cache` table, keyed by a cheap data-version token
that self-invalidates whenever the data changes — no per-mutation hooks needed.

This is derived, regenerable data: it is dropped on backup restore and is safe to
clear at any time.
"""

import logging

from tinydb import Query

from app.connection import (
    get_table, flush_db, _db_lock,
    CHART_CACHE, PORTFOLIO_SNAPSHOTS, TRANSACTIONS, DAILY_PRICES,
)

logger = logging.getLogger(__name__)


def data_version():
    """Cheap token describing the current data state.

    Composed from the row counts of the tables that feed the charts plus the most
    recent snapshot's date and market value. Any import / trade / delete — and any
    in-place repair of the latest snapshot — changes this string, so cache entries
    stamped with an older token are ignored.
    """
    n_snap = len(get_table(PORTFOLIO_SNAPSHOTS))
    n_txn = len(get_table(TRANSACTIONS))
    n_dp = len(get_table(DAILY_PRICES))

    latest_date, latest_mv = '', ''
    from app.snapshots import get_latest_snapshot
    latest = get_latest_snapshot()
    if latest:
        latest_date = latest.get('date', '')
        latest_mv = round(latest.get('total_market_value', 0) or 0, 2)

    return f'{n_snap}:{n_txn}:{n_dp}:{latest_date}:{latest_mv}'


def cached(name, builder):
    """Return builder() for `name`, memoized against the current data_version().

    On a version match the stored payload is returned without calling builder().
    Otherwise builder() runs and its result is stored under the current version.
    """
    version = data_version()
    table = get_table(CHART_CACHE)
    C = Query()

    doc = table.get(C.name == name)
    if doc is not None and doc.get('version') == version:
        return doc['payload']

    payload = builder()
    with _db_lock:
        table.upsert({'name': name, 'version': version, 'payload': payload}, C.name == name)
        # Prune entries from older data versions so parameterized keys (date ranges)
        # don't accumulate across imports.
        table.remove(C.version != version)
        flush_db()
    return payload


def warm_charts():
    """Precompute and store the heavy `/graphs` payloads for the current data.

    Best-effort — intended to run in a background thread after an import so the next
    page visit is served warm. Exceptions are logged and swallowed.
    """
    from app.analytics.monthly_summary import get_monthly_chart_data
    from app.analytics.daily_analytics import (
        get_historical_performance, get_daily_summary, get_daily_type_chart_data,
    )
    from app.analytics.portfolio_analytics import get_allocation_history
    from app.analytics.position_analytics import get_top_positions_pnl

    # Only JSON-safe, |tojson-consumed payloads are cached. The yearly/potential tax
    # builders are consumed server-side with int year keys / tuples, so they are NOT
    # cached (a JSON round-trip would coerce int keys to strings).
    builders = {
        'graphs:monthly': get_monthly_chart_data,
        'graphs:historical_perf': get_historical_performance,
        'graphs:allocation_history': get_allocation_history,
        'graphs:top_positions': get_top_positions_pnl,
        'graphs:daily_summary': get_daily_summary,
        'graphs:type_chart': get_daily_type_chart_data,
    }
    for name, builder in builders.items():
        try:
            cached(name, builder)
        except Exception:
            logger.exception('warm_charts failed for %s', name)
