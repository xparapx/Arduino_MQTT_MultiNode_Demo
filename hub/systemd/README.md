# systemd units (board: `/etc/systemd/system/`)

| unit | role | started by |
|---|---|---|
| `multinode_aq_hub.service` | MQTT → SQLite collector (`hub.py`) | boot, `Restart=always` |
| `multinode_aq_web.service` | admin web app :8501 (`webapp.py`) | boot, `Restart=always` |
| `multinode_aq_web_public.service` | public web app :8502 (`webapp.py --public`) | boot, `Restart=always` |
| `multinode_aq_analyst_hourly.timer` → `.service` | `analyst.py run --mode hourly` | every hour at :05 UTC |
| `multinode_aq_analyst_daily.timer` → `.service` | `analyst.py run --mode daily` | 06:00 UTC daily |
| `multinode_aq_analyst_weekly.timer` → `.service` | `analyst.py run --mode weekly` | 1st/3rd Sunday 06:30 UTC (biweekly, user decision 2026-09-05) |

The analyst units are `Type=oneshot`, `TimeoutStartSec=300`, `Nice=10`, no
`EnvironmentFile` (no broker credentials needed). They read `readings` /
`occupancy` read-only and write only `analysis` / `actuator_state`
(`sensor_data.db` is in WAL mode, so hub.py inserts are never blocked).
hub / web units are not touched by Phase 6. (The old Streamlit
`multinode_aq_dashboard.service` was retired 2026-09-06 — unit archived in
`legacy/streamlit/`; on the board: `sudo systemctl disable --now
multinode_aq_dashboard` + remove the unit file, see legacy/README.md.)

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

## 설치 방식 주의 (2026-10-07)

유닛은 반드시 `/etc/systemd/system/`에 **복사**해서 설치한다(`sudo cp hub/systemd/<unit> /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now <unit>`).
`/home/arduino/...`로 가는 **심링크로 설치하면 안 된다** — 이 보드는 `/home`이 별도 파티션(`/dev/mmcblk0p69`)이라 부팅 시 systemd가 유닛을 읽는 시점에 링크 대상이 없어
`Failed to open ... No such file or directory`로 유닛이 사라진다(plugwatch가 9/25~10/7 정지한 원인). `multinode_aq_plugwatch.service`는 10/7 복사 설치로 교체함.
