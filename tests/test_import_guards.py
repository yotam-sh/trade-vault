"""Daily-import guards: zero-rows and value-deviation never poison the series."""

import pandas as pd
from tinydb import Query

from app.column_map import DAILY_COLUMNS
from app.connection import get_db, get_table, PORTFOLIO_SNAPSHOTS
from app.settings import init_default_settings
from app.snapshots import create_snapshot
from app.importers.daily_importer import import_daily_portfolio

_REV = {v: k for k, v in DAILY_COLUMNS.items()}


def _write_daily_xlsx(path, rows):
    """rows: list of dicts keyed by english field names -> writes Hebrew-headed xlsx."""
    df = pd.DataFrame([{_REV[k]: v for k, v in r.items()} for r in rows])
    df.to_excel(path, index=False)


def _stock_row(tase_id, mv, name='נייר', qty=10):
    return {
        'name': name, 'tase_id': tase_id, 'symbol': f'S{tase_id}',
        'security_type': 'מניות בש"ח', 'currency': 'ILS', 'quantity': qty,
        'price': mv / qty, 'market_value': mv, 'cost_basis': mv, 'daily_pnl': 0,
    }


def _snap_count(date):
    return len(get_table(PORTFOLIO_SNAPSHOTS).search(Query().date == date))


def test_zero_rows_writes_no_snapshot(tmp_path):
    get_db(); init_default_settings()
    f = str(tmp_path / 'd.xlsx')
    # Only a skip-type row -> nothing imported.
    _write_daily_xlsx(f, [{
        'name': 'מס עתידי', 'tase_id': 999, 'symbol': '', 'security_type': 'תפ"ס/פח"ק',
        'currency': 'ILS', 'quantity': 0, 'price': 0, 'market_value': 0,
        'cost_basis': 0, 'daily_pnl': 0,
    }])
    result = import_daily_portfolio(f, data_date='2026-01-02', interpolate=False)
    assert result['status'] == 'failed'
    assert result['reason'] == 'no_rows'
    assert _snap_count('2026-01-02') == 0


def test_deviation_rejected_without_force(tmp_path):
    get_db(); init_default_settings()
    create_snapshot('2026-01-01', total_market_value=100000, total_cost_basis=100000,
                    total_daily_pnl=0, positions=[], total_deposits=100000,
                    total_withdrawals=0)
    f = str(tmp_path / 'd.xlsx')
    _write_daily_xlsx(f, [_stock_row(101, 1000)])  # 1k vs 100k prior -> 99% drop
    result = import_daily_portfolio(f, data_date='2026-01-02', interpolate=False)
    assert result['status'] == 'rejected'
    assert result['reason'] == 'deviation'
    assert _snap_count('2026-01-02') == 0


def test_deviation_bypassed_with_force(tmp_path):
    get_db(); init_default_settings()
    create_snapshot('2026-01-01', total_market_value=100000, total_cost_basis=100000,
                    total_daily_pnl=0, positions=[], total_deposits=100000,
                    total_withdrawals=0)
    f = str(tmp_path / 'd.xlsx')
    _write_daily_xlsx(f, [_stock_row(101, 1000)])
    result = import_daily_portfolio(f, data_date='2026-01-02', interpolate=False, force=True)
    assert result['status'] in ('success', 'partial')
    assert _snap_count('2026-01-02') == 1


def test_within_band_imports_normally(tmp_path):
    get_db(); init_default_settings()
    create_snapshot('2026-01-01', total_market_value=100000, total_cost_basis=100000,
                    total_daily_pnl=0, positions=[], total_deposits=100000,
                    total_withdrawals=0)
    f = str(tmp_path / 'd.xlsx')
    _write_daily_xlsx(f, [_stock_row(101, 95000)])  # within 50% band
    result = import_daily_portfolio(f, data_date='2026-01-02', interpolate=False)
    assert result['status'] in ('success', 'partial')
    assert _snap_count('2026-01-02') == 1
