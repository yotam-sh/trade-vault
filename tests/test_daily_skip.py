"""Daily import skips cash/FX balance rows (e.g. the USD row 'דולר ארה"ב')."""

import pandas as pd

from app.connection import get_db
from app.settings import init_default_settings
from app.holdings import list_holdings


def test_daily_import_skips_usd_cash_row(tmp_path):
    get_db(); init_default_settings()
    from app.importers.daily_importer import import_daily_portfolio

    df = pd.DataFrame([
        {'שם נייר': 'טבע', 'מספר נייר': 629014, 'סוג נייר': 'מניות בש"ח',
         'מטבע': 'שקל חדש', 'כמות נוכחית': 10, 'שער': 100, 'שווי נוכחי': 1000, 'עלות': 900},
        {'שם נייר': 'דולר ארה"ב', 'מספר נייר': 99028, 'סוג נייר': '',
         'מטבע': 'שקל חדש', 'כמות נוכחית': 5000, 'שער': 1, 'שווי נוכחי': 5000, 'עלות': 5000},
    ])
    path = tmp_path / 'data_2026-06-19.xlsx'
    df.to_excel(path, index=False)

    res = import_daily_portfolio(str(path), data_date='2026-06-19', force=True)

    names = {h['name_he'] for h in list_holdings(active_only=False)}
    assert 'טבע' in names                 # real security imported
    assert 'דולר ארה"ב' not in names      # USD cash row skipped, no holding created
    assert res['rows_imported'] == 1
    assert res['rows_skipped'] >= 1


def test_daily_import_skips_fx_cash_and_foreign_types(tmp_path):
    get_db(); init_default_settings()
    from app.importers.daily_importer import import_daily_portfolio

    df = pd.DataFrame([
        {'שם נייר': 'טבע', 'מספר נייר': 629014, 'סוג נייר': 'מניות בש"ח',
         'מטבע': 'שקל חדש', 'כמות נוכחית': 10, 'שער': 100, 'שווי נוכחי': 1000, 'עלות': 900},
        {'שם נייר': 'התחיבות דולרית', 'מספר נייר': 99218, 'סוג נייר': 'מט"ח מזומן',
         'מטבע': 'שקל חדש', 'כמות נוכחית': -616, 'שער': 294, 'שווי נוכחי': -1813, 'עלות': 0},
        {'שם נייר': 'ASTS US', 'מספר נייר': 24847121, 'סוג נייר': 'מניה זרה בחו"ל',
         'מטבע': 'דולר אמריקאי', 'כמות נוכחית': 4, 'שער': 80, 'שווי נוכחי': 949, 'עלות': 930},
    ])
    path = tmp_path / 'data_2026-06-20.xlsx'
    df.to_excel(path, index=False)

    res = import_daily_portfolio(str(path), data_date='2026-06-20', force=True)
    names = {h['name_he'] for h in list_holdings(active_only=False)}
    assert names == {'טבע'}                # only the ILS stock imported
    assert 'התחיבות דולרית' not in names   # FX cash excluded
    assert 'ASTS US' not in names          # foreign stock excluded
    assert res['rows_imported'] == 1
    assert res['rows_skipped'] == 2
