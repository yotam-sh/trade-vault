"""validate_update: unknown keys / bad types / enums rejected on updates."""

import pytest

from app.connection import get_db
from app.settings import init_default_settings, set_setting, get_setting
from app.holdings import add_holding, update_holding, get_holding
from app.schemas import validate_update


def test_validate_update_rejects_unknown_key():
    ok, errors = validate_update('holdings', {'not_a_field': 1})
    assert not ok and any('Unknown field' in e for e in errors)


def test_validate_update_rejects_bad_type():
    ok, errors = validate_update('holdings', {'is_active': 'yes'})  # expects bool
    assert not ok and any('expected bool' in e for e in errors)


def test_validate_update_rejects_bad_enum():
    ok, errors = validate_update('transactions', {'type': 'gift'})
    assert not ok and any('must be one of' in e for e in errors)


def test_validate_update_allows_valid_partial():
    ok, errors = validate_update('holdings', {'is_active': False, 'name_en': 'X'})
    assert ok and errors == []


def test_update_holding_enforces_validation():
    get_db(); init_default_settings()
    hid = add_holding(tase_id=222, tase_symbol='Q', name_he='נייר', security_type='stock',
                      currency='ILS', ticker='Q.TA')
    # Valid update goes through.
    update_holding(hid, name_en='QFoo')
    assert get_holding(hid)['name_en'] == 'QFoo'
    # Unknown field is rejected.
    with pytest.raises(ValueError):
        update_holding(hid, bogus_field=123)


def test_set_setting_still_accepts_arbitrary_values():
    get_db(); init_default_settings()
    set_setting('graph_layout', {'order': ['A'], 'widths': {}})  # dict value is fine
    assert get_setting('graph_layout')['order'] == ['A']
