"""validate_backup now rejects structurally-valid-but-garbage backups."""

import json

from app.db_backup import validate_backup


def _write(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def test_valid_empty_backup_ok(tmp_path):
    p = tmp_path / 'b.json'
    _write(str(p), {'holdings': {}, 'transactions': {}, 'settings': {}})
    ok, _msg = validate_backup(str(p))
    assert ok


def test_missing_required_table_rejected(tmp_path):
    p = tmp_path / 'b.json'
    _write(str(p), {'holdings': {}})
    ok, msg = validate_backup(str(p))
    assert not ok and 'missing tables' in msg


def test_invalid_record_rejected(tmp_path):
    p = tmp_path / 'b.json'
    _write(str(p), {
        'holdings': {'1': {'tase_id': 'not-an-int'}},  # wrong type + missing required
        'transactions': {},
        'settings': {},
    })
    ok, msg = validate_backup(str(p))
    assert not ok and 'invalid record' in msg.lower()


def test_bad_json_rejected(tmp_path):
    p = tmp_path / 'b.json'
    with open(p, 'w', encoding='utf-8') as f:
        f.write('{not json')
    ok, msg = validate_backup(str(p))
    assert not ok and 'Invalid JSON' in msg
