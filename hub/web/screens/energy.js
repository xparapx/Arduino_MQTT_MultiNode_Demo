/* 에너지 screen -- per-room plug power: current W per device (공청기/환풍기) and a
   24 h apower bar series (5-min buckets from plugwatch). Bars are value-mapped on
   the device colormap (purifier = Tealgrn, fan = Blues); the row dot shows the
   colormap's deep end as the device identity colour. */
"use strict";
(() => {
  const { esc, css, num, secMeta, store, devChip } = AQ;
  let P = null;

  function devRow(dev, ko, d) {
    const color = CH.devColor(dev);                          // 컬러맵 깊은 쪽 = 장치 정체성
    // 와트값은 칩 안에만 (중복 표기 제거) — 칩은 우측 정렬, 라벨·점은 칩 폰트에 맞춤
    return `<div class="enrow"><span class="dot" style="background:${color}"></span>`
      + `<span class="tt">${ko}</span>${devChip(d)}</div>`
      + (d && d.hist && d.hist.length ? CH.powerBars(d.hist, dev, (P.run_w || {})[dev] || 30)
         : `<div class="empty" style="padding:14px">${d ? (d.online ? "전력 이력 수집 중…" : "플러그 미접속") : "플러그 미설치"}</div>`);
  }

  // ---- 반별 에너지 비교 (일간·주간·월간) --------------------------------------------
  // 데이터 = plugwatch의 일별 Wh 적산(plug_energy.json). 기간 합계를 반별 가로
  // 스택 막대(공청기+환풍기)로, 총량 내림차순 정렬 — "어느 반이 얼마나 썼나"가
  // 한 눈에 읽히는 것이 목적. 막대는 scaleX 성장 모션(전환 시 재생).
  const PERIODS = [["d", "오늘", 1], ["w", "주간 (7일)", 7], ["m", "월간 (30일)", 30]];
  let period = "d";

  const fmtWh = (v) => (v >= 10000 ? `${(v / 1000).toFixed(1)} kWh`
    : v >= 1000 ? `${(v / 1000).toFixed(2)} kWh` : `${Math.round(v)} Wh`);

  function compareData(nDays) {
    const days = (P.energy && P.energy.days) || {};
    const today = P.energy && P.energy.today;
    if (!today) return { rows: [], covered: 0 };
    const dates = [];
    const t = new Date(`${today}T00:00:00Z`);
    for (let i = 0; i < nDays; i++) {
      dates.push(new Date(t.getTime() - i * 86400000).toISOString().slice(0, 10));
    }
    const per = {};
    let covered = 0;
    for (const dt of dates) {
      const rooms = days[dt];
      if (!rooms) continue;
      covered++;
      for (const [room, devs] of Object.entries(rooms)) {
        const p = per[room] || (per[room] = { p: 0, f: 0 });
        p.p += devs.purifier || 0;
        p.f += devs.fan || 0;
      }
    }
    const rows = P.rooms.map((r) => {
      const e = per[r.room] || { p: 0, f: 0 };
      return { room: r.room, p: e.p, f: e.f, total: e.p + e.f };
    }).sort((a, b) => b.total - a.total);
    return { rows, covered };
  }

  function renderCompare() {
    const nDays = PERIODS.find(([id]) => id === period)[2];
    const { rows, covered } = compareData(nDays);
    const cp = CH.devColor("purifier"), cf = CH.devColor("fan");
    const seg = PERIODS.map(([id, ko]) =>
      `<button class="eseg${id === period ? " on" : ""}" data-period="${id}" aria-pressed="${id === period}">${ko}</button>`).join("");
    const head = `<div class="ecmp-head"><div class="tt" style="font-size:13px;font-weight:700">반별 에너지 비교</div>`
      + `<div class="esegs" role="group" aria-label="비교 기간">${seg}</div></div>`;
    if (!rows.length || !rows.some((r) => r.total > 0)) {
      return `<div class="panel ecmp">${head}<div class="empty" style="padding:20px">아직 이 기간의 적산 데이터가 없습니다 — 플러그가 접속되면 5분 단위로 쌓입니다${P.energy && P.energy.since ? ` (적산 시작 ${esc(P.energy.since)})` : ""}.</div></div>`;
    }
    const max = Math.max(...rows.map((r) => r.total));
    const bars = rows.map((r) => {
      const wTot = r.total / max * 100;
      const wP = r.total ? r.p / r.total * 100 : 0;
      const title = `${r.room} · 공청기 ${fmtWh(r.p)} + 환풍기 ${fmtWh(r.f)}`;
      return `<div class="ecmp-row" title="${esc(title)}">`
        + `<span class="ecmp-room tt">${esc(r.room)}</span>`
        + `<div class="ecmp-track"><div class="ecmp-bar" style="width:${wTot.toFixed(2)}%">`
        + `<span style="width:${wP.toFixed(2)}%;background:${cp}"></span>`
        + `<span style="flex:1;background:${cf}"></span></div></div>`
        + `<span class="ecmp-val">${r.total > 0 ? fmtWh(r.total) : "—"}</span></div>`;
    }).join("");
    const cover = nDays > 1 ? ` · 수집 ${covered}/${nDays}일` : "";
    return `<div class="panel ecmp">${head}<div class="ecmp-body">${bars}</div>`
      + `<p class="note"><span class="lg" style="background:${cp}"></span> 공청기 <span class="lg" style="background:${cf};margin-left:8px"></span> 환풍기`
      + ` · 5분 평균 전력의 일별 적산(Wh), 총량 내림차순${cover}${P.energy && P.energy.since ? ` · 적산 시작 ${esc(P.energy.since)}` : ""}</p></div>`;
  }

  function render(el) {
    if (!P) { el.innerHTML = secMeta("") + '<div class="panel empty">플러그 상태 불러오는 중…</div>'; return; }
    const meta = `plugwatch 60 s 갱신 · ${P.n_online}/${P.n_plugs} 접속 · 가동 ${P.n_running}`
      + (P.updated_kst ? ` · 마지막 ${esc(P.updated_kst)} KST` : "") + (P.watcher_stale ? " · 수집 정지" : "");
    const cards = P.rooms.map((r) =>
      `<div class="panel"><div class="tt" style="font-size:13px;font-weight:700;margin-bottom:8px">${esc(r.room)}</div>`
      + devRow("purifier", "공청기", r.purifier) + `<div style="height:10px"></div>` + devRow("fan", "환풍기", r.fan) + `</div>`).join("");
    el.innerHTML = secMeta(meta)
      + (P.watcher_stale ? '<div class="info">plugwatch 서비스가 멈췄거나 아직 설치되지 않았습니다 — 상태·이력이 최신이 아닐 수 있습니다.</div>' : "")
      + `<div class="grid g4">${cards}</div>`
      + `<p class="note">막대 = 5분 평균 유효전력(24h) · 점선 = 가동 판별 임계(공청기 ${num((P.run_w || {}).purifier)} W · 환풍기 ${num((P.run_w || {}).fan)} W) · 색 = 전력 크기(공청기 Tealgrn · 환풍기 Blues, 클수록 깊은 색)</p>`
      + renderCompare();
    el.querySelectorAll(".eseg").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.period === period) return;
      period = b.dataset.period;
      render(el);
    }));
    const cmpEl = el.querySelector(".ecmp");
    if (cmpEl) requestAnimationFrame(() => requestAnimationFrame(() => cmpEl.classList.add("grow")));
  }

  AQ.router.register({
    name: "energy", group: "en", label: "전력·에너지", icon: "energy", color: "green",
    activate() { this.un = store.sub("/api/plugs", 60000, (d) => { P = d; render(this.el); }); },
    deactivate() { if (this.un) { this.un(); this.un = null; } },
    repaint() { render(this.el); },
  });
})();
