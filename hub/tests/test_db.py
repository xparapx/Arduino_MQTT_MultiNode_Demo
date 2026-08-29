"""aq.db: read-only connections, idempotent indexes, 5-minute bucket floor."""

import sqlite3

import pytest

from aq import db


def test_connect_ro_rejects_writes(fixture_path):
    conn = db.connect_ro(fixture_path)
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] > 0
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO readings(node) VALUES('x')")
    conn.close()


def test_ensure_indexes_idempotent_on_fixture(fixture_copy):
    conn = db.connect_rw(fixture_copy)
    first = db.ensure_indexes(conn)
    second = db.ensure_indexes(conn)
    assert set(first) == set(db.INDEXES)
    assert second == []
    assert set(db.INDEXES) <= db.existing_indexes(conn)
    conn.close()


def test_ensure_indexes_on_empty_db(empty_db):
    conn = db.connect_rw(empty_db)
    assert set(db.ensure_indexes(conn)) == set(db.INDEXES)
    assert db.ensure_indexes(conn) == []
    conn.close()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-08-29 00:58:24", "2026-08-29 00:55:00"),
        ("2026-08-29 00:55:00", "2026-08-29 00:55:00"),
        ("2026-08-29 00:59:59", "2026-08-29 00:55:00"),
        ("2026-08-29 01:00:00", "2026-08-29 01:00:00"),
        ("2026-08-28 23:57:01", "2026-08-28 23:55:00"),
    ],
)
def test_bucket_5min(raw, expected):
    assert db.bucket_5min(raw) == expected
