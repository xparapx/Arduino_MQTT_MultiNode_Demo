/* Home -- 일반 사용자 첫 화면: 시스템 상태 요약, 교실별 현재 레짐 · 행동 한 줄,
   경보/이상 요약, "오늘 한눈에" (analysis.summary -- API에 남아 있던 hourly 요약 부활).
   신규 엔드포인트 없음: /api/status(전역) + /api/live + /api/analysis 재조합. */
"use strict";
(() => {
  const { $, esc, num, sec, dot, regime, actionChip, chip, table, store, onStatus } = AQ;
  let A = null, L = null;

  const metric = (l, v, d, mc) => `<div class="metric${mc ? " mc" : ""}"${mc ? ` style="--mc:var(--${mc})"` : ""}><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d || ""}</div></div>`;
  const nm = (r) => `${dot(r.color)}${esc(r.label)}`;

  function statusCard() {
    const s = AQ.mode.last;
    if (!s) return sec("pulse", "cyan", "시스템 상태", "") + '<div class="panel empty">상태를 불러오는 중…</div>';
    return sec("pulse", "cyan", "시스템 상태", "60 s 갱신")
      + `<div class="panel"><div class="grid g4" style="gap:10px">`
      + metric("hub.py 수집", s.fresh ? "● 수집 중" : "● 수신 지연", s.hub_last_kst ? `마지막 수신 ${esc(s.hub_last_kst)} KST` : "수신 없음", s.fresh ? "green" : "red")
      + metric("환경 노드", `${s.env_active} / ${s.env_total} 활성`, `비전 ${s.vis_recent} / ${s.vis_total} (24h)`, "cyan")
      + metric("analyst.py", s.hourly_kst ? `hourly ${esc(s.hourly_kst)}` : "실행 없음", `daily ${esc(s.daily_kst || "—")} · weekly ${esc(s.weekly_kst || "—")}`, "blue")
      + metric("진단 모델", esc(s.model || "없음"), `readings ${num(s.readings_rows)} 행`, "purple")
      + `</div></div>`;
  }

  function roomsCard() {
    if (!A || A.empty || !A.rooms || !A.rooms.length) return sec("action", "red", "교실별 현재 레짐 · 행동", "") + '<div class="panel empty">analyst.py hourly 실행 후 표시됩니다.</div>';
    const rows = A.rooms.map((x) => ({ cls: x.judged ? "" : "dim", cells: [nm(x), regime(x.regime), actionChip(x.action.kind, x.action.word), num(x.co2), num(x.voc)] }));
    return sec("action", "red", "교실별 현재 레짐 · 행동", `hourly ${esc(A.action_run_at_kst || "—")} KST 판정`)
      + `<div class="panel">${table(["교실", "레짐", "행동", "CO₂ (ppm)", "VOC (idx)"], rows)}<p class="note">자세한 근거(히스테리시스 밴드 · 24h 추이)는 <b>진단 &amp; 추론 → 행동·경보</b>에서.</p></div>`;
  }

  function alertsCard() {
    const items = [];
    if (A && !A.empty) {
      (A.forecast || []).filter((f) => f.alert).forEach((f) => items.push(`<div class="row" style="gap:8px">${chip("경보", "warn")}<span>${nm(f)} — +${f.horizon_min}분 후 임계 초과 예상 (CO₂ ${num(f.co2_pred)} · VOC ${num(f.voc_pred)})</span></div>`));
      (A.qc || []).filter((q) => !q.passed).forEach((q) => items.push(`<div class="row" style="gap:8px">${chip("QC 제외", "ex")}<span>${nm(q)} — ${esc(q.reason || "유효율 미달")} · 판정 보류</span></div>`));
    }
    if (L) L.nodes.filter((n) => n.down).forEach((n) => items.push(`<div class="row" style="gap:8px">${chip("수신 지연", "warn")}<span>${dot(n.color)}${esc(n.label)} — ${n.recv_time ? `마지막 ${esc(n.recv_time.slice(5, 16))}` : "수신 없음"}</span></div>`));
    return sec("forecast", "orange", "경보 · 이상 요약", `${items.length ? items.length + "건" : ""}`)
      + `<div class="panel">${items.length ? `<div style="display:flex;flex-direction:column;gap:8px;font-size:13px">${items.join("")}</div>` : '<div class="empty" style="padding:12px 0">현재 경보·이상 없음 — 모든 판정 노드 정상 범위</div>'}</div>`;
  }

  function summaryCard() {
    const sm = A && !A.empty ? A.summary : null;
    if (!sm || !sm.lines || !sm.lines.length) return "";
    return sec("history", "purple", "오늘 한눈에", sm.run_at_kst ? `hourly ${esc(sm.run_at_kst)} KST` : "")
      + `<div class="panel"><div style="display:flex;flex-direction:column;gap:6px;font-size:13px">${sm.lines.map((l) => `<div>· ${esc(l)}</div>`).join("")}</div></div>`;
  }

  function render(el) {
    el.innerHTML = statusCard() + roomsCard() + alertsCard() + summaryCard();
  }

  AQ.router.register({
    name: "home", group: "home", label: "Home", icon: "home",
    activate() {
      this.unA = store.sub("/api/analysis", 60000, (d) => { A = d; render(this.el); });
      this.unL = store.sub("/api/live", 60000, (d) => { L = d; render(this.el); });
    },
    deactivate() {
      if (this.unA) { this.unA(); this.unA = null; }
      if (this.unL) { this.unL(); this.unL = null; }
    },
    repaint() { render(this.el); },
  });
  onStatus(() => {
    const c = AQ.router.current && AQ.router.current();
    if (c && c.name === "home") render(c.el);
  });
})();
