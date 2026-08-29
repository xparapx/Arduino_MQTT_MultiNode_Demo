# systemd units (board: `/etc/systemd/system/`)

| unit | role | started by |
|---|---|---|
| `multinode_aq_hub.service` | MQTT → SQLite collector (`hub.py`) | boot, `Restart=always` |
| `multinode_aq_dashboard.service` | Streamlit dashboard :8501 | boot, `Restart=always` |
| `multinode_aq_analyst_hourly.timer` → `.service` | `analyst.py run --mode hourly` | every hour at :05 UTC |
| `multinode_aq_analyst_daily.timer` → `.service` | `analyst.py run --mode daily` | 06:00 UTC daily |
| `multinode_aq_analyst_weekly.timer` → `.service` | `analyst.py run --mode weekly` | Sunday 06:30 UTC |

The analyst units are `Type=oneshot`, `TimeoutStartSec=300`, `Nice=10`, no
`EnvironmentFile` (no broker credentials needed). They read `readings` /
`occupancy` read-only and write only `analysis` / `actuator_state`
(`sensor_data.db` is in WAL mode, so hub.py inserts are never blocked).
hub / dashboard units are not touched by Phase 6.

## Install (Phase 6, run as the user — needs sudo)

```bash
cd ~/multinode_aq/hub/systemd
sudo cp multinode_aq_analyst_{hourly,daily,weekly}.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now multinode_aq_analyst_hourly.timer \
                            multinode_aq_analyst_daily.timer \
                            multinode_aq_analyst_weekly.timer
# first fill of the analysis table, once, by hand:
sudo systemctl start multinode_aq_analyst_daily.service
sudo systemctl start multinode_aq_analyst_hourly.service
```

## Check (no sudo)

```bash
systemctl list-timers 'multinode_aq*' --no-pager
systemctl status multinode_aq_analyst_daily.service --no-pager | tail -5
journalctl -u multinode_aq_analyst_hourly --since -2h --no-pager | tail -20
cd ~/multinode_aq/hub && .venv/bin/python -c "import sqlite3;print(sqlite3.connect('file:sensor_data.db?mode=ro',uri=True).execute('SELECT kind,COUNT(*),MAX(run_at) FROM analysis GROUP BY kind').fetchall())"
```

## Rollback

```bash
sudo systemctl disable --now multinode_aq_analyst_{hourly,daily,weekly}.timer
```
The `analysis` table can be emptied without touching collection or display
(`DELETE FROM analysis`), see plan appendix A.
