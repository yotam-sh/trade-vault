"""Isolated multi-portfolio: data separation, shared market data, lifecycle guards."""

from app import portfolios
from app.connection import get_db, using_portfolio
from app.settings import init_default_settings, get_shared_setting, set_shared_setting
from app.holdings import add_holding, list_holdings


def _ids():
    return {h['tase_id'] for h in list_holdings(active_only=False)}


def test_data_isolated_between_portfolios():
    get_db(); init_default_settings()
    add_holding(tase_id=1, tase_symbol='A', name_he='aaa', security_type='stock', currency='ILS')

    pid = portfolios.create_portfolio('Second')
    with using_portfolio(pid):
        assert _ids() == set()  # brand-new portfolio starts empty
        add_holding(tase_id=2, tase_symbol='B', name_he='bbb', security_type='stock', currency='ILS')
        assert _ids() == {2}

    assert _ids() == {1}                      # default portfolio untouched
    with using_portfolio(pid):
        assert _ids() == {2}                  # B's data persists, separate file


def test_shared_store_is_shared_across_portfolios():
    get_db(); init_default_settings()
    set_shared_setting('shared_probe', {'a': 1})

    pid = portfolios.create_portfolio('Second')
    with using_portfolio(pid):
        # the shared store is the same file regardless of active portfolio
        assert get_shared_setting('shared_probe') == {'a': 1}
        set_shared_setting('shared_probe', {'a': 1, 'b': 2})
    assert get_shared_setting('shared_probe') == {'a': 1, 'b': 2}


def test_yfinance_map_is_per_portfolio():
    """yfinance_map is now per-portfolio (was shared) — no cross-portfolio bleed."""
    from app.utils.translation_service import get_yfinance_mapping
    from app.settings import set_setting
    get_db(); init_default_settings()
    set_setting('yfinance_map', {'629014': 'TEVA.TA'})   # default portfolio

    pid = portfolios.create_portfolio('Second')
    with using_portfolio(pid):
        assert get_yfinance_mapping() == {}              # isolated — does not see default's map
        set_setting('yfinance_map', {'1': 'AAPL'})
        assert get_yfinance_mapping('1') == 'AAPL'

    assert get_yfinance_mapping('629014') == 'TEVA.TA'   # default unchanged


def test_lifecycle_and_guards():
    get_db(); init_default_settings()
    portfolios.list_portfolios()  # bootstraps the registry with the default entry

    ok, _ = portfolios.delete_portfolio('default')
    assert not ok                              # cannot delete the default

    pid = portfolios.create_portfolio('Two')
    assert portfolios.exists(pid)
    assert portfolios.rename_portfolio(pid, 'Renamed')
    assert portfolios.get_portfolio(pid)['name'] == 'Renamed'

    ok, _ = portfolios.delete_portfolio(pid)
    assert ok and not portfolios.exists(pid)


def test_set_default_reassign_and_redelete():
    get_db(); init_default_settings()
    portfolios.list_portfolios()  # bootstrap registry with 'default'

    pid = portfolios.create_portfolio('Two')
    assert portfolios.set_default(pid)
    assert portfolios.default_id() == pid

    # The old default is now deletable; the new default is protected.
    ok, _ = portfolios.delete_portfolio('default')
    assert ok
    ok, _ = portfolios.delete_portfolio(pid)   # now the only one AND default
    assert not ok
