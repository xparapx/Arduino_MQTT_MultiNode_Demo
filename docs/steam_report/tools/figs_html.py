# -*- coding: utf-8 -*-
"""MintCap 도식 — 차트(charts.py)와 같은 디자인 체계. 실제 크기(mm)·실제 글자 크기(pt)로 그린다.
   글자: 제목(굵게) / 그 밖의 모든 글자 두 단계 — 보고서 10/9pt, 포스터 20/16pt.
   색: 남색 잉크 + 무채색, 강조는 민트 하나. 레짐 4색(민트·파랑·주황·보라)과 실제 전선 색만 예외."""
import os, shutil, subprocess, json
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
P3 = os.path.dirname(HERE) + "/poster3"
INK = "#14283c"; SUB = "#5b6b79"; LINE = "#c5ced6"; SOFT = "#f2f5f7"
MINT = "#1fa97f"; MINTBG = "#e4f5ef"; CO2 = "#2f6fb5"; VOC = "#d9772b"; MIX = "#7a5bb5"; WARN = "#d64545"
OUT = {"r": HERE + "/figs", "p": HERE + "/pfigs"}
for d in OUT.values(): os.makedirs(d + "/img", exist_ok=True)
SIZE = {"r": (9, 10), "p": (16, 20)}
JOBS = []

# 화면 캡처(라이트) 준비
S = P3 + "/shots/"
for d in OUT.values():
    Image.open(S + "light-home.png").crop((0, 0, 1600, 760)).save(d + "/img/home.png")
    Image.open(S + "light-home.png").crop((232, 30, 1600, 720)).save(d + "/img/home_main.png")
    Image.open(S + "light-dx-regime.png").crop((232, 90, 1600, 640)).save(d + "/img/regime_main.png")
    Image.open(S + "light-dx-action.png").crop((232, 100, 1600, 650)).save(d + "/img/action_main.png")
    Image.open(S + "light-energy.png").crop((232, 60, 1600, 610)).save(d + "/img/energy_main.png")

def page(kind, name, w, h, title, body, extra_css=""):
    base, ttl = SIZE[kind]
    u = base / 9.0                      # 선 굵기·간격 배율
    css = f"""<!doctype html><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}} html,body{{background:#fff}}
body{{width:{w}mm;height:{h}mm;overflow:hidden;font-family:"Malgun Gothic",sans-serif;color:{INK};font-size:{base}pt;line-height:1.28;padding:{1.2*u}mm {1.5*u}mm {1.0*u}mm;display:flex;flex-direction:column;gap:{1.6*u}mm}}
.t{{font-size:{ttl}pt;font-weight:700;line-height:1.2;flex:none}}
b{{font-weight:700}} .sub{{color:{SUB}}}
.box{{border:{0.3*u}mm solid {INK};border-radius:{1.6*u}mm;background:#fff;padding:{1.3*u}mm {1.6*u}mm}}
.acc{{background:{MINTBG};border-color:{MINT}}}
.fill{{flex:1;min-height:0}}
.ar{{color:{LINE};font-weight:700;align-self:center;text-align:center;flex:none}}
.no{{display:inline-flex;align-items:center;justify-content:center;width:{4.4*u}mm;height:{4.4*u}mm;border-radius:50%;background:{INK};color:#fff;font-weight:700;flex:none}}
.acc .no{{background:{MINT}}}
{extra_css}</style><div class="t">{title}</div>{body}"""
    f = f"{OUT[kind]}/{name}.html"; open(f, "w", encoding="utf-8").write(css)
    JOBS.append((f, w, h, 4 if kind == "r" else 2.5, f"{OUT[kind]}/{name}.png"))

# ================= 1. 탐구 사이클 =================
CY = [("1", "공동체 문제 발견", "‘답답하다’는 느낌을<br>측정 가능한 문제로", 0), ("2", "측정 설계", "CO₂×VOC×재실 인원<br>영상 없는 엣지 AI", 0),
      ("3", "데이터 수집", "센서 8·비전 5 노드<br>73일 무인 운영", 0), ("4", "분석·모델링", "시간 패턴·재실 회귀<br>GMM 4개 레짐", 0),
      ("5", "인사이트", "수업시간 39% 초과<br>원인별 차등 대응", 0), ("6", "확장 — 제어", "플러그 16대 제어<br>다를 때만 명령", 1),
      ("7", "제안·공유", "실측 기반 환기 수칙<br>매뉴얼·오픈소스", 1)]
def cyc(kind):
    u = SIZE[kind][0] / 9
    def card(n, t, d, a):
        if kind == "p":
            t2 = {"공동체 문제 발견": "문제<br>발견", "측정 설계": "측정<br>설계", "데이터 수집": "데이터<br>수집", "분석·모델링": "분석·<br>모델링", "인사이트": "인사이트", "확장 — 제어": "확장:<br>제어", "제안·공유": "제안·<br>공유"}[t]
            return f'<div class="box{" acc" if a else ""}" style="flex:1;padding:{1*u}mm;display:flex;flex-direction:column;gap:{1*u}mm;justify-content:center"><span class="no">{n}</span><b>{t2}</b></div>'
        return f'<div class="box{" acc" if a else ""}" style="flex:1;display:flex;flex-direction:column;gap:{.8*u}mm"><div style="display:flex;gap:{1.2*u}mm;align-items:center"><span class="no">{n}</span><b>{t}</b></div><div>{d}</div></div>'
    ar = f'<div class="ar" style="font-size:{7*u}pt">▶</div>'
    loop = (f'<div class="box" style="flex:1;border-style:dashed;border-color:{MINT};display:flex;flex-direction:column;justify-content:center;gap:{.8*u}mm"><b style="color:#12775a">{"↻ 다시<br>1번으로" if kind == "p" else "↻ 다시 1로"}</b>'
            + ("" if kind == "p" else "<div>제어 효과는?<br>전력 비용은?</div>") + "</div>")
    r1 = ar.join(card(*c) for c in CY[:4]); r2 = ar.join(card(*c) for c in CY[4:]) + ar + loop
    return f'<div class="fill" style="display:flex;flex-direction:column;gap:{1.6*u}mm"><div style="display:flex;gap:{.8*u}mm;flex:1">{r1}</div><div style="display:flex;gap:{.8*u}mm;flex:1">{r2}</div></div>'
page("r", "d_cycle", 159, 50, "공동체 데이터 탐구 사이클 — 단계마다 우리 팀이 실제로 한 일", cyc("r"))
page("p", "d_cycle", 143, 85, "공동체 데이터 탐구 사이클", cyc("p"))

# ================= 2. 시스템 구성 =================
def sysd(kind):
    u = SIZE[kind][0] / 9; p = kind == "p"
    def b(t, d, acc=False, grow=1):
        return f'<div class="box{" acc" if acc else ""}" style="flex:{grow};display:flex;flex-direction:column;justify-content:center;text-align:center;gap:{.6*u}mm"><b>{t}</b>{"" if not d else f"<div>{d}</div>"}</div>'
    col = lambda *x: f'<div style="flex:1.25;display:flex;flex-direction:column;gap:{1.4*u}mm">{"".join(x)}</div>'
    ar = lambda t: f'<div class="ar" style="width:{(7 if p else 13)*u}mm">▶{"" if p else f"<div class=sub style=font-weight:400>{t}</div>"}</div>'
    left = col(b("센서 노드 ×8", "CO₂·VOC·먼지" if p else "UNO R4 · SEN55 · SCD30<br>CO₂·VOC·먼지, 5분 평균"), b("비전 노드 ×5", "인원 수만" if p else "Nicla Vision · FOMO<br>영상 비전송, 인원 수만"))
    hub = b("허브<br>UNO Q" if p else "허브 UNO Q", "저장·분석<br>판정·웹" if p else "MQTT 수집 → SQLite<br>품질 검사 · 레짐 판정<br>제어 추론 · 대시보드", grow=1.15)
    right = col(b("플러그 ×16", "전력 실측" if p else "공기청정기 8 · 환풍기 8<br>전력 실측 · 원격 스위치", acc=True), b("대시보드", "PC·폰" if p else "PC·폰 실시간 감시·진단<br>조회 전용 공개"))
    return f'<div class="fill" style="display:flex;gap:{.6*u}mm;align-items:stretch">{left}{ar("MQTT<br>(TLS)")}{hub}{ar("명령 ↓<br>전력 ↑")}{right}</div>'
page("r", "d_system", 159, 53, "시스템 구성 — 측정에서 제어까지 하나의 파이프라인", sysd("r"))
page("p", "d_system", 143, 85, "측정에서 제어까지 한 줄기", sysd("p"))

# ================= 3. 판정·제어 흐름 =================
def flow(kind):
    u = SIZE[kind][0] / 9; p = kind == "p"
    def b(n, t, d, acc=False, grow=1):
        return f'<div class="box{" acc" if acc else ""}" style="flex:{grow};display:flex;flex-direction:column;gap:{.6*u}mm;justify-content:center"><div style="display:flex;gap:{1.2*u}mm;align-items:center"><span class="no">{n}</span><b>{t}</b></div>{"" if not d else f"<div>{d}</div>"}</div>'
    ar = '<div class="ar">▶</div>'
    if p:
        row = b("1", "측정 → 수집", "") + ar + b("2", "판정", "") + ar + b("3", "제어", "", acc=True)
        lines = f'<div>② 품질 검사 → 레짐 → 규칙 → 목표 상태</div><div>③ 실물과 <b>다를 때만</b> 스위치</div><div class="box" style="border-style:dashed;border-color:{WARN}"><b style="color:{WARN}">품질 검사 탈락 → 판정 보류</b></div>'
    else:
        row = (b("1", "측정 → 수집", "5분 평균 → MQTT 발행<br>허브가 SQLite에 저장") + ar
               + b("2", "품질 검사 → 레짐 → 규칙", "유효율 95% 이상만 판정 → GMM 레짐<br>→ 1,000/700 ppm 규칙 → 목표 상태", grow=1.45) + ar
               + b("3", "실물 비교 → 스위치", "플러그 실제 상태와 비교<br><b>다를 때만</b> 명령 발행", acc=True))
        lines = (f'<div class="box" style="border-style:dashed;border-color:{WARN}"><b style="color:{WARN}">품질 검사 탈락 → 판정 보류</b> — 이전 상태를 유지한다. 나쁜 데이터로는 스위치를 만지지 않는다.</div>'
                 f'<div class="box" style="border-color:{LINE}"><b>판정과 집행의 분리</b> — 분석 모듈과 플러그 모듈이 따로 동작하여 한쪽이 멈춰도 오동작하지 않는다.</div>')
    return f'<div class="fill" style="display:flex;flex-direction:column;gap:{1.5*u}mm"><div style="display:flex;gap:{.8*u}mm;flex:1">{row}</div>{lines}</div>'
page("r", "d_flow", 159, 46, "판정에서 제어까지 — 데이터가 스위치를 누르는 3단계와 두 가지 안전 원칙", flow("r"))
page("p", "d_flow", 143, 85, "데이터가 스위치를 누르기까지", flow("p"))

# ================= 4. 레짐 → 대응 (보고서) =================
def quad():
    def q(c, bg, t, pct, act):
        return f'<div class="box" style="border-color:{c};background:{bg};display:flex;flex-direction:column;justify-content:center;gap:.5mm"><div><b style="color:{c}">{t}</b> {pct}</div><div>{act}</div></div>'
    grid = (f'<div style="flex:1.25;display:grid;grid-template-columns:5mm 1fr 1fr;grid-template-rows:1fr 1fr 4.6mm;gap:1.2mm">'
            f'<div style="grid-row:1/3;writing-mode:vertical-rl;transform:rotate(180deg);text-align:center" class="sub">VOC(물질) →</div>'
            + q(VOC, "#fbf0e6", "물질 레짐", "15%", "→ 공기청정기 가동") + q(MIX, "#f1edf8", "복합 레짐", "9%", "→ 둘 다 가동")
            + q("#12775a", MINTBG, "청정", "62%", "→ 유지") + q(CO2, "#eaf1f9", "인체 레짐", "15%", "→ 환풍기 가동")
            + f'<div></div><div style="grid-column:2/4;text-align:center" class="sub">CO₂(사람) →</div></div>')
    def s(n, l): return f'<div class="box" style="border-color:{LINE};display:flex;flex-direction:column;justify-content:center"><b>{n}</b><div>{l}</div></div>'
    st = (f'<div style="flex:1;display:grid;grid-template-columns:1fr 1fr;gap:1.2mm">' + s("플러그 16대", "레짐별 자동 제어") + s("1,000 / 700 ppm", "켜고 끄는 기준")
          + s("최소 10분 가동", "깜빡임 방지") + s("τ 중앙값 42분", "환기 회복 속도") + '</div>')
    return f'<div class="fill" style="display:flex;gap:2.2mm">{grid}{st}</div>'
page("r", "d_quad", 159, 46, "원인이 다르면 해법도 다르다 — 레짐별 대응 장치와 운영 기준", quad())

# ================= 5. 대시보드 =================
def dash_layout():
    pts = [("1", 6.5, 47), ("2", 6.5, 13), ("3", 42, 11), ("4", 50, 37), ("5", 42, 92)]
    bd = "".join(f'<span class="no" style="position:absolute;left:{x}%;top:{y}%;border:.3mm solid #fff">{n}</span>' for n, x, y in pts)
    pr = [("1", "믿어도 되는 데이터인가", "수집·노드·분석 상태를 늘 보이게"), ("2", "메뉴 = 질문 순서", "지금? → 변화? → 왜? → 무엇을? → 비용?"),
          ("3", "위에서 아래로 중요도순", "상태 → 교실별 판정 → 경보"), ("4", "판정과 실물을 나란히", "분석 결과 옆에 플러그 실측, 다를 때만 빨강"),
          ("5", "색과 움직임은 정보만", "레짐 4색 고정, 가동은 회전으로 표시")]
    rows = "".join(f'<div style="display:flex;gap:1.4mm;align-items:flex-start"><span class="no">{n}</span><div><b>{t}</b><div>{d}</div></div></div>' for n, t, d in pr)
    return (f'<div class="fill" style="display:flex;gap:3mm"><div style="position:relative;flex:none;width:84mm;align-self:center;aspect-ratio:1600/760;border:.3mm solid {LINE};border-radius:1.2mm;overflow:hidden">'
            f'<img src="img/home.png" style="width:100%;height:100%;display:block">{bd}</div><div style="flex:1;display:flex;flex-direction:column;justify-content:space-between">{rows}</div></div>')
page("r", "d_dash_layout", 159, 60, "대시보드 화면 설계 — 무엇을, 왜 그 자리에 두었는가", dash_layout())
def dash_screens():
    T = [("home_main.png", "Home — 상태·판정·실물·경보"), ("regime_main.png", "진단 — CO₂–VOC 레짐 평면"), ("action_main.png", "제어·경보 — 기준 밴드와 24시간 추이"), ("energy_main.png", "에너지 — 장치별 전력과 반별 비교")]
    c = "".join(f'<div style="display:flex;flex-direction:column;gap:.8mm;min-height:0"><b>{t}</b><img src="img/{f}" style="width:100%;flex:1;min-height:0;object-fit:cover;object-position:top left;border:.3mm solid {LINE};border-radius:1.2mm"></div>' for f, t in T)
    return f'<div class="fill" style="display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:2.4mm 3mm">{c}</div>'
page("r", "d_dash_screens", 159, 86, "대시보드 주요 화면 (8월 28일 측정 데이터로 재현, 플러그 전력은 시험값)", dash_screens())
page("p", "d_dash", 143, 85, "판정과 실물을 나란히 보여준다",
     f'<div class="fill" style="border:.5mm solid {LINE};border-radius:2mm;overflow:hidden"><img src="img/home_main.png" style="width:100%;height:100%;object-fit:cover;object-position:top left;display:block"></div>')

# ================= 6. 센서 노드 배선 (보고서) =================
def wiring():
    F = 3.175                                   # 9pt = 3.175mm (SVG 단위 = mm)
    wires = [("#222", "GND"), ("#d64545", "VCC 5V"), ("#ffffff", "SDA"), ("#e3b100", "SCL")]
    def cable(x1, y1, x2, y2):
        o = ""
        for i, (c, _) in enumerate(wires):
            a, b = y1 + i * 1.5, y2 + i * 1.5; mx = (x1 + x2) / 2; d = f"M{x1} {a} C{mx} {a} {mx} {b} {x2} {b}"
            if c == "#ffffff": o += f'<path d="{d}" fill="none" stroke="#8a96a1" stroke-width="1.15"/>'
            o += f'<path d="{d}" fill="none" stroke="{c}" stroke-width=".8" stroke-linecap="round"/>'
        return o
    port = lambda x, y: f'<rect x="{x}" y="{y}" width="4" height="7" rx=".8" fill="#fff" stroke="{INK}" stroke-width=".3"/>'
    tx = lambda x, y, t, w="400", a="start", c=INK: f'<text x="{x}" y="{y}" font-size="{F}" font-weight="{w}" text-anchor="{a}" fill="{c}">{t}</text>'
    s = f'<svg viewBox="0 0 156 49" style="width:100%;height:100%" font-family="Malgun Gothic">'
    s += f'<rect x="1" y="1" width="66" height="40" rx="2.5" fill="{SOFT}" stroke="{INK}" stroke-width=".3"/>' + tx(4, 38.3, "Arduino UNO R4 WiFi", "700")
    s += f'<rect x="5" y="3.5" width="58" height="30" rx="2" fill="#fff" stroke="{INK}" stroke-width=".3"/>' + tx(8, 9, "Grove Base Shield", "700")
    s += f'<rect x="8" y="12" width="17" height="6" rx="1.2" fill="#fff" stroke="{INK}" stroke-width=".3"/><rect x="8.6" y="12.6" width="7.5" height="4.8" rx=".8" fill="{INK}"/>'
    s += f'<text x="12.35" y="16.2" font-size="{F}" font-weight="700" text-anchor="middle" fill="#fff">5V</text>' + tx(17.2, 16.2, "3.3V", c=SUB) + tx(8, 23.5, "전압 스위치는 5V") + tx(8, 29.5, "다른 포트는 사용 안 함", c=SUB)
    s += f'<rect x="45" y="5" width="16.5" height="27" rx="1.5" fill="{MINTBG}" stroke="{MINT}" stroke-width=".3"/>' + tx(46.2, 19.6, "I2C", "700", c="#12775a")
    s += port(56.5, 6.2) + port(56.5, 14.2) + port(56.5, 22.2)
    for y, n, a, d in [(3, "SEN55", "0x69", "미세먼지 · VOC · NOx"), (25, "SCD30", "0x61", "CO₂ · 온도 · 습도")]:
        s += f'<rect x="104" y="{y}" width="51" height="18" rx="2" fill="#fff" stroke="{INK}" stroke-width=".3"/>' + port(102, y + 5.5)
        s += tx(109, y + 7, n, "700") + tx(152, y + 7, "주소 " + a, a="end", c=SUB) + tx(109, y + 13.5, d)
    s += cable(60.5, 7.5, 102, 9.8) + cable(60.5, 15.5, 102, 31.8)
    s += tx(68.5, 4.2, "Grove 케이블")
    x = 2
    s += tx(x, 47.3, "Grove 4선:", "700"); x += 21
    for c, lab in wires:
        if c == "#ffffff": s += f'<line x1="{x}" y1="46.2" x2="{x+7}" y2="46.2" stroke="#8a96a1" stroke-width="1.5"/>'
        s += f'<line x1="{x}" y1="46.2" x2="{x+7}" y2="46.2" stroke="{c}" stroke-width="1.1" stroke-linecap="round"/>' + tx(x + 8.5, 47.3, lab); x += 9.5 + len(lab) * 2.2 + 7
    return f'<div class="fill">{s}</svg></div>'
page("r", "d_wiring", 159, 58, "센서 노드 배선 — 실드의 I2C 포트에 케이블 두 개만 꽂으면 된다", wiring())

json.dump(JOBS, open(HERE + "/figs_jobs.json", "w", encoding="utf-8"))
for f, w, h, sc, out in JOBS:
    cw, ch = round(w * 3.7795), round(h * 3.7795)
    r = subprocess.run(["node", HERE + "/shot.mjs", f, str(cw), str(ch), str(sc), out], capture_output=True, text=True, encoding="utf-8", errors="replace")
    ov = [l for l in r.stdout.splitlines() if l.startswith("{")]
    pg = json.loads(ov[0])["page"] if ov else None
    print(os.path.basename(out), "ok" if os.path.exists(out) else "FAIL", "| overflow!" if pg and (pg[0] > cw + 1 or pg[1] > ch + 1) else "", pg, (cw, ch))
