# legacy — 운영에서 제외된 구세대 코드 아카이브 (2026-09-06)

여기 있는 코드는 **어떤 서비스·타이머에서도 실행되지 않는다.** 삭제하지 않고
보관하는 이유: `docs/manual.html`의 수동 실습(학습판) 사이클이 이 코드를
서사로 참조하고, 프로젝트 발전 계보(로컬 브로커 → 클라우드 → SPA)의 실물이기
때문이다. 의존성(`streamlit`·`streamlit-autorefresh`·`plotly`)은 pyproject에서
제거되었으므로 **그대로는 실행되지 않는다** — 돌려보려면 별도 venv에 세 패키지를
설치하고 import 경로(`aq.plots` 등)를 이 폴더에 맞게 조정해야 한다.

| 경로 | 무엇 | 대체 |
|---|---|---|
| `streamlit/dashboard.py` | Streamlit 페이지 1 (모니터링, :8501) | `hub/webapp.py` + `hub/web/` SPA (2026-08-29 전환) |
| `streamlit/pages/2_diagnosis.py` | Streamlit 페이지 2 (진단 A–I) | SPA `#dx-*` 화면 |
| `streamlit/plots.py` | 페이지 2 plotly 차트 (구 `aq/plots.py`) | `hub/web/charts.js` 손 SVG |
| `streamlit/ui_common.py` | Streamlit 공용 상수·테마 (구 `aq/ui_common.py`) | `aq/webdata.py`에 상수 복제본 |
| `streamlit/analysis_view.py` | analysis 테이블 read side (구 `aq/analysis_view.py`) | `aq/webdata.py` |
| `streamlit/scripts/` | perf_probe.py · plot_check.py (Streamlit bare-mode 측정·점검 도구, `docs/DASHBOARD_PIPELINE.md`의 측정 도구) | — |
| `streamlit/multinode_aq_dashboard.service` | Streamlit systemd 유닛 | web / web_public 유닛 |
| `en/` | 로컬 mosquitto 브로커 v1 (hub.py + dashboard.py, 영문 주석판) | `hub/hub.py` (HiveMQ Cloud) |
| `hub_cloud.py` | 클라우드 전환 초판 — 구 토픽 `multinode_sensor_demo`, occupancy 없음 | `hub/hub.py` |

보드 정리(1회, sudo — 사용자 실행):

```bash
sudo systemctl disable --now multinode_aq_dashboard.service
sudo rm /etc/systemd/system/multinode_aq_dashboard.service
sudo systemctl daemon-reload
```
