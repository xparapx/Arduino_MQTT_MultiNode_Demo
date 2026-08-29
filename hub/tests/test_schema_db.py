"""aq.db.ensure_schema: idempotent on the fixture and on an empty DB; never touches
readings / occupancy; refuses nothing on a read-only connection except writing."""

import sqlite3

import pytest

from aq import db


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


@pytest.mark.parametrize("which", ["fixture_copy", "empty_db"])
def test_ensure_schema_twice(which, request):
    path = request.getfixturevalue(which)
    conn = db.connect_rw(path)
    before_readings = _cols(conn, "readings")
    before_rows = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]

    first = db.ensure_schema(conn)
    second = db.ensure_schema(conn)
    assert set(first) == set(db.ANALYSIS_TABLES)
    assert second == []

    tables = db.existing_tables(conn)
    assert {"analysis", "actuator_state", "readings", "occupancy"} <= tables
    assert "ix_analysis_kind_run" in db.existing_indexes(conn)
    assert _cols(conn, "analysis") == ["id", "run_at", "kind", "scope", "win_start",
                                       "win_end", "model_ver", "payload"]
    assert _cols(conn, "actuator_state") == ["node", "device", "state", "since"]
    # collector tables untouched
    assert _cols(conn, "readings") == before_readings
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == before_rows
    conn.close()


def test_actuator_state_primary_key(empty_db):
    conn = db.connect_rw(empty_db)
    db.ensure_schema(conn)
    ins = "INSERT INTO actuator_state VALUES ('env_01', 'fan', ?, ?)"
    conn.execute(ins, (1, "2026-08-29 03:00:00"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, (0, "2026-08-29 03:10:00"))
    conn.close()


def test_ensure_schema_needs_a_writer(fixture_copy):
    ro = db.connect_ro(fixture_copy)
    with pytest.raises(sqlite3.OperationalError):
        db.ensure_schema(ro)
    ro.close()


def test_ddl_only_creates():
    up = db.ANALYSIS_DDL.upper()
    for forbidden in ("ALTER", "DROP", "DELETE", "UPDATE", "READINGS", "OCCUPANCY"):
        assert forbidden not in up
