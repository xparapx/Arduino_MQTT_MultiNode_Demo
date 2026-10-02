# MintCap 성과발표회 v2 — 그림 디자인 시스템 (모든 에이전트 공통 브리프)

프로젝트: 공주고 STEAM 클럽 MintCap, "멀티노드 IoT·엣지 AI 시스템을 활용한 교실 환경 모니터링 및 제어 시스템 구축에 관한 연구".
8개 교실 센서 노드(CO₂·VOC·미세먼지) + 5개 비전 노드(영상 없이 인원 수만) + 허브 UNO Q + 스마트플러그 16대(환풍기 8·공기청정기 8).
심사 관점: 독창성·창의성, "데이터 기반 소셜 임팩트", 공동체 데이터 탐구 사이클 7단계
(문제 발견 → 측정 설계 → 데이터 수집 → 분석·모델링 → 인사이트 → 확장(제어) → 제안·공유).

## 0. 왜 다시 만드는가 (1차 산출물의 실패 원인)
- 그림 글자(9pt)가 본문(12–14pt)보다 훨씬 작아 **읽히지 않았다**. 도식은 선이 가늘고 톤이 흐려 흑백 복사처럼 보였다.
- 색이 웹앱과 달라(파랑 CO₂, 주황 VOC) 보고서·포스터·대시보드 화면 사이에 **색 언어가 끊겼다**.
- 도식이 "글상자 나열"이라 인포그래픽이 아니라 표처럼 보였다.

## 1. 컬러 — 웹앱 라이트 테마를 그대로 쓴다 (`base.css` 토큰, 출처 `hub/web/app.css`)
| 의미 | 토큰 | 값 | 비고 |
|---|---|---|---|
| CO₂ (사람) | `--co2` / `--co2-deep` | #fd8d3c / #e31a1c | 웹앱 CO₂ 트레이스 색(YlOrRd 중앙값). 강조·높은 값은 deep |
| VOC (물질) | `--voc` / `--voc-deep` | #ce4457 / #8a1d63 | 웹앱 VOC 트레이스 색(matter 중앙값) |
| 레짐 청정/물질/인체/복합 | `--rg-clean/-matter/-human/-mixed` | #0fa8a2 / #d39a00 / #7a5fe0 / #d63f5a | 칸 배경은 `--rg-*-bg` |
| 조치 | 레짐 색을 빌림 | 환기=인체(보라), 공기청정=물질(노랑), 둘 다=복합(분홍), 없음=청정(청록) | 웹앱 `.achip` 규칙 |
| 장치 | `--fan` / `--purifier` | #4292c6 / #38b2a3 | 환풍기 Blues, 공기청정기 Tealgrn |
| 기준선 1,000 ppm | `--thr` (= `--red` #d9534f) | 점선 | |
| 재실 인원 막대 | `--bar` #b9c4d3, 현재/강조 `--acc` #b87a00 | | 웹앱 재실 버킷 막대 |
| 잉크/보조/격자 | `--ink` #1a1d24, `--dim` #5b6472, `--grid` #d9dde3, `--rowline` #e6e9ee | | |
| 패널 | `--panel` #fff + 1px `--grid` 테두리 + 둥근 모서리, 보조 배경 `--panel2` #eef0f3 | | 웹앱 `.panel` |
| 교실 8색 | `--n1…--n8` | | 교실을 구분해야 할 때만 |

규칙: **색은 의미에만.** 장식용 색 금지. 한 그림 안에서 CO₂는 항상 주황, VOC는 항상 진홍, 레짐은 항상 위 4색.
회색은 "맥락"(비교 대상·배경·과거), 채도 있는 색은 "지금 말하려는 것"에만.

## 2. 글자 — 두 단계뿐
- 폰트: **IBM Plex Sans KR**(웹앱과 동일, Google Fonts 링크가 base.css에 있음; 렌더러가 폰트 로딩을 기다림).
- 보고서(`data-kind="r"`): 본문 `--fs` 10.5pt, 제목 `--fs-t` 12pt 굵게. 본문 글(12pt KoPub돋움 Light)과 나란히 놓여도 작아 보이지 않는 크기.
- 포스터(`data-kind="p"`): 본문 17pt, 제목 22pt 굵게 (포스터 본문 글 20pt 옆).
- **그보다 작은 글자 금지** — 축 눈금, 범례, 각주, 단위까지 전부 `--fs`. 글자가 안 들어가면 글을 줄이거나 그림을 키운다(폰트를 줄이지 않는다).
- 숫자는 tabular-nums(기본 적용). 단위는 숫자 뒤 반각 공백(1,000 ppm, 42분).

## 3. 구성 원칙
1. **한 그림 한 메시지** — `.t` 제목이 곧 결론 문장("두 봉우리는 주중에만 나타난다"). 보조 설명은 `.t .sub`(회색)에 짧게.
2. **잉크 최소화** — 위·오른쪽 축선 없음, 가로 격자만 `--rowline`, 테두리는 패널 테두리 하나.
3. **직접 라벨링** — 범례 상자 대신 선·영역 끝에 라벨을 붙인다. 범례는 두 가지 이상의 계열이 겹칠 때만.
4. **웹앱의 부품을 쓴다** — 패널(`.panel`), 칩(`.chip r-human` 등), 점(`.dot`), 번호(`.num`), KPI 숫자(`.kpi`). 보고서 그림이 대시보드 화면과 "같은 제품"처럼 보여야 한다.
5. **여백** — 패널 안 글자는 가장자리에서 최소 1.6mm(보고서)/2.6mm(포스터) 띄운다. 요소 간격은 `var(--u)` 배율.
6. **실제 크기로 만든다** — `<html data-w data-h>`(mm)가 곧 인쇄 크기. 렌더러는 그 크기 그대로 PNG로 만들고 hwpx에 1:1로 넣는다. 넘침은 렌더러가 보고한다(OVERFLOW).
7. 글상자 나열 금지 — 흐름은 화살표/연결선/타임라인으로, 구조는 공간 배치로, 수치는 KPI 숫자나 막대로 "보이게" 만든다.

## 4. 파일 규약
```
v2/design/base.css      공통 토큰·베이스 (수정 금지 — 필요한 보조 스타일은 각 HTML 안 <style>에)
v2/design/DESIGN.md     이 문서
v2/data/data.json       차트 데이터 (아래 5절)
v2/img/*.png            대시보드 라이트 테마 캡처 (home.png 1600×760, home_main.png, regime_main.png, action_main.png, energy_main.png)
v2/figs/<name>.html     그림 1개 = HTML 1개. <html lang="ko" data-kind="r|p" data-w="159" data-h="60"> + <link rel="stylesheet" href="../design/base.css">
v2/out/<name>.png       렌더 결과
v2/render.mjs           node render.mjs [figs/x.html ...]  → out/*.png + OVERFLOW 보고
```
- HTML은 외부 라이브러리 없이(인라인 SVG + CSS + 필요하면 인라인 JS로 SVG 생성). `data.json`은 `<script>`로 fetch하지 말고 **빌드 스크립트가 HTML에 인라인**하거나 JS로 `fetch("../data/data.json")` (file:// 접근 허용됨 — `--allow-file-access-from-files`). fetch를 쓰면 렌더 대기 1.5초 안에 그려져야 하므로 동기적으로 빠르게.
- 이름 규칙: 보고서 `r_<id>.html`, 포스터 `p_<id>.html`. 같은 id는 같은 내용의 크기 변형.
- 넘침 검사: 내부에서 높이를 꽉 채우는 요소에 `data-fit="이름"`을 달면 렌더러가 need/have를 보고한다.
- 렌더 명령은 node 24가 깔린 이 PC에서 `cd v2 && node render.mjs figs/r_day.html` 처럼 실행. 결과 PNG를 Read 도구로 직접 열어 보고 고친다(반드시 눈으로 확인).

## 5. data.json 구조 (v2/data/data.json, 44KB)
- `stats.table[8]` {room, n, mean, p95, mx, over1000, over1500} — 주중 08–16시 교실별 CO₂ 통계(73일)
- `stats.occ{room}` {n, rho, slope, icpt, r2} — 재실–CO₂ (CLASS_01/02/03/05)
- `stats.rates{room}` [mean, sd] ppm/분·탐지 인원당
- `stats.regime_share` {청정, 인체, 물질, 복합} %
- `stats.decay` {n, tau_med, tau_q1, tau_q3, by_room{room: τ}}
- `day` {date "2026-09-15", room, co2[[HH:MM, ppm]], occ[[HH:MM, n]]} — 1반 수업일 하루
- `hourly.weekday / weekend` [[hour, q25, q50, q75]]
- `occ_scatter` {points[[occ, co2]] 2,500개 샘플, slope, icpt, rho, xmax}; `occ_box` [[occ, n, q25, q50, q75]]
- `regime` {lo -1.6, hi 3.2, n 48, counts[48][48] (x=CO₂ z, y=VOC z), total, share, threshold 0.5}
- `decay_case` {room, start, tau, co2_0, baseline 420, series[[HH:MM, ppm]], fit[[HH:MM, ppm]]}
- `tau_all` [τ…] 520건
교실 이름: CLASS_01 → "1반".

## 6. 확정 수치 (글·라벨에 쓸 때 그대로)
73일(2026-07-07~09-19), 측정 157,744건(QC 후 136,634건), 재실 감지 19,711건. 주중 08–16시 CO₂>1,000 ppm 초과율 31.4–45.0%(평균 39%).
재실–CO₂ Spearman ρ 0.31–0.58, 1반 기울기 탐지 1명당 +194 ppm, 상승률 2.6–6.8 ppm/분·탐지 인원당.
레짐(최근 30일) 청정 62 / 인체 15 / 물질 15 / 복합 9 %. 감쇠 사건 520건, τ 중앙값 42분(IQR 23–94). 플러그 16대, 환풍기 ON 1,000/OFF 700 ppm, 공기청정기 ON VOC 200/OFF 120, 최소 10분 가동.
