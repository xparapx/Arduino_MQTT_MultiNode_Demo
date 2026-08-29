"""SQLite access for sensor_data.db.

- ``connect_ro``  : read-only URI connection used by every reader.
- ``connect_rw``  : writer connection, used only by analyst.py (analysis tables).
- ``ensure_indexes``: (node, ts) indexes on readings / occupancy. DDL, but not a
  schema change; safe while hub.py keeps inserting (short write lock).
- ``bucket_5min`` : the single place where the 5-minute floor rule lives.

Phase 3 adds load_readings / load_occupancy / write here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

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


def bucket_5min(ts: str | datetime) -> str:
    """Floor a UTC timestamp to its 5-minute bucket, returned as ``YYYY-MM-DD HH:MM:SS``.

    Nodes that send ``t`` already sit on the bucket; the six nodes stamped with
    the server receive time do not. Everything downstream keys on this value.
    """
    if isinstance(ts, str):
        ts = datetime.strptime(ts, TS_FMT)
    floored = ts - timedelta(minutes=ts.minute % 5, seconds=ts.second, microseconds=ts.microsecond)
    return floored.strftime(TS_FMT)
