/* 관리 (admin instance only) -- 시스템 상세, CSV 내보내기(구 sec5), 데이터
   초기화(구 sec6). public 인스턴스에서는 registry 게이트 + 서버 403 이중 차단. */
"use strict";
(() => {
  const { $, esc, num, sec, getJSON, toast, store } = AQ;
  const S = { bounds: null };

  const metric = (l, v, d) => `<div class="metric"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d || ""}</div></div>`;

  function systemCard() {
    const s = AQ.mode.last;
    if (!s) return "";
    return sec("admin", "cyan", "시스템 상세", "60 s 갱신 · /api/status")
      + `<div class="panel"><div class="grid g4" style="gap:10px">`
      + metric("readings", `${num(s.readings_rows)} 행`, `journal ${esc(s.journal || "—")}`)
      + metric("hub 수신", s.fresh ? "● 수집 중" : "● 지연", s.hub_last_kst ? `${esc(s.hub_last_kst)} KST` : "—")
      + metric("analyst 실행", s.hourly_kst ? `hourly ${esc(s.hourly_kst)}` : "없음", `daily ${esc(s.daily_kst || "—")} · weekly ${esc(s.weekly_kst || "—")}`)
      + metric("진단 모델", esc(s.model || "없음"), `환경 ${s.env_active}/${s.env_total} · 비전 ${s.vis_recent}/${s.vis_total}`)
      + `</div></div>`;
  }

  function exportCard() {
    const b = S.bounds || {};
    const lo = (b.lo || "").slice(0, 10), hi = (b.hi || "").slice(0, 10);
    const hours = [...Array(24).keys()].map((h) => `<option value="${h}">${String(h).padStart(2, "0")}:00</option>`).join("");
    return sec("export", "purple", "데이터 내보내기 (CSV) — 요청 시 생성", "버튼을 누르기 전엔 쿼리 · 직렬화 없음")
      + `<div class="grid g2"><div class="panel"><div class="tt" style="margin-bottom:10px">DB = 영구 원본 · CSV = 그 순간의 사본. 준비 → 다운로드.</div>`
      + `<div class="row"><button class="btn" data-export="all">전체 readings CSV 준비</button><button class="btn" data-export="merged">env × occupancy 병합 CSV 준비</button><button class="btn" data-export="occupancy">occupancy 원본 CSV 준비</button></div><div class="row" id="export-out" style="margin-top:10px"></div></div>`
      + `<div class="panel"><div class="tt" style="margin-bottom:8px">Export by date range (KST)</div>`
      + (lo ? `<div class="row"><input type="date" id="r-sd" value="${lo}" min="${lo}" max="${hi}"><select id="r-sh">${hours}</select><span class="tt">→</span><input type="date" id="r-ed" value="${hi}" min="${lo}" max="${hi}"><select id="r-eh">${hours.replace('value="23"', 'value="23" selected')}</select></div><div class="row" style="margin-top:10px"><button class="btn" id="r-go">조회 · CSV 준비</button><span id="range-out"></span></div>`
             : '<div class="tt">데이터가 쌓이면 범위 내보내기가 가능합니다.</div>')
      + `</div></div>`;
  }

  function resetCard() {
    return sec("reset", "red", "데이터 초기화", "CSV 자동 백업 후 readings 비우기 · hub는 멈추지 않음")
      + `<details class="panel" style="border-color:var(--chip-ex)"><summary style="cursor:pointer;color:var(--red);font-size:13px">Clear all collected data (DANGER)</summary>`
      + `<p class="note">readings 테이블을 비웁니다. hub.py는 계속 돌며 빈 테이블에 새 행을 쓰고, 삭제 전에 CSV 백업이 DB 옆에 저장됩니다. 되돌릴 수 없습니다.</p>`
      + `<div class="row" style="margin-top:8px"><label class="tt"><input type="checkbox" id="reset-ok"> I understand this cannot be undone</label><button class="btn danger" id="reset-btn" disabled>Backup + Clear table</button></div><div class="tt" id="reset-out" style="margin-top:8px"></div></details>`;
  }

  function render(el) {
    el.innerHTML = systemCard() + exportCard() + resetCard();
    el.querySelectorAll("[data-export]").forEach((btn) => btn.addEventListener("click", () => prepare(btn.dataset.export, {}, $("#export-out", el), btn)));
    const go = $("#r-go", el);
    if (go) go.addEventListener("click", () => {
      const s = `${$("#r-sd", el).value}T${String($("#r-sh", el).value).padStart(2, "0")}:00`, e = `${$("#r-ed", el).value}T${String($("#r-eh", el).value).padStart(2, "0")}:59`;
      if (s > e) { toast("시작이 끝보다 늦습니다"); return; }
      prepare("range", { start: s, end: e }, $("#range-out", el), go);
    });
    $("#reset-ok", el).addEventListener("change", (e) => { $("#reset-btn", el).disabled = !e.target.checked; });
    $("#reset-btn", el).addEventListener("click", async () => {
      if (!confirm("정말로 readings를 비울까요? CSV 백업 후 삭제됩니다.")) return;
      $("#reset-btn", el).disabled = true;
      try {
        const r = await fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: "DELETE" }) });
        const j = await r.json();
        $("#reset-out", el).textContent = r.ok ? `Cleared ${num(j.rows)} rows. Backup: ${j.backup}` : `Reset failed: ${j.error}`;
        if (r.ok) { toast("초기화 완료 — 화면은 다음 갱신에 반영"); store.refresh("/api/live"); store.refresh("/api/stats"); }
      } catch (e) { $("#reset-out", el).textContent = `Reset failed: ${e}`; }
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

  AQ.router.register({
    name: "admin", group: "admin", label: "관리", icon: "admin", admin: true,
    activate() {
      const el = this.el;
      render(el);
      if (!S.bounds) getJSON("/api/bounds").then((b) => { S.bounds = b; render(el); }).catch((e) => console.warn(e));
    },
    repaint() { render(this.el); },
  });
})();
