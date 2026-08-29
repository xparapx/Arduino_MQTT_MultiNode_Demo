"""fixtures/sample.db must carry the awkward parts of the real data:
anonymised node ids, out-of-range sensor rows, nodes that went down, and gaps."""

import json
import re
from pathlib import Path

from aq import db

MAX_MB = 20


def test_fixture_size_and_schema(fixture_path: Path):
    assert fixture_path.stat().st_size < MAX_MB * 1024 * 1024
    conn = db.connect_ro(fixture_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"readings", "occupancy"} <= tables
    conn.close()


def test_nodes_are_anonymised(fixture_path: Path):
    conn = db.connect_ro(fixture_path)
    env = [r[0] for r in conn.execute("SELECT DISTINCT node FROM readings")]
    vis = [r[0] for r in conn.execute("SELECT DISTINCT node FROM occupancy")]
    assert env and all(re.fullmatch(r"env_\d{2}", n) for n in env), env
    assert vis and all(re.fullmatch(r"vis_\d{2}", n) for n in vis), vis
    labels = json.loads((fixture_path.parent / "nodes.json").read_text())
    assert set(env) | set(vis) <= set(labels)
    conn.close()


def test_fixture_contains_abnormal_rows(fixture_path: Path):
    conn = db.connect_ro(fixture_path)
    sql = "SELECT COUNT(*) FROM readings WHERE co2 <= 0 OR sen_temp < -50"
    bad = conn.execute(sql).fetchone()[0]
    assert bad > 0, "expected out-of-range sensor rows (QC test material)"
    conn.close()


def test_fixture_contains_down_node_and_gaps(fixture_path: Path):
    conn = db.connect_ro(fixture_path)
    overall_max = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    per_node = conn.execute("SELECT node, MAX(ts) FROM readings GROUP BY node").fetchall()
    down = [n for n, m in per_node if m < overall_max[:10]]  # last row more than a day before end
    assert down, "expected at least one node that stopped reporting"
    gap = conn.execute(
        """
        SELECT MAX(julianday(ts) - julianday(prev)) * 24 * 60 FROM (
          SELECT ts, LAG(ts) OVER (PARTITION BY node ORDER BY ts) AS prev FROM readings)
        """
    ).fetchone()[0]
    assert gap > 15, "expected a gap > 15 min inside some node's series"
    conn.close()
