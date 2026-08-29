"""Shared pytest fixtures. Tests never touch the real sensor_data.db."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DB = HUB_DIR / "fixtures" / "sample.db"

if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))


@pytest.fixture(scope="session")
def fixture_path() -> Path:
    if not FIXTURE_DB.exists():
        pytest.skip("fixtures/sample.db missing - run tests/make_fixture.py on the board")
    return FIXTURE_DB


@pytest.fixture
def fixture_copy(fixture_path: Path, tmp_path: Path) -> Path:
    """Writable copy of the fixture for tests that need to create indexes / tables."""
    dst = tmp_path / "sample.db"
    shutil.copy(fixture_path, dst)
    return dst


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Empty DB with the real readings / occupancy schema (as created by hub.py)."""
    import sqlite3

    path = tmp_path / "empty.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE readings(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, node TEXT,
          pm1p0 REAL, pm2p5 REAL, pm4p0 REAL, pm10p0 REAL, sen_temp REAL, sen_hum REAL,
          voc REAL, nox REAL, co2 REAL, scd_temp REAL, scd_hum REAL, n INTEGER);
        CREATE TABLE occupancy(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, node TEXT,
          occ REAL, occ_med INTEGER, occ_max INTEGER, occ_last INTEGER, cents TEXT,
          w INTEGER, n INTEGER);
        """
    )
    conn.commit()
    conn.close()
    return path
