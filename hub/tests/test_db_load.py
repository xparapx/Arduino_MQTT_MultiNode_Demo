"""aq.db loaders: receive-time rows land on the 5-min bucket grid, the last row of a
bucket wins, and the analyst writers round-trip through schemas."""

import pytest

from aq import db, schemas


def test_load_readings_buckets_are_on_grid(fixture_path):
    conn = db.connect_ro(fixture_path)
    hi = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    df = db.load_readings(conn, "2000-01-01 00:00:00", hi + "z")   # 'z' > any digit
    conn.close()
    assert not df.empty
    minutes = df["bucket"].str[14:16].astype(int)
    assert (minutes % 5 == 0).all() and (df["bucket"].str[17:19] == "00").all()
    # receive-time nodes (seconds != 00) exist in the fixture and were floored, not rounded
    off_grid = df[df["ts"].str[17:19] != "00"]
    assert len(off_grid) > 0
    assert (off_grid["ts"] >= off_grid["bucket"]).all()
    assert not df.duplicated(["node", "bucket"]).any()
    assert list(df.columns) == ["node", "bucket", "ts", "co2", "voc", "pm2p5", "temp", "hum", "n"]


def test_last_row_of_bucket_wins(empty_db):
    conn = db.connect_rw(empty_db)
    conn.executemany("INSERT INTO readings(ts, node, co2, voc) VALUES(?,?,?,?)", [
        ("2026-08-29 00:01:10", "env_01", 500, 50),
        ("2026-08-29 00:04:59", "env_01", 600, 60),     # same bucket 00:00 -> this one wins
        ("2026-08-29 00:05:00", "env_01", 700, 70),
        ("2026-08-29 00:02:00", "env_02", 800, 80),
    ])
    conn.commit()
    df = db.load_readings(conn, "2026-08-29 00:00:00", "2026-08-30 00:00:00")
    conn.close()
    got = {(r.node, r.bucket): r.co2 for r in df.itertuples()}
    assert got == {("env_01", "2026-08-29 00:00:00"): 600, ("env_01", "2026-08-29 00:05:00"): 700,
                   ("env_02", "2026-08-29 00:00:00"): 800}


def test_load_occupancy_empty_and_grid(fixture_path, empty_db):
    conn = db.connect_ro(fixture_path)
    occ = db.load_occupancy(conn, "2000-01-01 00:00:00", "2100-01-01 00:00:00")
    conn.close()
    assert not occ.empty and (occ["bucket"].str[17:19] == "00").all()
    assert list(occ.columns) == ["node", "bucket", "occ", "occ_med", "occ_max", "n"]
    conn = db.connect_rw(empty_db)
    assert db.load_occupancy(conn, "2000-01-01 00:00:00", "2100-01-01 00:00:00").empty
    conn.close()


def test_write_and_read_analysis_and_actuator_state(empty_db):
    conn = db.connect_rw(empty_db)
    db.ensure_schema(conn)
    rows = [{"run_at": "2026-08-29 03:00:00", "kind": "summary", "scope": "all",
             "win_start": "2026-08-28 03:00:00", "win_end": "2026-08-29 03:00:00",
             "model_ver": "adhoc", "payload": {"lines": ["ok"]}}]
    assert db.write_analysis(conn, rows) == 1
    got = db.read_analysis(conn, "summary")
    assert got[0]["payload"] == {"lines": ["ok"]} and got[0]["scope"] == "all"
    with pytest.raises(schemas.SchemaError):
        db.write_analysis(conn, [dict(rows[0], payload={"nope": 1})])
    assert db.read_actuator_state(conn) == {}
    db.write_actuator_state(conn, "env_01", "fan", 1, "2026-08-29 03:00:00")
    db.write_actuator_state(conn, "env_01", "fan", 0, "2026-08-29 03:20:00")   # replace
    assert db.read_actuator_state(conn) == {"env_01": {"fan": {"state": 0,
                                                              "since": "2026-08-29 03:20:00"}}}
    conn.close()
