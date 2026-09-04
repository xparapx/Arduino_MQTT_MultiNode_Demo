/* 모니터링 screens: mon-live / mon-stats / mon-series / mon-records (admin).
   Same renderers as the old page 1, split per screen; data via AQ.store
   (version-gated, active screen only). Export/reset moved to screens/admin.js. */
"use strict";
(() => {
  const { $, esc, css, num, sec, secMeta, dot, getJSON, table, store } = AQ;
  const S = { live: null, stats: null, series: null, seriesKey: null, node: null };
  try { S.node = localStorage.getItem("aq-node"); } catch (e) { /* ignore */ }

  const fmtAge = (m) => m === null ? "" : m < 90 ? `${Math.round(m)}분` : m < 48 * 60 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;

  function onLive(d) {
    S.live = d;
    if (!S.node || !d.nodes.some((n) => n.node === S.node)) S.node = d.nodes.length ? d.nodes[0].node : null;
  }
  async function loadSeries(force) {
    if (!S.node) { S.series = null; return; }
    const key = `${S.node}:${S.live ? S.live.version : 0}`;
    if (!force && S.seriesKey === key && S.series) return;
    S.series = await getJSON(`/api/series?node=${encodeURIComponent(S.node)}`);
    S.seriesKey = key;
  }

  // ---- 실시간상태: radar grid (+ 단일 class 상세: #mon-live/<node>) -------------------
  function renderLive(el, node) {
    const d = S.live;
    if (!d || !d.nodes.length) { el.innerHTML = secMeta("") + '<div class="panel empty">데이터가 아직 없습니다 — hub.py와 노드 발행을 확인하세요.</div>'; return; }
    $("#sub").textContent = `${d.nodes.length} nodes: ${d.nodes.map((n) => n.label).join(", ")} · ${num(d.rows)} rows — last seen ${d.last_seen_kst} (KST) · 온습도 대표값 SCD30 · 데이터가 바뀔 때만 다시 그림`;
    const one = node ? d.nodes.find((n) => n.node === node) : null;
    if (one) {
      el.innerHTML = sec("radar", "cyan", `실시간 상태(Radar) — ${esc(one.label)}`, "60 s 갱신 · ★ = ML 타깃")
        + `<div class="row" style="margin-bottom:10px"><a class="btn" data-go="mon-live" href="#mon-live">← 전체 레이더</a></div>`
        + `<div class="panel"><div class="radar-card one${one.down ? " down" : ""}"><div class="h">${dot(one.color)}${esc(one.label)}</div>${one.down ? `<div class="dn">${one.recv_time ? `지연 ${fmtAge(one.age_min)} · 마지막 ${esc(one.recv_time.slice(5, 16))}` : "수신 없음"}</div>` : ""}${CH.radar(one)}</div></div>`;
      return;
    }
    const cards = d.nodes.map((n) => `<div class="radar-card${n.down ? " down" : ""}" data-go="mon-live/${esc(n.node)}"><div class="h">${dot(n.color)}${esc(n.label)}</div>${n.down ? `<div class="dn">${n.recv_time ? `지연 ${fmtAge(n.age_min)} · 마지막 ${esc(n.recv_time.slice(5, 16))}` : "수신 없음"}</div>` : ""}${CH.radar(n)}</div>`).join("");
    el.innerHTML = secMeta("6변수 정규화 · 60 s 갱신 · 이름표 숫자순 · ★ = ML 타깃 · 카드 탭 = 확대")
      + `<div class="panel"><div class="radar-grid">${cards}</div></div>`;
  }

  // ---- 전체통계: 28-day stats (추세 → 초과율 순위 → 분포) ----------------------------
  function renderStats(el) {
    const d = S.stats;
    if (!d || !Object.keys(d.box).length) { el.innerHTML = secMeta("") + '<div class="panel empty">통계 없음</div>'; return; }
    const colors = { pm2p5: "--orange", pm10p0: "--red", scd_temp: "--yellow", scd_hum: "--blue", co2: "--cyan", voc: "--green" };
    const thr = d.thr || { co2: 1000, voc: 200 };
    const TITLE = { co2: "CO₂", voc: "VOC" }, UNIT = { co2: "ppm", voc: "idx" };
    let h = secMeta(`최근 ${d.days}일 · 5 min 갱신 · 서버 집계본만 전송 (q1 · median · q3) · ${num(d.rows)} 행`);
    if (d.daily) {
      const tpanel = (k, col) => `<div class="panel"><div class="tt" style="margin-bottom:6px;color:${css(col)}">${TITLE[k]} 일별 추이 ★ <span style="opacity:.7">(전 교실 중앙값 · q1–q3 밴드 · 빨간선 = ON 임계 ${num(thr[k])})</span></div>${CH.trend(d.daily[k], css(col), { threshold: thr[k], unit: UNIT[k] })}</div>`;
      h += `<div class="grid g2">${tpanel("co2", "--cyan")}${tpanel("voc", "--green")}</div>`;
      const xpanel = (k, col) => `<div class="panel"><div class="tt" style="margin-bottom:6px;color:${css(col)}">${TITLE[k]} 임계 초과율 by 교실 ★ <span style="opacity:.7">(&gt;${num(thr[k])} ${UNIT[k]} 인 시간 비율)</span></div>${CH.pbars(d.exceed[k] || [], css(col))}</div>`;
      h += `<div class="grid g2" style="margin-top:12px">${xpanel("co2", "--cyan")}${xpanel("voc", "--green")}</div>`;
    } else {
      const bars = (k, col, unit) => `<div class="panel"><div class="tt" style="margin-bottom:6px;color:${css(col)}">${TITLE[k]} mean by node (${unit}) ★</div>${CH.hbars(d.by_node[k] || [], css(col), unit)}</div>`;
      h += `<div class="grid g2">${bars("co2", "--cyan", "ppm")}${bars("voc", "--green", "idx")}</div>`;
    }
    const boxes = Object.entries(d.box).map(([k, st]) => `<div class="bx"><div class="tt" style="margin-bottom:4px;${st.target ? `color:${css(colors[k])}` : ""}">${esc(st.label)}${st.target ? " ★" : ""} <span style="opacity:.7">(${esc(st.unit)})</span></div>${CH.box(st, css(colors[k] || "--blue"))}</div>`).join("");
    el.innerHTML = h + `<div class="panel" style="margin-top:12px"><div class="tt" style="margin-bottom:8px">변수별 분포 — ${d.days}일 전체</div><div class="boxrow">${boxes}</div></div>`
      + '<p class="note">분포 박스는 p99에서 축을 자르고 생략된 극단 이상치는 ▲로 표기. 초과율 임계 = 행동지침 규칙 계층의 ON 임계와 동일. 상관 히트맵 · 레짐 산점도는 <b>진단 &amp; 추론</b>에서.</p>';
  }

  // ---- 시계열&비전 -------------------------------------------------------------------
  function renderSeries(el) {
    const d = S.series;
    if (!d) { el.innerHTML = secMeta("") + '<div class="panel empty">데이터가 아직 없습니다.</div>'; return; }
    const opts = (S.live ? S.live.nodes : []).map((n) => `<option value="${esc(n.node)}"${n.node === d.node ? " selected" : ""}>${esc(n.label)} (${esc(n.node)})</option>`).join("");
    const colors = { pm2p5: "--orange", pm10p0: "--red", scd_temp: "--yellow", scd_hum: "--blue", co2: "--cyan", voc: "--green" };
    const thr = { co2: 1000, voc: 200 };
    const charts = Object.entries(d.series).map(([k, vals]) => { const m = d.metrics[k]; return `<div><div class="tt" style="${m.target ? `color:${css(colors[k])}` : ""}">${esc(m.label)} (${esc(m.unit)})${m.target ? " ★" : ""}</div>${CH.line(d.times, vals, css(colors[k]), { threshold: thr[k], unit: m.unit, target: m.target })}</div>`; }).join("");
    el.innerHTML = secMeta("재실 탐지 포함 · 60 s 갱신 · 선택 상태 유지 · 최근 60 버킷 = 5시간")
      + `<div class="panel"><div class="row" style="margin-bottom:10px"><span class="tt">노드 선택</span><select id="node-sel">${opts}</select><span class="tt">최근 ${d.times.length} 버킷</span></div>`
      + (d.times.length ? `<div class="grid g6">${charts}</div>` : '<div class="empty">이 노드의 행이 없습니다</div>')
      + `<div style="margin-top:12px">${visionPanel(d.occupancy, d.label)}</div>`
      + '<p class="note">같은 교실(라벨) 비전 노드의 재실 탐지 — 깜빡이는 조준선은 최근 버킷 최대 인원 시점의 위치, 수치는 5분 버킷 통계(평균/중앙값/최대). 영상은 전송·저장되지 않습니다(좌표만 수집).</p></div>';
    $("#node-sel", el).addEventListener("change", async (e) => {
      S.node = e.target.value;
      try { localStorage.setItem("aq-node", S.node); } catch (er) { /* ignore */ }
      await loadSeries(true);
      renderSeries(el);
    });
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

  // ---- 최근기록 (admin) --------------------------------------------------------------
  function renderRecords(el) {
    const d = S.series;
    if (!d) { el.innerHTML = secMeta("") + '<div class="panel empty">데이터가 아직 없습니다.</div>'; return; }
    const head = ["recv_time (KST)", ...d.record_keys];
    const rows = d.records.map((r) => ({ cells: [esc(r.recv_time), ...d.record_keys.map((k) => num(r[k], ["voc", "nox", "co2"].includes(k) ? 0 : 1))] }));
    el.innerHTML = secMeta(`${esc(d.label)} · 60 s 갱신 · 최신 5행 · 11개 원시 변수`) + `<div class="panel">${table(head, rows)}</div>`;
  }

  // ---- screens -----------------------------------------------------------------------
  AQ.router.register({
    name: "mon-live", group: "mon", label: "실시간상태", icon: "radar", color: "cyan",
    activate(param) {
      this.p = param || null;
      if (this.un) this.un();
      this.un = store.sub("/api/live", 60000, (d) => { onLive(d); renderLive(this.el, this.p); });
    },
    deactivate() { if (this.un) { this.un(); this.un = null; } },
    repaint() { renderLive(this.el, this.p); },
  });
  AQ.router.register({
    name: "mon-stats", group: "mon", label: "전체통계", icon: "stats", color: "orange",
    activate() {
      if (!S.stats && !this.el.innerHTML) this.el.innerHTML = secMeta("") + '<div class="panel empty">서버 집계 계산 중…</div>';
      this.un = store.sub("/api/stats", 300000, (d) => { S.stats = d; renderStats(this.el); });
    },
    deactivate() { if (this.un) { this.un(); this.un = null; } },
    repaint() { renderStats(this.el); },
  });
  AQ.router.register({
    name: "mon-series", group: "mon", label: "시계열&비전", icon: "series", color: "blue",
    activate() { this.un = store.sub("/api/live", 60000, async (d) => { onLive(d); await loadSeries(); renderSeries(this.el); }); },
    deactivate() { if (this.un) { this.un(); this.un = null; } },
    repaint() { renderSeries(this.el); },
  });
  AQ.router.register({
    name: "mon-records", group: "mon", label: "최근기록", icon: "records", color: "green", admin: true,
    activate() { this.un = store.sub("/api/live", 60000, async (d) => { onLive(d); await loadSeries(); renderRecords(this.el); }); },
    deactivate() { if (this.un) { this.un(); this.un = null; } },
    repaint() { renderRecords(this.el); },
  });
})();
