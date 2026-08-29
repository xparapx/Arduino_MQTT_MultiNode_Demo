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

**결정 (플랜 v2 §3.1): (A) 채택.** 저장소 `hub/systemd/*.service`는 `hub/` 경로 + `EnvironmentFile=` + dashboard `After=multinode_aq_hub.service`(오타 수정)로 갱신. 보드 평면 파일은 `_phase0_backup/`(gitignore)로 이동. 보드의 uv 기본 `.gitignore`도 저장소 `.gitignore`와 충돌하므로 같은 백업 폴더로 이동.

## 플랜 v2 반영 후 추가 드리프트
| 항목 | 기재 | 실물 |
|---|---|---|
| 플랜 위치 | CLAUDE.md·플랜 §4.1: `plan/CLAUDE_CODE_PLAN.md`, `plan/dashboard_mockup.html` | 실제 파일은 `docs/plan/CLAUDE_CODE_PLAN.md`, `docs/plan/dashboard_mockup_v2.html` (2026-08-29 이동) |
| 저장소 `.gitignore` `*.db` | (기존 규칙) | `fixtures/sample.db`(Phase 1)를 커밋하려면 예외 규칙 `!fixtures/sample.db` 필요 |
| 저장소 히스토리 | 비밀값 없음 | `docs/manual.html` 2826·3205행(펌웨어 예제)에 실제 HiveMQ 클러스터 **호스트명**이 main 히스토리에 있음(계정·비밀번호는 없음). 처리 시점 [ASK] |

## Phase 1 — 플랜 §4와 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| CI 트리거 | PR마다 | PR + **모든 브랜치 push** | `gh` CLI가 없어 PR을 Claude Code가 열 수 없음 → push만으로 hub.py 가드 실패를 확인 가능하게 함. hub.py 가드는 `origin/main...HEAD` 비교라 main push에서는 자동 통과 |
| `.claude/settings.json` | Claude Code가 작성 | **사용자가 작성** | 자동 모드 분류기가 권한 파일 쓰기(직접·`update-config` 스킬 모두)를 차단. 내용은 PR 본문에 첨부 |
| 비밀값 스캔 범위 | (명시 없음) | `hub/` 하위만 (`hub/scripts/secret_scan.sh`) | `docs/manual.html`의 기존 호스트명 때문에 docs/를 포함하면 모든 PR이 실패. docs는 Phase 7 문서 작업에서 정리 |
| ruff 범위 | `ruff check hub/` | 동일하되 `hub.py dashboard.py hub_cloud.py en/` 제외(pyproject `extend-exclude`) | 보드 코드는 바이트 동일 유지 원칙(§0.2), 구버전 참고 파일은 정리 시점 [ASK] |
| deploy.sh import 검사 | `import aq, dashboard` | 동일 + `py_compile hub.py` | 보드 bare 모드에서 `import dashboard`가 동작함을 확인(경고만 출력) |
| 픽스처 노드 ID | 익명화 | `env_01..08`, `vis_01..05` + `fixtures/nodes.json`(라벨 CLASS_xx 유지) | 환경↔비전 페어링을 라벨로 보존해야 (label, bucket) 조인 테스트 가능 |
| `ssh q` 호출 | deny 패턴 `Bash(ssh q *sudo*)` | `~/.ssh/config`에 `BatchMode yes`를 넣어 Claude가 `ssh q '…'` 형태만 쓰도록 통일 | `ssh -o BatchMode=yes q …` 형태는 deny 패턴과 매치되지 않음 |
| Claude Code 작업 디렉터리 | 저장소 루트 가정 (`.claude/settings.json`, `CLAUDE.md`) | Phase 0~1 세션은 상위 폴더 `c:\Users\phlox\PRJ`에서 실행됨 → 저장소의 `.claude/settings.json`(deny·hook)과 `CLAUDE.md`가 **로드되지 않음**. 2026-08-29 검증에서 `ssh q sudo true`가 차단되지 않은 원인 | 이후 세션은 반드시 `Arduino_MQTT_MultiNode_Demo/`를 작업 디렉터리로 시작한다. deny·hook 동작 확인은 그 세션에서 재실행 |
| PreToolUse 훅 명령 | `python .claude/hooks/precommit_tests.py`(상대경로) | `python "$CLAUDE_PROJECT_DIR/.claude/hooks/precommit_tests.py"` | Bash 도구의 셸 cwd는 호출 간에 유지되므로 `cd hub` 뒤에는 상대경로가 깨져 **모든 Bash 호출이 훅 오류로 차단**됐다(2026-08-29 검증 중 발견). 절대경로 환경변수로 교체. 훅 스크립트 자체는 `__file__` 기준이라 변경 없음 |
| deny 동작 확인 | Phase 1 완료 기준 §4.4-2 | 저장소 루트에서 시작한 세션(2026-08-29)에서 `ssh q sudo true` → `Permission to use Bash with command ssh q sudo true has been denied.` | 확인 완료. 위 행(상위 폴더 세션)의 미차단 원인이 작업 디렉터리였음을 재확인 |
| PR 개설 | Claude Code가 `gh pr create` | **사용자가 compare URL로 개설**(PR 본문은 Claude가 작성해 전달) | `gh` 미설치, `GH_TOKEN`/`GITHUB_TOKEN` 없음. `gh pr checks` 대신 GitHub REST API(`/actions/runs`) 무인증 조회로 CI 결과 확인 |

## Phase 1b — 플랜 §5와 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| before 측정 방법 | 배포 후 `journalctl`의 `[perf]` 로그 + 브라우저 DevTools 웹소켓 바이트 | `hub/scripts/perf_probe.py`(bare 모드)로 **배포·재시작 없이** 보드에서 측정. 페이로드는 figure JSON / CSV 바이트로 근사 | 재시작(sudo) 없이 before를 얻기 위해. 브라우저 DevTools 수치는 없음 — Streamlit은 변경 없는 요소를 재전송하지 않으므로 probe 수치는 상한 |
| ② 캐시 키 | `MAX(id)` | `data_version()` = (`MAX(id)`, 최신 행의 5분 버킷). 무거운 28일 통계는 **버킷**으로, 라이브 figure는 노드별 `recv_time`으로 키 | `MAX(id)`는 8노드가 수 초마다 바꾸므로 60 s 주기마다 캐시 미스 → 통계는 버킷당 1회만 재생성 |
| ② figure 캐시 종류 | `@st.cache_data` | **`@st.cache_resource`**(ttl 300, `max_entries`) | 보드 벤치마크: `cache_data` 히트 = unpickle → plotly 재검증(레이더 25 ms×8, ②의 5개 280 ms)으로 새로 만드는 것과 같은 비용. `cache_resource`는 같은 객체를 돌려줘 히트 ≈ 0 ms. `st.plotly_chart`는 읽기만 함 |
| ② ★ 마커 오버레이 | `copy.deepcopy` 후 `add_trace` | 플랜대로 deepcopy **+ 배치 추가**(`add_traces` 1회, `layout.annotations` 1회 대입) | 공유 객체라 deepcopy 필수. `add_annotation` 16회는 매번 전체 목록 재검증 → 293 ms, 배치 51 ms |
| ③ 노드별 산점도 과거점 | "서버 집계본만 전송" | 밀도 배경은 `np.histogram2d` 집계, 과거점은 **시간 균등 표본 ≤ 1,500점**(`SCATTER_MAX_POINTS`) | 점을 없애면 화면이 달라짐. 표본화로 모양 유지, 페이로드 634 KB → 49 KB |
| ② boxplot 이상치 | (언급 없음) | `boxpoints="outliers"` 대신 순위 균등 표본 ≤ 300점 scatter | 사전 집계 `go.Box(q1=…)`에는 이상치 인자가 없음 |
| bare 모드 검사 | `deploy.sh`의 `import dashboard` | fragment 본문은 bare 모드에서 실행되지 않음(Streamlit이 컨텍스트 없으면 `None` 반환) → `perf_probe.py`가 `__wrapped__`로 호출 | import 검사만으로는 섹션 코드가 실행되지 않으므로 probe를 배포 후 검증에 사용 |
| `components.html` | (없음) | `st.components.v1.html` 2026-06-01 이후 제거 예고(1.58에선 경고). `st.iframe`은 URL 전용, `st.html`은 iframe 격리 없음 → **Phase 5**에서 처리 | 시각 동일 기준 유지 |
| dashboard 유닛 `After=` | 1b에서 수정 | Phase 0 D-1에서 이미 `multinode_aq_hub.service`로 수정됨 | — |
| 태블릿 체감 기록 [ASK] | 1b | **연기** — 행동 지침용 LED 인디케이터 부착·학생 수행 후 | 사용자 결정 2026-08-29 |
