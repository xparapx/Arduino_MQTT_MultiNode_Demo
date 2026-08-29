# DRIFT — 문서/저장소 vs 보드 실물 (Phase 0)

원칙: 보드 실물이 정답. 아래는 저장소(main @ 1b2bde0) 및 README/manual 기재와 실물의 차이.

## 코드 파일 (저장소 `hub/` ← 보드 `~/multinode_aq/`)
| 파일 | 방향 | 요약 |
|---|---|---|
| `hub/hub.py` | 보드 → 저장소 **교체** | 저장소본은 로컬 mosquitto(1883, 토픽 `multinode_sensor_demo/+/env`, readings만). 보드본은 HiveMQ TLS 8883, 토픽 `multinode_aq/+/env` + `multinode_aq/+/occ`, `occupancy` 테이블·`store_occ()` 추가 (132줄 vs 91줄). 브로커 계정은 `os.environ`(MQTT_BROKER/PORT/USERNAME/PASSWORD)으로 분리 — 변경 줄은 import 1줄 + 상수 4줄뿐 |
| `hub/hub_cloud.py` | 유지 (참고용) | 보드에 없음. 보드 hub.py의 전신(자리표시 계정, 토픽 `multinode_sensor_demo`, occupancy 없음). 문서가 참조하므로 Phase 0에서는 삭제하지 않음 → [ASK] 정리 시점 |
| `hub/en/hub.py`, `hub/en/dashboard.py` | 유지 (참고용) | 보드에 없음. 저장소 옛 버전과 동일 내용의 "영문판". 위와 동일 처리 |
| `hub/dashboard.py` | 보드 → 저장소 **교체** | 803줄 → 1,081줄. 6변수 시계열, 노드별 레짐 산점도, 비전 occupancy crosshair 맵, 환경↔비전 라벨 페어링 추가 |
| `hub/nodes.json` | 보드 → 저장소 **교체** | 3항목 한글 샘플 → 16항목(CLASS_01~08 × 환경/비전) |
| `hub/systemd/*.service` | 이름 변경 | `multinode_sensor_demo_{hub,dashboard}.service` 삭제 → `multinode_aq_{hub,dashboard}.service` (경로 `/home/arduino/multinode_aq`). dashboard 유닛 `After=multinode_aq.service`는 존재하지 않는 유닛 참조(실물 그대로 둠) |
| `hub/pyproject.toml`, `hub/uv.lock`, `hub/.python-version` | 신규 | 저장소에 없던 파일. 의존성에 numpy·scikit-learn이 이미 포함 |
| `hub/secrets.env.example` | 신규 | 실제 값은 보드 `hub/secrets.env`(gitignore) |
| `.gitignore` | 추가 | `sensor_data.db`, `*.db-journal/-wal/-shm`, `models/*.joblib`, `backup_*.csv`, `secrets.env`, `*.bak`, `*.save` |

## 문서 기재 vs 실물
| 항목 | README / 플랜 사전지식 | 실물 |
|---|---|---|
| 작업 디렉터리 | `~/multinode_sensor_demo` | `~/multinode_aq` |
| 토픽 | `multinode_sensor_demo/+/env` | `multinode_aq/+/env`, `multinode_aq/+/occ` |
| 서비스명 | `multinode_sensor_demo_*` | `multinode_aq_hub`, `multinode_aq_dashboard` |
| 수집 스크립트 | `hub.py`(로컬) 또는 `hub_cloud.py`(클라우드) 택일 | `hub.py` 하나이며 클라우드(HiveMQ) 버전 |
| 대시보드 테마 | `.streamlit/config.toml` 다크 테마 | 파일 없음. CSS/plotly 템플릿을 dashboard.py에 내장 |
| 의존성 | paho-mqtt pandas plotly streamlit streamlit-autorefresh | + numpy, scikit-learn |
| DB journal | (플랜 §9.2에서 WAL 확인 예정) | `delete` 모드 |
| ts 형식 | 5분 버킷 정각 정렬 | 노드가 `t`를 보내는 2노드만 정각 버킷, 나머지 6노드는 수신 시각(초 단위) — 분석 시 5분 버킷 리샘플 필요 |
| sqlite3 CLI | 플랜 검증 명령이 `sqlite3` 사용 | 미설치 → python `sqlite3` 모듈로 대체 |
| uv | `uv` 명령 | 비로그인 셸 PATH 밖 (`~/.local/bin/uv`) |
| 보드 git | 없음 가정 | `uv init`이 만든 빈 `.git`(커밋 0, remote 없음) — `git init` 재실행 무해 |
| sudo | (플랜은 서비스 재시작을 Claude가 수행 가정) | 비밀번호 필요 → 사용자가 실행 |
| `docs/dashboard_mockup.html` (CLAUDE.md) | `docs/` | 실제 위치 `plan/dashboard_mockup.html` |

## D-1 [ASK] 보드 레이아웃 (Phase 0 §3.3.6 진행 전 결정 필요)
보드 `~/multinode_aq`는 평면(`hub.py`가 루트)이고 저장소는 `hub/` 하위 구조다. `~/multinode_aq`를 저장소 루트로 전환하면 코드가 `~/multinode_aq/hub/hub.py`에 놓여 현행 서비스 `ExecStart`·상대경로(`sensor_data.db`, `nodes.json`)와 어긋난다. 선택지:

- **(A) 권장** `~/multinode_aq/hub/`를 uv 프로젝트·런타임 디렉터리로: 보드에서 `.venv`, `sensor_data.db`, `pyproject.toml`, `uv.lock`, `.python-version`을 `hub/`로 `mv`, 두 유닛의 `WorkingDirectory`/`ExecStart`를 `/home/arduino/multinode_aq/hub/...`로 수정 + `EnvironmentFile=/home/arduino/multinode_aq/hub/secrets.env`. 저장소 `hub/` == 보드 `hub/` 가 그대로 성립하고 Phase 1 `hub/deploy.sh`, Phase 6 유닛 파일과 일관됨. 비용: hub 서비스 정지 → 이동 → 기동 (수 초 수집 공백).
- (B) 저장소를 평면으로 재구성(`hub/` 내용을 루트로): 플랜 §4.1 구조와 충돌.
- (C) 보드에 심링크(`~/multinode_aq/hub.py → hub/hub.py` 등): untracked 항목 증가, DB 경로 혼란.
