"""Per-portfolio display currency (Phase 1): helpers + registry."""

from app import portfolios
from app.currency import currency_symbol, normalize_currency, is_agorot


def test_currency_symbol_map():
    assert currency_symbol('ILS') == '₪'
    assert currency_symbol('USD') == '$'
    assert currency_symbol('EUR') == '€'
    assert currency_symbol('GBP') == '£'
    # Unknown codes fall back to the (normalized) code itself.
    assert currency_symbol('SEK') == 'SEK'
    assert currency_symbol('usd') == '$'   # case-insensitive
    assert currency_symbol('') == '₪'      # empty → ILS default → ₪


def test_normalize_and_agorot():
    assert normalize_currency('usd') == 'USD'
    assert normalize_currency(None) == 'ILS'
    assert normalize_currency('  eur ') == 'EUR'
    # Agorot (×100 subunit) only applies to ILS/TASE.
    assert is_agorot('ILS') is True
    assert is_agorot('USD') is False


def test_registry_currency_roundtrip():
    # New portfolio created with an explicit currency.
    pid = portfolios.create_portfolio('USD book', currency='usd')
    assert portfolios.get_currency(pid) == 'USD'

    # Changing it persists.
    assert portfolios.set_currency(pid, 'EUR') is True
    assert portfolios.get_currency(pid) == 'EUR'

    # Unknown portfolio returns the default and a False on set.
    assert portfolios.get_currency('nope') == 'ILS'
    assert portfolios.set_currency('nope', 'USD') is False


def test_default_currency_backfill():
    # The default ('IBI') portfolio reports ILS even though older registries
    # predate the currency field (back-compat default applied on load).
    assert portfolios.get_currency(portfolios.default_id()) == 'ILS'
    # Created without an explicit currency → defaults to ILS.
    pid = portfolios.create_portfolio('No currency given')
    assert portfolios.get_currency(pid) == 'ILS'
