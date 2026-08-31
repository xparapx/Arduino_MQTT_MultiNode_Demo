/* Page 1 -- monitoring: sections 1-6 from /api/live, /api/stats, /api/series, /api/export. */
"use strict";
(() => {
  const { $, esc, css, num, sec, dot, getJSON, poll, table, toast } = AQ;
  const state = { live: null, stats: null, series: null, node: null, bounds: null };
  try { state.node = localStorage.getItem("aq-node"); } catch (e) { /* ignore */ }

  // ---- section 1: radar grid --------------------------------------------------------------
  function renderLive() {
    const d = state.live;
    if (!d || !d.nodes.length) { $("#sec1").innerHTML = sec("radar", "cyan", "노드별 실시간 상태 — 레이더 (6변수 정규화)", "") + '<div class="panel empty">데이터가 아직 없습니다 — hub.py와 노드 발행을 확인하세요.</div>'; return; }
    $("#sub").textContent = `${d.nodes.length} nodes: ${d.nodes.map((n) => n.label).join(", ")} · ${num(d.rows)} rows — last seen ${d.last_seen_kst} (KST) · 온습도 대표값 SCD30 · 데이터가 바뀔 때만 다시 그림`;
    const cards = d.nodes.map((n) => `<div class="radar-card${n.down ? " down" : ""}"><div class="h">${dot(n.color)}${esc(n.label)}</div>${n.down ? `<div class="dn">${n.recv_time ? `지연 ${fmtAge(n.age_min)} · 마지막 ${esc(n.recv_time.slice(5, 16))}` : "수신 없음"}</div>` : ""}${CH.radar(n)}</div>`).join("");
    $("#sec1").innerHTML = sec("radar", "cyan", "노드별 실시간 상태 — 레이더 (6변수 정규화)", "60 s 갱신 · 이름표 숫자순 · ★ = ML 타깃")
      + `<div class="panel"><div class="radar-grid">${cards}</div></div>`;
  }
  const fmtAge = (m) => m === null ? "" : m < 90 ? `${Math.round(m)}분` : m < 48 * 60 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;

  // ---- section 2: 28-day stats ---------------------------------------------------------------
  function renderStats() {
    const d = state.stats;
    if (!d || !Object.keys(d.box).length) { $("#sec2").innerHTML = sec("stats", "orange", "전체 통계 — 최근 28일", "") + '<div class="panel empty">통계 없음</div>'; return; }
    const colors = { pm2p5: "--orange", pm10p0: "--red", scd_temp: "--yellow", scd_hum: "--blue", co2: "--cyan", voc: "--green" };
    const boxes = Object.entries(d.box).map(([k, st]) => `<div class="panel" style="padding:10px"><div class="tt" style="margin-bottom:4px;${st.target ? `color:${css(colors[k])}` : ""}">${esc(st.label)}${st.target ? " ★" : ""} <span style="opacity:.7">(${esc(st.unit)})</span></div>${CH.box(st, css(colors[k] || "--blue"))}</div>`).join("");
    const bars = (k, col, unit) => `<div class="panel"><div class="tt" style="margin-bottom:6px;color:${css(col)}">${k === "co2" ? "CO₂" : "VOC"} mean by node (${unit}) ★</div>${CH.hbars(d.by_node[k] || [], css(col), unit)}</div>`;
    $("#sec2").innerHTML = sec("stats", "orange", `전체 통계 — 최근 ${d.days}일`, `5 min 갱신 · 서버 집계본만 전송 (q1 · median · q3) · ${num(d.rows)} 행`)
      + `<div class="grid g6">${boxes}</div><div class="grid g2" style="margin-top:12px">${bars("co2", "--cyan", "ppm")}${bars("voc", "--green", "idx")}</div>`
      + '<p class="note">상관 히트맵 · CO₂-VOC 레짐 산점도(pooled / 노드별)는 <b>2) 진단</b> 페이지로 이동. 이 페이지는 "지금 상태"만.</p>';
  }

  // ---- section 3 + 4: series, vision, records ------------------------------------------------
  function renderSeries() {
    const d = state.series, live = state.live;
    if (!d) return;
    const opts = (live ? live.nodes : []).map((n) => `<option value="${esc(n.node)}"${n.node === d.node ? " selected" : ""}>${esc(n.label)} (${esc(n.node)})</option>`).join("");
    const colors = { pm2p5: "--orange", pm10p0: "--red", scd_temp: "--yellow", scd_hum: "--blue", co2: "--cyan", voc: "--green" };
    const thr = { co2: 1000, voc: 200 };
    const charts = Object.entries(d.series).map(([k, vals]) => { const m = d.metrics[k]; return `<div><div class="tt" style="${m.target ? `color:${css(colors[k])}` : ""}">${esc(m.label)} (${esc(m.unit)})${m.target ? " ★" : ""}</div>${CH.line(d.times, vals, css(colors[k]), { threshold: thr[k], unit: m.unit, target: m.target })}</div>`; }).join("");
    $("#sec3").innerHTML = sec("series", "blue", "노드별 시계열 + 재실 탐지", "60 s 갱신 · 선택 상태 유지 · 최근 60 버킷 = 5시간")
      + `<div class="panel"><div class="row" style="margin-bottom:10px"><span class="tt">노드 선택</span><select id="node-sel">${opts}</select><span class="tt">최근 ${d.times.length} 버킷</span></div>`
      + (d.times.length ? `<div class="grid g6">${charts}</div>` : '<div class="empty">이 노드의 행이 없습니다</div>')
      + `<div style="margin-top:12px">${visionPanel(d.occupancy, d.label)}</div>`
      + '<p class="note">같은 교실(라벨) 비전 노드의 재실 탐지 — 깜빡이는 조준선은 최근 버킷 최대 인원 시점의 위치, 수치는 5분 버킷 통계(평균/중앙값/최대). 영상은 전송·저장되지 않습니다(좌표만 수집).</p></div>';
    $("#node-sel").addEventListener("change", (e) => { state.node = e.target.value; try { localStorage.setItem("aq-node", state.node); } catch (er) { /* ignore */ } loadSeries(); });
    const head = ["recv_time (KST)", ...d.record_keys];
    const rows = d.records.map((r) => ({ cells: [esc(r.recv_time), ...d.record_keys.map((k) => num(r[k], ["voc", "nox", "co2"].includes(k) ? 0 : 1))] }));
    $("#sec4").innerHTML = sec("records", "blue", `최근 기록 — ${esc(d.label)}`, "60 s 갱신 · 최신 5행 · 11개 원시 변수") + `<div class="panel">${table(head, rows)}</div>`;
  }
  function visionPanel(o, label) {
    if (!o || !o.available) {
      const why = { "no occupancy table": "occupancy 테이블이 없습니다 — hub.py의 occ 구독을 확인하세요.", "no rows": "비전(재실) 데이터가 아직 없습니다.", "no vision node": `'${esc(label)}' 교실에 매핑된 비전 노드가 없습니다 — nodes.json에서 같은 라벨로 등록하세요.` };
      return `<div class="info">${why[(o || {}).reason] || "비전 데이터 없음"}</div>`;
    }
    const cross = o.cents.length ? o.cents.map((c, i) => `<div class="ch" style="left:${(c[0] / o.w * 100).toFixed(1)}%;top:${(c[1] / o.w * 100).toFixed(1)}%;animation-delay:${(i * 0.15).toFixed(2)}s"><b></b></div>`).join("") : '<div class="none">버킷 내 탐지 없음</div>';
    const chips = `<div class="chips"><div class="c2 acc"><div class="v">${num(o.occ, 1)}</div><div class="l">5분 평균</div></div><div class="c2"><div class="v">${num(o.occ_med)}</div><div class="l">중앙값</div></div><div class="c2"><div class="v">${num(o.occ_max)}</div><div class="l">최대</div></div><div class="c2"><div class="v">${num(o.n)}</div><div class="l">샘플 n</div></div></div>`;
    const vns = o.nodes || [];
    const vnodes = vns.length ? `<div class="tt" style="margin-bottom:6px">비전 노드 상태 (${vns.filter((v) => v.on).length}/${vns.length} ON)</div><div class="vnodes">${vns.map((v) => `<span class="vnc${v.on ? " on" : ""}" data-tip="${esc(v.node)} · 마지막 ${esc((v.last_kst || "—").slice(5, 16))} KST">${esc(v.room)}<i></i>${v.on ? "ON" : "OFF"}</span>`).join("")}</div>` : "";
    return `<div class="vp"><div class="hd"><span>재실 탐지 — ${esc(o.label)} <span style="color:var(--dim)">(${esc(o.vision_node)})</span></span><span class="live" style="color:${o.stale ? "var(--red)" : "var(--green)"}">${o.stale ? `지연 · 마지막 ${esc(o.recv_time.slice(5, 16))}` : "LIVE"}</span></div>`
      + `<div class="maprow"><div class="map">${cross}<span class="tag">CAMERA VIEW 4:3 · coords /${o.w}</span></div><div class="side2">${chips}${vnodes}<div class="tt" style="margin-bottom:6px">최근 버킷 추이 (평균 인원)</div><div class="bars">${CH.occBars(o.hist)}</div><div class="ft">조준선 = 최대 인원(${num(o.occ_max)}) 시점 위치 (4:3 프레임 상대좌표) · 버킷 ${esc(o.recv_time)} KST<br>영상 비전송 · 좌표만 수집 (온디바이스 추론)</div></div></div></div>`;
  }

  // ---- section 5 + 6: export, reset ----------------------------------------------------------
  function renderExport() {
    const b = state.bounds || {};
    const lo = (b.lo || "").slice(0, 10), hi = (b.hi || "").slice(0, 10);
    const hours = [...Array(24).keys()].map((h) => `<option value="${h}">${String(h).padStart(2, "0")}:00</option>`).join("");
    $("#sec5").innerHTML = sec("export", "purple", "데이터 내보내기 (CSV) — 요청 시 생성", "버튼을 누르기 전엔 쿼리 · 직렬화 없음")
      + `<div class="grid g2"><div class="panel"><div class="tt" style="margin-bottom:10px">DB = 영구 원본 · CSV = 그 순간의 사본. 준비 → 다운로드.</div>`
      + `<div class="row"><button class="btn" data-export="all">전체 readings CSV 준비</button><button class="btn" data-export="merged">env × occupancy 병합 CSV 준비</button><button class="btn" data-export="occupancy">occupancy 원본 CSV 준비</button></div><div class="row" id="export-out" style="margin-top:10px"></div></div>`
      + `<div class="panel"><div class="tt" style="margin-bottom:8px">Export by date range (KST)</div>`
      + (lo ? `<div class="row"><input type="date" id="r-sd" value="${lo}" min="${lo}" max="${hi}"><select id="r-sh">${hours}</select><span class="tt">→</span><input type="date" id="r-ed" value="${hi}" min="${lo}" max="${hi}"><select id="r-eh">${hours.replace('value="23"', 'value="23" selected')}</select></div><div class="row" style="margin-top:10px"><button class="btn" id="r-go">조회 · CSV 준비</button><span id="range-out"></span></div>`
             : '<div class="tt">데이터가 쌓이면 범위 내보내기가 가능합니다.</div>')
      + `</div></div>`;
    document.querySelectorAll("[data-export]").forEach((btn) => btn.addEventListener("click", () => prepare(btn.dataset.export, {}, $("#export-out"), btn)));
    const go = $("#r-go");
    if (go) go.addEventListener("click", () => {
      const s = `${$("#r-sd").value}T${String($("#r-sh").value).padStart(2, "0")}:00`, e = `${$("#r-ed").value}T${String($("#r-eh").value).padStart(2, "0")}:59`;
      if (s > e) { toast("시작이 끝보다 늦습니다"); return; }
      prepare("range", { start: s, end: e }, $("#range-out"), go);
    });
    $("#sec6").innerHTML = sec("reset", "red", "데이터 초기화", "CSV 자동 백업 후 readings 비우기 · hub는 멈추지 않음")
      + `<details class="panel" style="border-color:var(--chip-ex)"><summary style="cursor:pointer;color:var(--red);font-size:13px">Clear all collected data (DANGER)</summary>`
      + `<p class="note">readings 테이블을 비웁니다. hub.py는 계속 돌며 빈 테이블에 새 행을 쓰고, 삭제 전에 CSV 백업이 DB 옆에 저장됩니다. 되돌릴 수 없습니다.</p>`
      + `<div class="row" style="margin-top:8px"><label class="tt"><input type="checkbox" id="reset-ok"> I understand this cannot be undone</label><button class="btn danger" id="reset-btn" disabled>Backup + Clear table</button></div><div class="tt" id="reset-out" style="margin-top:8px"></div></details>`;
    $("#reset-ok").addEventListener("change", (e) => { $("#reset-btn").disabled = !e.target.checked; });
    $("#reset-btn").addEventListener("click", async () => {
      if (!confirm("정말로 readings를 비울까요? CSV 백업 후 삭제됩니다.")) return;
      $("#reset-btn").disabled = true;
      try {
        const r = await fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: "DELETE" }) });
        const j = await r.json();
        $("#reset-out").textContent = r.ok ? `Cleared ${num(j.rows)} rows. Backup: ${j.backup}` : `Reset failed: ${j.error}`;
        if (r.ok) { toast("초기화 완료 — 화면은 다음 갱신에 반영"); loadLive(); }
      } catch (e) { $("#reset-out").textContent = `Reset failed: ${e}`; }
    });
  }
  async function prepare(kind, params, out, btn) {
    btn.disabled = true; out.innerHTML = '<span class="tt">Preparing CSV…</span>';
    try {
      const q = new URLSearchParams({ kind, ...params });
      const r = await fetch(`/api/export?${q}`);
      if (!r.ok) throw new Error((await r.json()).error || r.status);
      const rows = r.headers.get("X-Rows"), name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || `${kind}.csv`;
      const blob = await r.blob();
      if (!Number(rows)) { out.innerHTML = '<span class="tt">No rows.</span>'; return; }
      const url = URL.createObjectURL(blob);
      out.innerHTML = `<a class="btn primary" href="${url}" download="${esc(name)}">⬇ ${esc(name)} (${(blob.size / 1048576).toFixed(1)} MB)</a><span class="tt">${num(rows)} rows · 준비 완료</span>`;
    } catch (e) { out.innerHTML = `<span class="tt" style="color:var(--red)">${esc(e.message || e)}</span>`; }
    finally { btn.disabled = false; }
  }

  // ---- loaders ------------------------------------------------------------------------------
  async function loadLive() {
    const d = await getJSON("/api/live");
    const changed = !state.live || state.live.version !== d.version;
    state.live = d;
    if (!state.node || !d.nodes.some((n) => n.node === state.node)) state.node = d.nodes.length ? d.nodes[0].node : null;
    if (changed) { renderLive(); await loadSeries(); }
  }
  async function loadSeries() {
    if (!state.node) return;
    state.series = await getJSON(`/api/series?node=${encodeURIComponent(state.node)}`);
    renderSeries();
  }
  async function loadStats() {
    const d = await getJSON("/api/stats");
    if (!state.stats || state.stats.version !== d.version) { state.stats = d; renderStats(); }
  }
  async function loadBounds() { state.bounds = await getJSON("/api/bounds"); renderExport(); }

  AQ.initTheme(); AQ.initTip();
  // sections 5 (export) and 6 (reset) exist only on the admin instance; the public
  // instance (--public) answers 403 for both, so they are not rendered at all
  AQ.initSidebar((s) => { if (!s.public) loadBounds().catch((e) => console.warn(e)); });
  AQ.onTheme(() => { renderLive(); renderStats(); renderSeries(); });
  poll(loadLive, 60000);
  poll(loadStats, 300000);
})();
