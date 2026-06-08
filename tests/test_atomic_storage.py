"""AtomicJSONStorage: round-trip, atomic replace, and no-clobber-on-crash."""

import json
import os

import pytest
from tinydb import TinyDB
from tinydb.middlewares import CachingMiddleware

from app.storage import AtomicJSONStorage


def _open(path):
    return TinyDB(path, storage=CachingMiddleware(AtomicJSONStorage),
                 ensure_ascii=False, indent=2, encoding='utf-8')


def test_round_trip_preserves_unicode(tmp_path):
    path = str(tmp_path / 'db.json')
    db = _open(path)
    db.table('x').insert({'name': 'נקסטקום', 'v': 1})
    db.close()

    on_disk = json.load(open(path, encoding='utf-8'))
    assert on_disk['x']['1']['name'] == 'נקסטקום'
    assert _open(path).table('x').all() == [{'name': 'נקסטקום', 'v': 1}]


def test_write_leaves_no_temp_files(tmp_path):
    path = str(tmp_path / 'db.json')
    db = _open(path)
    db.table('x').insert({'v': 1})
    db.storage.flush()
    leftovers = [f for f in os.listdir(tmp_path) if f.startswith('.db-')]
    assert leftovers == []


def test_failed_write_does_not_corrupt_existing_file(tmp_path, monkeypatch):
    """If os.replace fails mid-write, the original db.json must be intact."""
    path = str(tmp_path / 'db.json')
    db = _open(path)
    db.table('x').insert({'v': 'original'})
    db.storage.flush()
    good = open(path, encoding='utf-8').read()

    # Force the atomic swap to fail on the next write.
    import app.storage as storage_mod

    def boom(src, dst):
        raise OSError('simulated crash during replace')

    monkeypatch.setattr(storage_mod.os, 'replace', boom)
    db.table('x').insert({'v': 'corrupting'})
    with pytest.raises(OSError):
        db.storage.flush()

    # Original file untouched and still valid JSON; no temp leftovers.
    assert open(path, encoding='utf-8').read() == good
    json.loads(good)
    assert [f for f in os.listdir(tmp_path) if f.startswith('.db-')] == []
