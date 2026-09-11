/* 에너지 screen -- per-room plug power: current W per device (공청기/환풍기) and a
   24 h apower bar series (5-min buckets from plugwatch). Device identity colours
   follow the action semantics: fan = --rg-human, purifier = --rg-matter. */
"use strict";
(() => {
  const { esc, css, num, secMeta, store, devChip } = AQ;
  let P = null;

  function devRow(dev, ko, d) {
    const color = css(dev === "fan" ? "--rg-human" : "--rg-matter");
    const w = d && d.online && d.apower !== null ? `${num(d.apower, 1)} W` : "—";
    return `<div class="enrow"><span style="width:9px;height:9px;border-radius:3px;background:${color};display:inline-block"></span>`
      + `<span class="tt" style="font-weight:700">${ko}</span>${devChip(d)}<span class="w" style="color:${d && d.running ? "var(--green)" : "var(--dim)"}">${w}</span></div>`
      + (d && d.hist && d.hist.length ? CH.powerBars(d.hist, dev, (P.run_w || {})[dev] || 30)
         : `<div class="empty" style="padding:14px">${d ? (d.online ? "전력 이력 수집 중…" : "플러그 미접속") : "플러그 미설치"}</div>`);
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
      + `<div class="grid g2">${cards}</div>`
      + `<p class="note">막대 = 5분 평균 유효전력(24h) · 점선 = 가동 판별 임계(공청기 ${num((P.run_w || {}).purifier)} W · 환풍기 ${num((P.run_w || {}).fan)} W) · 색 = 장치 정체성(공청기 물질 · 환풍기 인체, 제어 판단과 동일)</p>`;
  }

  AQ.router.register({
    name: "energy", group: "en", label: "전력·에너지", icon: "energy", color: "green",
    activate() { this.un = store.sub("/api/plugs", 60000, (d) => { P = d; render(this.el); }); },
    deactivate() { if (this.un) { this.un(); this.un = null; } },
    repaint() { render(this.el); },
  });
})();
