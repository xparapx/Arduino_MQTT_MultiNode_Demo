# -*- coding: utf-8 -*-
"""v3(2026-10-07): 손으로 만든 그림에서 비전 노드 제거, 복도 키오스크 추가, 새 그림(r_kiosk, p_share) 생성."""
import re, shutil, os
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
for s in ("s1", "s2", "s5"):
    shutil.copy(f"../poster3/shots/kiosk-{s}.png", f"img/kiosk_{s}.png")

def rw(p, f):
    s = open(p, encoding="utf-8").read(); n = f(s); assert n != s, p; open(p, "w", encoding="utf-8").write(n)

# ---- r_system: 센서 노드가 2행 차지, 오른쪽 위 = 대시보드·키오스크
def f(s):
    s = s.replace('#sen{grid-column:1;grid-row:1} #vis{grid-column:1;grid-row:2}', '#sen{grid-column:1;grid-row:1/3}')
    s = s.replace(' <div class="panel box" id="vis" data-fit="vis"><div class="h">비전 노드 ×5</div><div>Nicla Vision · FOMO</div><div>영상 비전송, <b>인원 수만</b></div></div>\n', '')
    s = s.replace('<div class="panel box" id="sen" data-fit="sen"><div class="h">센서 노드 ×8</div><div>UNO R4 WiFi</div><div>SEN55 · SCD30</div>',
                  '<div class="panel box" id="sen" data-fit="sen"><div class="h">센서 노드 ×8</div><div>UNO R4 WiFi + Grove</div><div>SEN55 · SCD30, 5분 평균</div><div>센서 무응답 시 자동 복구</div>')
    s = s.replace('<div class="panel box" id="dash" data-fit="dash"><div class="h">대시보드</div><div>PC·폰, 조회 전용</div><div>실시간 상태·진단</div></div>',
                  '<div class="panel box" id="dash" data-fit="dash"><div class="h">대시보드 · 복도 키오스크</div><div>PC·폰 조회 전용 공개</div><div>1학년 복도 DID 송출(UNO Q 2호)</div></div>')
    s = s.replace("const a1=pt('sen','r'),h1=pt('hub','l',.3);arrow(a1,h1,ink,{curve:1});\n const a2=pt('vis','r'),h2=pt('hub','l',.7);arrow(a2,h2,ink,{curve:1});\n const gx=(a1[0]+h1[0])/2,gy=(h1[1]+h2[1])/2;",
                  "const a1=pt('sen','r'),h1=pt('hub','l',.5);arrow(a1,h1,ink,{curve:1});\n const gx=(a1[0]+h1[0])/2,gy=h1[1];")
    return s.replace('<div class="t">시스템 구성 — 측정·허브·제어·표시', '<div class="t">시스템 구성 — 측정·허브·제어·공유')
rw("figs/r_system.html", f)

# ---- p_system
def f(s):
    s = s.replace('#sen{grid-column:1;grid-row:1} #vis{grid-column:1;grid-row:2}', '#sen{grid-column:1;grid-row:1/3}')
    s = s.replace('  <div class="panel box" id="vis" data-fit="vis"><div class="h">비전 노드 ×5</div><div>인원 수만</div></div>\n', '')
    s = s.replace('<div class="panel box" id="sen" data-fit="sen"><div class="h">센서 노드 ×8</div><div><span class="co2">CO₂</span>·<span class="voc">VOC</span>·<span class="pm">먼지</span></div><div>5분 평균</div></div>',
                  '<div class="panel box" id="sen" data-fit="sen"><div class="h">센서 노드 ×8</div><div><span class="co2">CO₂</span>·<span class="voc">VOC</span>·<span class="pm">먼지</span></div><div>5분 평균</div><div>UNO R4 + Grove</div></div>')
    s = s.replace('<div class="panel box" id="dash" data-fit="dash"><div class="h">대시보드</div><div>PC·폰 조회</div></div>',
                  '<div class="panel box" id="dash" data-fit="dash"><div class="h">대시보드·키오스크</div><div>PC·폰 조회</div><div>복도 DID 송출</div></div>')
    s = s.replace("arrow(pt('sen','r'),pt('hub','l',.3),ink,{curve:1});arrow(pt('vis','r'),pt('hub','l',.7),ink,{curve:1});", "arrow(pt('sen','r'),pt('hub','l',.5),ink,{curve:1});")
    return s
rw("figs/p_system.html", f)

# ---- m_system: 비전 블록 제거, 센서 2행, 대시보드에 키오스크 추가
def f(s):
    s = re.sub(r' <div class="b t-human" data-fit="vis">.*?</div></div>\n', '', s, flags=re.S, count=1)
    s = s.replace('<div class="b t-co2" data-fit="sen">', '<div class="b t-co2" data-fit="sen" style="grid-row:1/3">')
    s = s.replace('<div>R4·SEN55·SCD30</div></div>', '<div>R4·SEN55·SCD30</div><div>CO₂·VOC·먼지</div></div>')
    s = s.replace('대시보드</div><div>PC·폰 조회 전용</div></div>', '대시보드·키오스크</div><div>PC·폰 조회 · 복도 DID</div></div>')
    return s
rw("figs/m_system.html", f)

# ---- r_cycle
def f(s):
    s = s.replace('CO₂·VOC·재실 인원, 영상 없는 엣지 AI', 'CO₂·VOC·먼지 + 장치 전력(비용)')
    s = s.replace('센서 8·비전 5 노드, 73일 <b>157,744건</b>', '센서 노드 8대, 73일 <b>157,744건</b>')
    s = s.replace('시간 패턴·재실 회귀, GMM <b>4개 레짐</b>', '시간 패턴·감쇠 적합, GMM <b>4개 레짐</b>')
    s = s.replace('실측 기반 환기 수칙, 매뉴얼·오픈소스', '환기 수칙, 공개 대시보드·복도 키오스크')
    return s
rw("figs/r_cycle.html", f)

# ---- p_wide_kpi: 탐지 1명당 → 수업 중 상승률
def f(s):
    return s.replace('''      <div class="lab">탐지 1명당 CO₂</div>
      <div class="v"><span class="kpi">+194</span><span class="u">ppm</span></div>
      <div class="sub">ρ 0.31–0.58</div>''', '''      <div class="lab">수업 중 CO₂ 상승</div>
      <div class="v"><span class="kpi">7</span><span class="u">ppm/분</span></div>
      <div class="sub">1교시 740→1,204</div>''')
rw("figs/p_wide_kpi.html", f)

# ---- p_hero_timeline
def f(s):
    s = s.replace('["7월 초", "8교실·비전 5대 설치", ""]', '["7월 초", "8교실 센서 노드 설치", ""]')
    s = s.replace('["10월", "성과발표·공유", "c"]', '["10월 4일", "복도 키오스크 송출", "c"]')
    return s.replace('시범 노드 2대에서 플러그 16대 자동 제어까지', '시범 노드 2대에서 플러그 자동 제어·복도 키오스크까지')
rw("figs/p_hero_timeline.html", f)

# ---- 새 그림
open("figs/r_kiosk.html", "w", encoding="utf-8").write('''<!doctype html><html lang="ko" data-kind="r" data-w="159" data-h="58"><head><meta charset="utf-8"><link rel="stylesheet" href="../design/base.css"><style>
html,body{height:100%} body{word-break:keep-all}
.fill{display:grid;grid-template-columns:1fr 1fr;gap:3mm}
.c{display:flex;flex-direction:column;gap:.8mm;min-height:0}
.c .im{flex:1;min-height:0;border:.3mm solid var(--grid);border-radius:1.4mm;overflow:hidden;background:#1b1f27}
.c img{width:100%;height:100%;object-fit:cover;display:block}
.c .cap{flex:none;line-height:1.25} .c .cap b{margin-right:.4em}
</style></head><body><div class="fig">
<div class="t">복도 키오스크(DID) 화면 <span class="sub">1920×1080 다크 전용 · 10월 7일 실화면 · 15초 간격 자동 회전</span></div>
<div class="fill">
 <div class="c"><div class="im"><img src="../img/kiosk_s1.png" alt=""></div><div class="cap"><b>교실 현황판</b>8개 교실 CO₂ 게이지 · 좋음/보통/나쁨 · 레짐 칩 · 가동 중 장치</div></div>
 <div class="c"><div class="im"><img src="../img/kiosk_s5.png" alt=""></div><div class="cap"><b>교실별 전기 사용</b>최근 7일 플러그 적산(공기청정기·환풍기) · 오늘 합계</div></div>
</div></div></body></html>''')
open("figs/p_share.html", "w", encoding="utf-8").write('''<!doctype html><html lang="ko" data-kind="p" data-w="143" data-h="85"><head><meta charset="utf-8"><link rel="stylesheet" href="../design/base.css"><style>
html,body{height:100%} body{word-break:keep-all}
.fill{display:grid;grid-template-columns:1fr 1fr;gap:3.5mm}
.c{display:flex;flex-direction:column;gap:1.4mm;min-height:0}
.c .im{flex:1;min-height:0;border:.45mm solid var(--grid);border-radius:2.2mm;overflow:hidden;background:#f5f6f8;position:relative}
.c img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:left top;display:block}
.c .cap{flex:none;line-height:1.2;display:flex;flex-direction:column;gap:.3mm} .c .cap b{display:block}
.c .cap .d{color:var(--dim)}
</style></head><body><div class="fig">
<div class="t">공개 대시보드와 복도 키오스크</div>
<div class="fill">
 <div class="c"><div class="im"><img src="../img/home.png" alt=""></div><div class="cap"><b>공개 대시보드</b><span class="d">PC·폰, 조회 전용 · 질문 순서 메뉴</span></div></div>
 <div class="c"><div class="im" style="background:#1b1f27"><img src="../img/kiosk_s1.png" alt="" style="object-position:center"></div><div class="cap"><b>복도 키오스크(DID)</b><span class="d">1학년 복도, 지나가며 보는 현황판</span></div></div>
</div></div></body></html>''')
print("figs patched")
