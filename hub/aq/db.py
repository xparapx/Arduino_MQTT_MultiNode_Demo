"""SQLite access for sensor_data.db.

- ``connect_ro``  : read-only URI connection used by every reader.
- ``connect_rw``  : writer connection, used only by analyst.py (analysis tables).
- ``ensure_indexes``: (node, ts) indexes on readings / occupancy. DDL, but not a
  schema change; safe while hub.py keeps inserting (short write lock).
- ``bucket_5min`` : the single place where the 5-minute floor rule lives.
- ``ensure_schema``: analysis / actuator_state tables (Phase 2). Only creates.

Phase 3 adds load_readings / load_occupancy / write here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

HUB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = HUB_DIR / "sensor_data.db"
TS_FMT = "%Y-%m-%d %H:%M:%S"
BUCKET = timedelta(minutes=5)

INDEXES: dict[str, str] = {
    "ix_readings_node_ts": ("CREATE INDEX IF NOT EXISTS ix_readings_node_ts ON readings(node, ts)"),
    "ix_occupancy_node_ts": (
        "CREATE INDEX IF NOT EXISTS ix_occupancy_node_ts ON occupancy(node, ts)"
    ),
}


def _uri(path: str | Path, mode: str) -> str:
    return f"{Path(path).resolve().as_uri()}?mode={mode}"


def connect_ro(path: str | Path = DEFAULT_DB, timeout: float = 5.0) -> sqlite3.Connection:
    """Read-only connection (``?mode=ro``). Writes raise sqlite3.OperationalError."""
    conn = sqlite3.connect(_uri(path, "ro"), uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    return conn


def connect_rw(path: str | Path = DEFAULT_DB, timeout: float = 5.0) -> sqlite3.Connection:
    """Writer connection for analyst.py. busy_timeout keeps hub.py inserts unharmed."""
    conn = sqlite3.connect(_uri(path, "rw"), uri=True, timeout=timeout)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def existing_indexes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    return {r[0] for r in rows}


def ensure_indexes(conn: sqlite3.Connection) -> list[str]:
    """Create missing (node, ts) indexes. Idempotent. Returns the names created."""
    have = existing_indexes(conn)
    created: list[str] = []
    for name, ddl in INDEXES.items():
        if name not in have:
            conn.execute(ddl)
            created.append(name)
    conn.commit()
    return created


# ---- analysis tables (plan section 6.1). Only analyst.py writes them. -----------
# DDL only creates. The collector tables are never altered, dropped or emptied
# from this package; CI greps hub/aq for those statements.
ANALYSIS_DDL = """
CREATE TABLE IF NOT EXISTS analysis (
  id INTEGER PRIMARY KEY, run_at TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT,
  win_start TEXT, win_end TEXT, model_ver TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_analysis_kind_run ON analysis(kind, run_at);
CREATE TABLE IF NOT EXISTS actuator_state (
  node TEXT, device TEXT, state INTEGER, since TEXT, PRIMARY KEY(node, device));
"""
ANALYSIS_TABLES = ("analysis", "actuator_state")


def existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def ensure_schema(conn: sqlite3.Connection) -> list[str]:
    """Create analysis / actuator_state (+ index) if missing. Idempotent; safe to
    run on every analyst start and on an empty DB. Returns the tables created."""
    before = existing_tables(conn)
    conn.executescript(ANALYSIS_DDL)
    conn.commit()
    return [t for t in ANALYSIS_TABLES if t not in before]


def bucket_5min(ts: str | datetime) -> str:
    """Floor a UTC timestamp to its 5-minute bucket, returned as ``YYYY-MM-DD HH:MM:SS``.

    Nodes that send ``t`` already sit on the bucket; the six nodes stamped with
    the server receive time do not. Everything downstream keys on this value.
    """
    if isinstance(ts, str):
        ts = datetime.strptime(ts, TS_FMT)
    floored = ts - timedelta(minutes=ts.minute % 5, seconds=ts.second, microseconds=ts.microsecond)
    return floored.strftime(TS_FMT)


# ---- Phase 3: loaders (read-only) and the analyst's writers -------------------

def floor_buckets(ts: pd.Series) -> pd.Series:
    """Vectorised bucket_5min for a Series of 'YYYY-MM-DD HH:MM:SS' strings."""
    import pandas as pd

    return pd.to_datetime(ts, format=TS_FMT).dt.floor(f"{int(BUCKET.total_seconds() // 60)}min") \
        .dt.strftime(TS_FMT)


def load_readings(conn: sqlite3.Connection, start: str, end: str) -> pd.DataFrame:
    """readings rows with ``start <= ts < end`` (UTC strings), one row per
    (node, bucket): ts floored to 5 min, the LAST received row of a bucket wins.
    Columns: node, bucket, ts, co2, voc, pm2p5, temp, hum, n."""
    import pandas as pd

    sql = ("SELECT id, ts, node, co2, voc, pm2p5, scd_temp AS temp, scd_hum AS hum, n "
           "FROM readings WHERE ts >= ? AND ts < ? ORDER BY id")
    df = pd.read_sql_query(sql, conn, params=(start, end))
    if df.empty:
        return pd.DataFrame(columns=["node", "bucket", "ts", "co2", "voc", "pm2p5",
                                     "temp", "hum", "n"])
    df["bucket"] = floor_buckets(df["ts"])
    df = df.drop_duplicates(["node", "bucket"], keep="last")
    df = df.sort_values(["node", "bucket"]).reset_index(drop=True)
    return df[["node", "bucket", "ts", "co2", "voc", "pm2p5", "temp", "hum", "n"]]


def load_occupancy(conn: sqlite3.Connection, start: str, end: str) -> pd.DataFrame:
    """occupancy rows with ``start <= ts < end``, one row per (node, bucket).
    Columns: node, bucket, occ, occ_med, occ_max, n."""
    import pandas as pd

    cols = ["node", "bucket", "occ", "occ_med", "occ_max", "n"]
    if "occupancy" not in existing_tables(conn):
        return pd.DataFrame(columns=cols)
    sql = ("SELECT id, ts, node, occ, occ_med, occ_max, n FROM occupancy "
           "WHERE ts >= ? AND ts < ? ORDER BY id")
    df = pd.read_sql_query(sql, conn, params=(start, end))
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["bucket"] = floor_buckets(df["ts"])
    df = df.drop_duplicates(["node", "bucket"], keep="last")
    return df.sort_values(["node", "bucket"]).reset_index(drop=True)[cols]


def last_occupancy_bucket(conn: sqlite3.Connection) -> dict[str, str]:
    """{node: last 5-minute bucket} over the whole occupancy table (all time,
    not just an analysis window) so a vision node that stopped reporting still
    has a "last seen" the dashboard can show as stopped. Read-only; served by
    ix_occupancy_node_ts."""
    if "occupancy" not in existing_tables(conn):
        return {}
    rows = conn.execute("SELECT node, MAX(ts) FROM occupancy GROUP BY node").fetchall()
    if not rows:
        return {}
    import pandas as pd

    buckets = floor_buckets(pd.Series([ts for _, ts in rows]))
    return {node: b for (node, _), b in zip(rows, buckets, strict=True)}


ANALYSIS_COLS = ("run_at", "kind", "scope", "win_start", "win_end", "model_ver", "payload")


def write_analysis(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert analysis rows (dicts with ANALYSIS_COLS; payload as dict). Every
    payload passes aq.schemas.validate first, so a bad row aborts the batch."""
    import json

    from aq import schemas

    prepared = []
    for r in rows:
        schemas.validate(r["kind"], r["payload"])
        prepared.append(tuple(json.dumps(r[c], ensure_ascii=False) if c == "payload" else r.get(c)
                              for c in ANALYSIS_COLS))
    cols, marks = ",".join(ANALYSIS_COLS), ",".join("?" * len(ANALYSIS_COLS))
    conn.executemany(f"INSERT INTO analysis({cols}) VALUES({marks})", prepared)
    conn.commit()
    return len(prepared)


def read_analysis(conn: sqlite3.Connection, kind: str, limit: int = 20) -> list[dict]:
    import json

    if "analysis" not in existing_tables(conn):
        return []
    cur = conn.execute("SELECT id, run_at, kind, scope, win_start, win_end, model_ver, payload "
                       "FROM analysis WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))
    out = []
    for row in cur.fetchall():
        d = dict(zip(["id", "run_at", "kind", "scope", "win_start", "win_end", "model_ver",
                      "payload"], row, strict=True))
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def read_actuator_state(conn: sqlite3.Connection) -> dict[str, dict[str, dict]]:
    """{node: {device: {"state": int, "since": str}}} -- empty when the table is absent."""
    if "actuator_state" not in existing_tables(conn):
        return {}
    out: dict[str, dict[str, dict]] = {}
    for node, device, state, since in conn.execute(
            "SELECT node, device, state, since FROM actuator_state"):
        out.setdefault(node, {})[device] = {"state": int(state), "since": since}
    return out


def write_actuator_state(conn: sqlite3.Connection, node: str, device: str,
                         state: int, since: str) -> None:
    conn.execute("INSERT OR REPLACE INTO actuator_state(node, device, state, since) "
                 "VALUES(?,?,?,?)", (node, device, int(state), since))
    conn.commit()
