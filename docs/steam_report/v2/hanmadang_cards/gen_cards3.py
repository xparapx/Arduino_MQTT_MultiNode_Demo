# -*- coding: utf-8 -*-
"""한마당 중앙 포스터 활동 카드 v3 — v1(gen_cards2)의 레이아웃·색 블록 그대로, 글자 크기만 두 단계로 통일 + 내용 정정.
   캔버스 3600px ≈ 셀 폭 123.8mm(29px/mm). 100px ≈ 페이지 9.6pt.
   글자: HEAD = 125px(≈12pt, 표의 활동 제목과 같은 급) / BODY = 94px(≈9pt). 그 밖의 크기 없음."""
import os, io, sys, shutil
from PIL import Image
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
P3 = os.path.dirname(HERE); SHOTS = P3 + "/shots"; V2 = os.path.dirname(P3) + "/v2/out"
P = {"blue": "#a1c9f4", "orange": "#ffb482", "green": "#8de5a1", "red": "#ff9f9b", "purple": "#d0bbff",
     "brown": "#debb9b", "pink": "#fab0e4", "gray": "#cfcfcf", "yellow": "#fffea3", "cyan": "#b9f2f0"}
INK = "#2f3542"; INK2 = "#4a5261"; NAVY = "#1f3c88"
HEAD, BODY = 84, 56

os.makedirs(HERE + "/img", exist_ok=True)
def crop(src, dst, box):
    Image.open(src).crop(box).save(dst)
MAIN = (232, 0, 1600, 1000)
crop(f"{SHOTS}/light-home.png", f"{HERE}/img/home_full.png", (0, 0, 1600, 1000))
for s in ("home", "dx-regime", "dx-action", "energy"):
    crop(f"{SHOTS}/light-{s}.png", f"{HERE}/img/{s}_main.png", MAIN)
for f in ("p_hourly.png", "p_regime.png"):
    shutil.copy(f"{V2}/{f}", f"{HERE}/img/{f}")

CSS = f"""
<meta charset="utf-8"><style>
html,body{{margin:0;background:#fff}}
body{{font-family:"Malgun Gothic","Noto Sans KR",sans-serif;color:{INK};overflow:hidden;font-size:{BODY}px;line-height:1.25}}
*{{box-sizing:border-box}}
.wrap{{display:flex;gap:36px;padding:30px 34px;width:100%;height:100%;align-items:stretch}}
.col{{display:flex;flex-direction:column;gap:22px;padding:30px 34px;width:100%;height:100%}}
.row{{display:flex;gap:30px;align-items:stretch}}
.card{{flex:1;border-radius:34px;padding:28px 34px;display:flex;flex-direction:column;gap:12px;min-width:0}}
.k{{font-size:{HEAD}px;font-weight:800;line-height:1.1;letter-spacing:-.01em}}
.d{{font-size:{BODY}px;line-height:1.25;color:{INK2};font-weight:600}}
.tag{{display:inline-block;font-size:{BODY}px;font-weight:800;padding:6px 30px;border-radius:999px;background:rgba(255,255,255,.78);width:max-content}}
.arrow{{font-size:{HEAD}px;font-weight:900;color:#9aa3b2;align-self:center;line-height:1}}
.chip{{flex:1;border-radius:999px;padding:14px 40px;font-size:{HEAD}px;font-weight:800;text-align:center;line-height:1.2;min-width:0;white-space:nowrap;display:flex;align-items:center;justify-content:center;gap:26px}}
.line{{font-size:{BODY}px;font-weight:700;line-height:1.3;color:{INK2};padding-left:10px}}
.line b{{color:{NAVY}}}
svg.ic{{stroke:currentColor;fill:none;stroke-width:6;stroke-linecap:round;stroke-linejoin:round}}
.badge{{position:absolute;width:{HEAD}px;height:{HEAD}px;border-radius:50%;background:{NAVY};color:#fff;font-size:{BODY}px;font-weight:900;display:flex;align-items:center;justify-content:center;border:8px solid #fff;box-shadow:0 0 0 4px {NAVY},0 6px 18px rgba(0,0,0,.3)}}
.num{{flex:none;width:{HEAD}px;height:{HEAD}px;border-radius:50%;background:{NAVY};color:#fff;font-size:{BODY}px;font-weight:900;display:flex;align-items:center;justify-content:center}}
</style>"""

LIST = []
def write(name, w, h, body):
    html = f'<!doctype html><html data-pxw="{w}" data-pxh="{h}">' + CSS.replace("body{", f"body{{width:{w}px;height:{h}px;", 1) + body + "</html>"
    open(f"{HERE}/{name}.html", "w", encoding="utf-8").write(html); LIST.append(name)

def ic(path, size=170, color=INK, vb="0 0 100 100", sw=6):
    return f'<svg class="ic" viewBox="{vb}" style="width:{size}px;height:{size}px;color:{color};stroke-width:{sw}">{path}</svg>'
I = {
 "sensor": '<rect x="14" y="22" width="72" height="56" rx="8"/><rect x="26" y="34" width="22" height="18" rx="3"/><circle cx="68" cy="43" r="7"/><path d="M26 62h48M26 70h30"/><path d="M30 22v-10M50 22v-10M70 22v-10M30 78v10M50 78v10M70 78v10"/>',
 "camera": '<rect x="10" y="30" width="80" height="52" rx="10"/><circle cx="50" cy="56" r="15"/><circle cx="50" cy="56" r="6"/><path d="M34 30l8-12h16l8 12"/><circle cx="78" cy="42" r="3"/>',
 "cloud": '<path d="M28 76h46a16 16 0 0 0 2-32 22 22 0 0 0-42-6 16 16 0 0 0-6 38z"/><path d="M38 58l12-12 12 12M50 46v26"/>',
 "hub": '<rect x="22" y="22" width="56" height="56" rx="8"/><rect x="36" y="36" width="28" height="28" rx="4"/><path d="M34 22V8M50 22V8M66 22V8M34 78v14M50 78v14M66 78v14M22 34H8M22 50H8M22 66H8M78 34h14M78 50h14M78 66h14"/>',
 "plug": '<path d="M30 42V18M70 42V18"/><rect x="18" y="42" width="64" height="26" rx="8"/><path d="M50 68v22"/><path d="M40 90h20"/>',
 "fan": '<circle cx="50" cy="50" r="7"/><path d="M50 42c1-16 8-23 18-22 4 11-2 19-12 23M58 50c16 1 23 8 22 18-11 4-19-2-23-12M50 58c-1 16-8 23-18 22-4-11 2-19 12-23M42 50c-16-1-23-8-22-18 11-4 19 2 23 12"/>',
 "purifier": '<rect x="26" y="12" width="48" height="76" rx="12"/><path d="M38 28h24M38 40h24M38 52h24"/><path d="M14 70c8-6 12 6 20 0M66 70c8-6 12 6 20 0" style="stroke-width:5"/>',
 "monitor": '<rect x="10" y="18" width="80" height="52" rx="6"/><path d="M50 70v14M34 84h32"/><path d="M22 58l12-16 10 10 14-20 10 12"/>',
 "gear": '<circle cx="50" cy="50" r="13"/><path d="M50 12v12M50 76v12M12 50h12M76 50h12M23 23l9 9M68 68l9 9M77 23l-9 9M32 68l-9 9"/>',
 "check": '<circle cx="50" cy="50" r="36"/><path d="M32 52l12 12 24-26"/>',
 "phone": '<rect x="30" y="8" width="40" height="84" rx="8"/><path d="M44 80h12"/>',
 "kiosk": '<rect x="10" y="12" width="80" height="52" rx="6"/><path d="M50 64v18M32 82h36"/><path d="M22 28h22M22 40h40M22 52h14"/><circle cx="74" cy="30" r="6"/>',
}

# ================= c1 — 시스템 구축 =================
def node(icon, color, title, lines, w=600):
    return (f'<div class="card" style="background:{color};flex:0 0 {w}px;align-items:center;text-align:center;gap:8px;padding:22px 24px;justify-content:center">'
            f'{ic(I[icon], 170)}<div class="k">{title}</div><div class="d">{lines}</div></div>')
def snode(icon, color, title, lines):
    return (f'<div class="card" style="background:{color};flex:1;flex-direction:row;align-items:center;gap:20px;padding:14px 24px;text-align:left">'
            f'{ic(I[icon], 120)}<div style="min-width:0;line-height:1.1"><div class="k">{title}</div><div class="d" style="line-height:1.2">{lines}</div></div></div>')
def arrow(label):
    return f'<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;min-width:120px;gap:6px"><div class="arrow">▶</div><div class="d" style="text-align:center;line-height:1.15">{label}</div></div>'
write("c1", 3600, 800, f"""<div class="wrap" style="gap:0;padding:26px 30px">
<div style="display:flex;flex-direction:column;gap:18px;flex:0 0 820px">
  {snode("sensor", P["blue"], "센서 노드 ×8", "UNO R4 WiFi + Grove<br>SEN55 · SCD30")}
</div>
{arrow("MQTT · TLS<br>5분 평균")}
{node("cloud", P["gray"], "브로커", "HiveMQ · 8883", 430)}
{arrow("구독")}
{node("hub", P["orange"], "허브 UNO Q", "수집·SQLite·분석·웹<br>systemd 무인 운영", 760)}
{arrow("명령 ↓ 전력 ↑")}
<div style="display:flex;flex-direction:column;gap:18px;flex:0 0 820px">
  {snode("plug", P["purple"], "플러그 ×16", "공청기 8 · 환풍기 8")}
  {snode("monitor", P["cyan"], "대시보드", "PC · 폰, 조회 전용")}
  {snode("kiosk", P["yellow"], "복도 키오스크", "1학년 복도 DID 송출")}
</div>
</div>""")

# ================= c2 — 대시보드 화면 구성 =================
badges = [("①", 4.5, 36), ("②", 4.5, 16), ("③", 40, 14), ("④", 47, 29), ("⑤", 40, 75)]
bd = "".join(f'<div class="badge" style="left:{x}%;top:{y}%">{n}</div>' for n, x, y in badges)
princ = [("①", "데이터 상태 상시 표시", "수집·노드·분석"),
         ("②", "메뉴 = 질문 순서", "지금→변화→원인→조치→비용"),
         ("③", "중요도순 배치", "상태→판정→경보"),
         ("④", "판정과 실물 나란히", "다를 때만 빨강"),
         ("⑤", "색·움직임은 정보만", "레짐 4색 고정, 가동=회전")]
pr = "".join(f'<div style="display:flex;gap:16px;align-items:center;line-height:1"><div class="num" style="width:{BODY*1.5}px;height:{BODY*1.5}px">{n}</div>'
             f'<div style="min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"><span class="k">{t}</span> <span class="d">{d}</span></div></div>' for n, t, d in princ)
nav = [("Home", "지금?", P["blue"]), ("모니터링", "변화?", P["cyan"]), ("진단·추론", "원인?", P["purple"]), ("제어·경보", "조치?", P["red"]), ("에너지", "비용?", P["green"])]
nv = '<div class="arrow">▶</div>'.join(
    f'<div style="flex:1;border-radius:999px;background:{c};padding:8px 20px;text-align:center;line-height:1.1"><div class="d" style="font-weight:800;color:{INK}">{a}</div><div class="d">{q}</div></div>' for a, q, c in nav)
write("c2", 3600, 800, f"""<div class="col" style="gap:10px;padding:16px 30px">
<div style="display:flex;gap:30px;flex:1;min-height:0">
  <div style="position:relative;flex:none;width:860px;height:538px;border-radius:22px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.25)"><img src="img/home_full.png" style="width:860px;height:538px;display:block">{bd}</div>
  <div style="flex:1;display:flex;flex-direction:column;justify-content:space-between;padding:0;min-height:0">{pr}</div>
</div>
<div style="display:flex;align-items:center;gap:14px"><div class="d" style="flex:none;font-weight:800;color:{NAVY};padding-right:10px">메뉴 =<br>질문 순서</div>{nv}
  <div class="d" style="flex:none;margin-left:14px;display:flex;align-items:center;gap:10px">{ic(I["phone"], 70, INK2)}모바일은 하단 dock,<br>같은 순서</div></div>
</div>""")

# ================= c2m — 화면 4종 =================
tiles = [("home_main.png", "Home — 상태·판정·실물·경보", P["blue"]),
         ("dx-regime_main.png", "진단 — CO₂·VOC 레짐 평면", P["purple"]),
         ("dx-action_main.png", "제어·경보 — 기준 밴드·24h", P["red"]),
         ("energy_main.png", "에너지 — 장치 전력·반별 비교", P["green"])]
tl = "".join(f'<div style="display:flex;flex-direction:column;border-radius:18px;overflow:hidden;border:5px solid {c}"><div class="d" style="background:{c};color:{INK};font-weight:800;padding:6px 16px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{t}</div><img src="img/{f}" style="width:100%;height:470px;object-fit:cover;object-position:top;display:block"></div>' for f, t, c in tiles)
write("c2m", 1500, 1230, f"""<div style="display:grid;grid-template-columns:1fr 1fr;gap:22px;padding:22px;width:100%;height:100%">{tl}</div>""")

# ================= c3 — 분석 → 모델링 → 인사이트 =================
def stage(num, title, color, body, tag=None):
    return (f'<div style="flex:1;min-width:0;border-radius:30px;background:{color};padding:18px 24px;display:flex;flex-direction:column;gap:10px">'
            f'<div style="display:flex;align-items:center;gap:18px"><div class="k">{num} {title}</div>{("<div class=tag style=margin-left:auto>" + tag + "</div>") if tag else ""}</div>{body}</div>')
cap = lambda t: f'<div class="d" style="line-height:1.22">{t}</div>'
s1 = stage("①", "패턴 분석", P["blue"],
           f'<img src="img/p_hourly.png" style="width:100%;height:360px;object-fit:contain;background:#fff;border-radius:16px">'
           + cap("두 봉우리는 주중에만 · 주중 08–16시 <b>39%</b> 초과(방학 포함)"), tag="73일 · 157,744건")
s2 = stage("②", "레짐 모델링", P["purple"],
           f'<img src="img/p_regime.png" style="width:100%;height:360px;object-fit:contain;background:#fff;border-radius:16px">'
           + cap("4개 레짐: 청정 62·인체 15·물질 15·복합 9% · 환기 회복 τ <b>42분</b>"))
def qt(c, t, s):
    return f'<div style="background:{c};border-radius:18px;padding:6px 14px;line-height:1.05;display:flex;flex-direction:column;justify-content:center"><div class="k">{t}</div><div class="d">{s}</div></div>'
s3 = stage("③", "인사이트", P["green"],
           '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;flex:1;min-height:0">'
           + qt(P["cyan"], "청정", "→ 유지") + qt(P["blue"], "인체", "→ 환풍기") + qt(P["orange"], "물질", "→ 공기청정기") + qt(P["red"], "복합", "→ 둘 다 가동")
           + '</div>' + cap("<b>1,000/700 ppm</b> · 10분 · 환풍기 <b>38 W</b> vs 공청기 7 W"))
write("c3", 3600, 800, f"""<div class="wrap" style="gap:14px;padding:16px 26px">{s1}<div class="arrow">▶</div>{s2}<div class="arrow">▶</div>{s3}</div>""")

# ================= c4 — 제어 로직 3단계 (넓고 낮은 셀) =================
write("c4", 5000, 620, f"""<div class="col" style="gap:30px;padding:30px 40px;justify-content:center">
<div class="row">
<div class="chip" style="background:{P['blue']};padding:24px 40px">{ic(I['sensor'], 120)}① 측정 → 수집</div><div class="arrow">▶</div>
<div class="chip" style="background:{P['green']};flex:1.9;padding:24px 40px">{ic(I['gear'], 120)}② 품질 검사 → 레짐 판정 → 규칙 → 목표 상태</div><div class="arrow">▶</div>
<div class="chip" style="background:{P['orange']};padding:24px 40px">{ic(I['plug'], 120)}③ 실물 비교 → 스위치</div>
</div>
<div class="row"><div class="line">• 품질 검사 미통과(유효율 95% 미만) → <b>판정 생략, 이전 상태 유지</b> · 규칙: 환풍기 1,000/700 ppm, 공기청정기 VOC 200/120, 최소 10분</div></div>
<div class="row"><div class="line">• <b>판정 모듈과 집행 모듈 분리</b> — 플러그 실제 상태와 비교해 다를 때만 명령, 한쪽이 멈춰도 오동작 없음</div></div>
</div>""")

# ================= c5 — 레짐 ↔ 대응 + 운영 수치 =================
def quad(c, title, pct, act, icon):
    return (f'<div style="background:{c};border-radius:22px;padding:14px 22px;display:flex;align-items:center;gap:18px;min-width:0">'
            f'{ic(I[icon], 120) if icon else ""}<div style="line-height:1.1;min-width:0"><div class="k">{title} <span class="d" style="font-weight:800">{pct}</span></div><div class="d" style="font-weight:800;color:{NAVY}">{act}</div></div></div>')
plane = (f'<div style="flex:0 0 1900px;display:grid;grid-template-columns:110px 1fr 1fr;grid-template-rows:1fr 1fr 110px;gap:14px;height:100%">'
         f'<div class="d" style="grid-row:1/3;writing-mode:vertical-rl;transform:rotate(180deg);font-weight:800;text-align:center">VOC(물질) ↑</div>'
         + quad(P["orange"], "물질", "15%", "→ 공기청정기", "purifier") + quad(P["red"], "복합", "9%", "→ 둘 다 가동", None)
         + quad(P["green"], "청정", "62%", "→ 유지", "check") + quad(P["blue"], "인체", "15%", "→ 환풍기", "fan")
         + f'<div></div><div class="d" style="grid-column:2/4;font-weight:800;text-align:center;align-self:center">CO₂(사람) →</div></div>')
def stat(c, n, l):
    return f'<div style="background:{c};border-radius:22px;padding:14px 24px;display:flex;flex-direction:column;justify-content:center;line-height:1.1"><div class="k">{n}</div><div class="d">{l}</div></div>'
stats = ('<div style="flex:1;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:14px">'
         + stat(P["purple"], "16대", "플러그 편입 · 15대 실가동") + stat(P["cyan"], "τ 42분", "환기 회복 시정수 중앙값")
         + stat(P["yellow"], "1,000 / 700", "ppm 히스테리시스 밴드") + stat(P["gray"], "10분", "최소 가동 · 반복 전환 방지") + '</div>')
write("c5", 3600, 850, f"""<div class="wrap" style="gap:28px;padding:24px 30px">{plane}{stats}</div>""")

print("\n".join(LIST))
