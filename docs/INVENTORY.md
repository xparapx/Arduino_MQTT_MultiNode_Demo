# INVENTORY — 보드 실물 (Phase 0, 2026-08-29 01:00 UTC 기준)

모든 값은 `ssh q`(arduino@aqhub)에서 읽기 전용 명령으로 확인한 실물이다. 비밀값은 마스킹.

## 1. 실행 환경
| 항목 | 실물 값 |
|---|---|
| 호스트 | `aqhub` (Tailscale 100.72.130.89), 사용자 `arduino`. 개발 PC에서 `ssh q`로 접속 (`~/.ssh/config` Host q) |
| OS / 커널 | Debian GNU/Linux 13 (trixie), `Linux aqhub 7.0.0-g122c2c22d838 aarch64` |
| 시간대 | `Etc/UTC` (시스템 시각 UTC, NTP 동기) |
| Python | `python3` 3.13.5 (`.python-version` = `3.13`) |
| uv | `~/.local/bin/uv` 존재. **비로그인 셸(`ssh q '...'`) PATH에는 없음** → 절대경로 사용 |
| sqlite3 CLI | **미설치**. DB 조회는 python `sqlite3` 모듈로 대체 |
| sudo | 비밀번호 필요 (NOPASSWD 아님) → 서비스 파일 수정·재시작은 사용자가 실행 |
| 리소스 | RAM 3667 MB (avail ~2.2 GB), swap 1833 MB, `/home/arduino` 18G 중 2.0G 사용, nproc = 4 |

## 2. 작업 디렉터리 `~/multinode_aq` (README의 `multinode_sensor_demo`와 불일치)

> **D-1 적용 후 (2026-08-29 02:50 UTC)**: `~/multinode_aq`는 저장소 루트(main 추적)이고 런타임 디렉터리는 `~/multinode_aq/hub/`다.
> `hub/.venv`(uv sync --frozen로 재생성), `hub/sensor_data.db`, `hub/secrets.env`(0600)는 untracked·gitignore.
> 평면 시절 파일(`hub.py dashboard.py nodes.json pyproject.toml uv.lock .python-version *.bak *.save`, 옛 `.venv`→`venv_old`, uv 기본 `.gitignore.uv`)은 `~/multinode_aq/_phase0_backup/`에 보관(gitignore).
> 두 유닛은 `WorkingDirectory=/home/arduino/multinode_aq/hub`, hub 유닛은 `EnvironmentFile=…/hub/secrets.env`. 아래는 전환 **이전** 실물 기록.

```
dashboard.py (51,439 B, Jul 27)   hub.py (4,830 B, Jul 9)   nodes.json (Aug 8)
pyproject.toml  uv.lock  .python-version  .gitignore(uv 기본)  .venv/  sensor_data.db (15 MB)
백업: dashboard.py.bak  dashboard.py.save  dashboard_v2.py.bak  hub.py.bak  nodes.json.save
.git/  <- uv init이 만든 빈 저장소 (브랜치 master, 커밋 0, remote 없음)
```
- **`hub_cloud.py` 없음** — 보드의 `hub.py` 자체가 HiveMQ Cloud(TLS 8883) 버전이다.
- **`.streamlit/config.toml` 없음** (`~/.streamlit/`에는 `machine_id_v4`만). 다크 테마는 dashboard.py 내부 CSS/plotly 템플릿으로 구현.
- `systemd/` 디렉터리 없음 — 유닛은 `/etc/systemd/system/`에만 존재 (저장소 `hub/systemd/`에 복사함).
- 레이아웃: 보드는 **평면**(`~/multinode_aq/hub.py`), 저장소는 `hub/hub.py`. 보드를 git 트리로 전환할 때 서비스 경로 조정 필요 → DRIFT.md D-1.

### pyproject.toml (실물)
```
name = "multinode-aq"  requires-python = ">=3.13"
numpy>=2.5.1  paho-mqtt>=2.1.0  pandas>=3.0.3  plotly>=6.8.0  scikit-learn>=1.9.0
streamlit>=1.58.0  streamlit-autorefresh>=1.0.1
```
.venv 설치 버전: numpy 2.5.1, paho-mqtt 2.1.0, pandas 3.0.3, plotly 6.8.0, scikit-learn 1.9.0, streamlit 1.58.0, streamlit-autorefresh 1.0.1. (python-dotenv 없음)

## 3. 서비스 (정본 이름)
| 유닛 | 상태 | ExecStart |
|---|---|---|
| `multinode_aq_hub.service` | active, enabled, NRestarts=5, 기동 2026-08-28 06:52 UTC | `/home/arduino/multinode_aq/.venv/bin/python /home/arduino/multinode_aq/hub.py` |
| `multinode_aq_dashboard.service` | active, enabled | `.../.venv/bin/streamlit run /home/arduino/multinode_aq/dashboard.py --server.address 0.0.0.0 --server.port 8501 --server.headless true` |

- 둘 다 `WorkingDirectory=/home/arduino/multinode_aq`, `User=arduino`, `Restart=always`.
- dashboard 유닛의 `After=... multinode_aq.service`는 **존재하지 않는 유닛**을 가리킴 (not-found; 무해하나 오타).
- `curl localhost:8501` → 200. dashboard 로그에 streamlit `use_container_width` deprecation 경고가 반복 출력됨(오류 아님).

## 4. MQTT (정본 값, hub.py 소스)
| 항목 | 값 |
|---|---|
| 브로커 | HiveMQ Cloud `********.s1.eu.hivemq.cloud`, 포트 8883 TLS, 계정 `****` / `****` (→ `hub/secrets.env`로 분리) |
| TOPIC | `multinode_aq/+/env` (환경 노드) |
| TOPIC_OCC | `multinode_aq/+/occ` (비전 노드) |
| DB | `sensor_data.db` (작업 디렉터리 기준 상대경로) |

README의 `multinode_sensor_demo/+/env` 와 불일치 → **보드 값이 정본**.

## 5. DB `sensor_data.db`
- `PRAGMA journal_mode` = **delete** (WAL 아님 — Phase 6 [ASK] 대상)
- 스키마: `readings`(id, ts, node, pm1p0, pm2p5, pm4p0, pm10p0, sen_temp, sen_hum, voc, nox, co2, scd_temp, scd_hum, n), `occupancy`(id, ts, node, occ, occ_med, occ_max, occ_last, cents, w, n). 인덱스 없음.
- `ts` 형식: `YYYY-MM-DD HH:MM:SS` UTC 문자열. 노드가 `t`를 보내면 5분 정각 버킷(`...:55:00`), 안 보내면 서버 수신 시각(초 단위, 예 `00:58:24`) — **두 형식이 섞여 있음** (node_4C22A7/E04537은 버킷, 나머지는 수신 시각).

### readings — 노드별 (총 114,375행)
| node | rows | min ts | max ts |
|---|---|---|---|
| node_3093F0 | 14,709 | 2026-07-07 22:52:39 | 2026-08-29 01:01:27 |
| node_4C22A7 | 14,740 | 2026-07-07 22:41:21 | 2026-08-29 00:55:00 |
| node_5040F0 | 14,507 | 2026-07-07 22:58:50 | 2026-08-29 00:59:00 |
| node_8C8B35 | 14,712 | 2026-07-07 22:44:20 | 2026-08-29 00:58:24 |
| node_B80DC8 | 14,108 | 2026-07-07 04:50:00 | 2026-08-27 00:30:00 (**2일 전 중단**) |
| node_D0C12C | 12,153 | 2026-07-07 22:35:00 | 2026-08-28 04:21:43 (**~21h 전 중단**) |
| node_E04537 | 14,738 | 2026-07-07 22:45:00 | 2026-08-29 00:55:00 |
| node_E84DF0 | 14,708 | 2026-07-07 22:48:00 | 2026-08-29 01:00:25 |

### occupancy — 노드별 (총 16,287행)
| node | rows | min ts | max ts |
|---|---|---|---|
| node_2A8454 | 4,445 | 2026-07-09 15:53:27 | 2026-08-21 22:04:11 |
| node_44F2FB | 4,120 | 2026-07-15 02:41:43 | 2026-08-28 21:59:08 |
| node_E1B3AA | 721 | 2026-07-20 23:53:20 | 2026-08-09 22:04:14 |
| node_E29568 | 2,720 | 2026-07-20 23:44:25 | 2026-08-14 22:00:29 |
| node_E647F1 | 4,281 | 2026-08-08 07:02:02 | 2026-08-23 23:33:38 |

### 데이터 품질 관찰 (QC 설계 참고)
- `node_E04537` 2026-08-29 00:55 행: pm 1765/3240, sen_temp −98.24, sen_hum 169, co2 0.0 → 센서 이상값이 그대로 저장됨. §2 범위 규칙(CO₂ 350~5000 → NaN)이 걸러야 한다.
- 두 환경 노드(B80DC8, D0C12C)가 현재 다운 — 픽스처의 "노드다운 구간"으로 쓸 수 있음.

## 6. nodes.json (실물)
16개 항목: 환경 노드 8개(`node_D0C12C` … `node_B80DC8`) → CLASS_01~08, 비전 노드 8개(`node_44F2FB` … `node_2A8454`) → 같은 라벨 CLASS_01~08 (환경↔비전 쌍은 **같은 라벨**로 연결). 저장소의 3항목 한글 샘플과 다름.

## 7. dashboard.py (실물, 1,081줄)
- `DB = "sensor_data.db"`, `NODES_PATH = "nodes.json"` (상대경로), `st_autorefresh(interval=REFRESH_MS)`
- 섹션: ① 노드 카드 그리드(게이지) ② 전체 통계 — 박스플롯 | **상관 히트맵**, CO₂+VOC 스택 | **CO₂-VOC 레짐 산점도(RobustScaling)** ③ 시계열(6변수) + 노드별 레짐 산점도 | 비전 crosshair 맵 ④ 최근 5행 ⑤ CSV 내보내기
- ②의 히트맵·레짐 산점도가 Phase 5에서 제거 대상. 산점도는 데이터 의존 스케일러(RobustScaling)를 쓰고 있어 §2 불변 조건과 충돌(대시보드 표시용이므로 Phase 5에서 정리).
