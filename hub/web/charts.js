/* SVG chart builders (strings). Colours come from the CSS tokens at call time so a
   theme switch just re-renders. Hover: any mark carries data-tip (AQ.initTip). */
"use strict";

const CH = (() => {
  const { css, esc, num } = AQ;
  const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
  const MONO = "font-family=\"'IBM Plex Mono', ui-monospace, monospace\"";
  const SANS = "font-family=\"'IBM Plex Sans KR', system-ui, sans-serif\"";

  // ---- page 1 ---------------------------------------------------------------------------
  function radar(n) {
    const cx = 110, cy = 100, R = 60, k = n.radar.length || 6;
    const pt = (j, r) => { const a = -Math.PI / 2 + j * 2 * Math.PI / k; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; };
    const grid = css("--grid"), dim = css("--dim"), ink = css("--ink"), foot = css("--foot");
    let s = '<svg class="chart" viewBox="0 0 220 200">';
    for (const f of [0.33, 0.66, 1]) s += `<polygon points="${[...Array(k)].map((_, j) => pt(j, R * f).map(f1).join(",")).join(" ")}" fill="none" stroke="${grid}"/>`;
    for (let j = 0; j < k; j++) { const [x, y] = pt(j, R); s += `<line x1="${cx}" y1="${cy}" x2="${f1(x)}" y2="${f1(y)}" stroke="${grid}"/>`; }
    if (n.radar.length && !n.radar.every((r) => r.value === null)) {
      const pts = n.radar.map((r, j) => pt(j, R * r.r));
      s += `<polygon points="${pts.map((p) => p.map(f1).join(",")).join(" ")}" fill="${n.color}" fill-opacity="0.32" stroke="${n.color}" stroke-width="2"/>`;
      n.radar.forEach((r, j) => { const [x, y] = pts[j]; s += `<circle cx="${f1(x)}" cy="${f1(y)}" r="3.5" fill="${n.color}" data-tip="${esc(r.label)} ${num(r.value, 1)} ${esc(r.unit)}"/>`; });
    }
    n.radar.forEach((r, j) => {
      const [x, y] = pt(j, R + 27);
      const v = r.value === null ? "-" : num(r.value, 1);
      s += `<text x="${f1(x)}" y="${f1(y - 4)}" font-size="9" fill="${dim}" text-anchor="middle" class="sans">${esc(r.label)}${r.target ? " ★" : ""}</text>`
         + `<text x="${f1(x)}" y="${f1(y + 7)}" font-size="10" font-weight="600" fill="${n.down ? foot : ink}" text-anchor="middle">${v} <tspan font-size="8" fill="${dim}">${esc(r.unit)}</tspan></text>`;
    });
    return s + "</svg>";
  }

  // boxen(letter-value): 중앙 50% 상자 + 75/87.5/93.75% 꼬리 세그먼트 — 이상치 점 구름 대체.
  // 핵심 변수(co2/voc)는 세그먼트 색 = 해당 컬러맵의 구간 중앙값 위치, 보조 변수는 단색 불투명도 단계.
  function box(st, key) {
    const lv = st.lv || [];
    if (!lv.length) return "";
    const outer = lv[lv.length - 1];
    let lo = outer[0], hi = outer[1];
    if (hi === lo) { hi = lo + 1; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const H = 130, T = 12, B = 6, X = 60;
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const ink = css("--ink"), dim = css("--dim");
    const core = key === "co2" || key === "voc", col = varColor(key);
    const W4 = [34, 22, 14, 8], OP = [0.8, 0.55, 0.36, 0.22], COV = [50, 75, 87.5, 93.75];
    const segFill = (a, b, i) => core
      ? `fill="rgb(${cmapAt(cmap(key), ((a + b) / 2 - lo) / (hi - lo))})" fill-opacity="0.9"`
      : `fill="${col}" fill-opacity="${OP[i]}"`;
    let s = `<svg class="chart" viewBox="0 0 100 ${H}">`;
    const seg = (a, b, i) => {
      if (!(b > a)) return;
      const w = W4[i];
      s += `<rect x="${X - w / 2}" y="${f1(y(b))}" width="${w}" height="${f1(Math.max(1, y(a) - y(b)))}" rx="1.5" ${segFill(a, b, i)} data-tip="${esc(`중앙 ${COV[i]}% 단계\n${num(a, 1)} – ${num(b, 1)}`)}"/>`;
    };
    for (let i = lv.length - 1; i >= 1; i--) { seg(lv[i][0], lv[i - 1][0], i); seg(lv[i - 1][1], lv[i][1], i); }
    seg(lv[0][0], lv[0][1], 0);
    s += `<line x1="${X - 19}" y1="${f1(y(st.median))}" x2="${X + 19}" y2="${f1(y(st.median))}" stroke="${ink}" stroke-width="2.5" data-tip="${esc(`중앙 ${num(st.median, 1)} · 평균 ${num(st.mean, 1)} · n ${num(st.n)}`)}"/>`;
    const my = y(st.median);
    for (const v of [outer[0], st.median, outer[1]]) {
      if (v !== st.median && Math.abs(y(v) - my) < 9) continue;      // don't collide with the median label
      s += `<text x="36" y="${f1(y(v) + 3)}" font-size="7" fill="${v === st.median ? ink : dim}" text-anchor="end">${num(v, Math.abs(v) < 100 ? 1 : 0)}</text>`;
    }
    if (st.beyond_n) s += `<text x="${X}" y="${T - 5}" font-size="5.5" fill="${dim}" text-anchor="middle" data-tip="바깥 단계(93.75%) 밖 ${num(st.beyond_n)}개 생략\n최대 ${num(st.out_max, 1)}">▲${num(st.beyond_n)} · max ${num(st.out_max)}</text>`;
    return s + "</svg>";
  }

  // 28-day daily trend: q1-q3 band + median line + ON-threshold reference
  function trend(dl, color, opts = {}) {
    const W = 660, H = 150, L = 46, R = 10, T = 10, B = 20;
    const n = (dl.days || []).length;
    if (!n) return `<svg class="chart" viewBox="0 0 ${W} ${H}"><text x="${W / 2}" y="${H / 2}" font-size="11" fill="${css("--dim")}" text-anchor="middle">no data</text></svg>`;
    const dim = css("--dim"), grid = css("--grid"), red = css("--red");
    let lo = Math.min(...dl.q1, opts.threshold ?? Infinity), hi = Math.max(...dl.q3, opts.threshold ?? -Infinity);
    if (hi === lo) hi = lo + 1;
    const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
    const x = (i) => L + (n === 1 ? 0 : i / (n - 1) * (W - L - R));
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
    for (const v of [lo + pad, (lo + hi) / 2, hi - pad]) s += `<line x1="${L}" y1="${f1(y(v))}" x2="${W - R}" y2="${f1(y(v))}" stroke="${grid}"/><text x="${L - 4}" y="${f1(y(v) + 3)}" font-size="9" fill="${dim}" text-anchor="end">${num(v)}</text>`;
    let band = "";
    dl.q3.forEach((v, i) => { band += `${i ? "L" : "M"}${f1(x(i))},${f1(y(v))}`; });
    for (let i = n - 1; i >= 0; i--) band += `L${f1(x(i))},${f1(y(dl.q1[i]))}`;
    s += `<path d="${band}Z" fill="${color}" opacity="0.18"/>`;
    if (opts.threshold !== undefined) s += `<line x1="${L}" y1="${f1(y(opts.threshold))}" x2="${W - R}" y2="${f1(y(opts.threshold))}" stroke="${red}" stroke-dasharray="4 3" opacity="0.8"/><text x="${W - R}" y="${f1(y(opts.threshold) - 3)}" font-size="8" fill="${red}" text-anchor="end">${num(opts.threshold)}</text>`;
    let d = "";
    dl.med.forEach((v, i) => { d += `${i ? "L" : "M"}${f1(x(i))},${f1(y(v))}`; });
    s += `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.2"${glow(color, opts.glow)}/>`;
    dl.med.forEach((v, i) => { s += `<circle cx="${f1(x(i))}" cy="${f1(y(v))}" r="2.6" fill="${color}" data-tip="${esc(dl.days[i])}\n중앙 ${num(v, 1)} ${esc(opts.unit || "")} · q1 ${num(dl.q1[i], 1)} · q3 ${num(dl.q3[i], 1)}"/>`; });
    [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i)
      .forEach((i) => { s += `<text x="${f1(x(i))}" y="${H - 6}" font-size="9" fill="${dim}" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${esc((dl.days[i] || "").slice(5))}</text>`; });
    return s + "</svg>";
  }

  // weekly comparison: one row per KST week -- q1-q3 range bar + median tick
  function weekbars(rows, thr, color, unit) {
    const dim = css("--dim"), red = css("--red"), ink = css("--ink"), grid = css("--grid");
    if (!rows || !rows.length) return `<svg class="chart" viewBox="0 0 660 60"><text x="330" y="34" font-size="11" fill="${dim}" text-anchor="middle">no data</text></svg>`;
    const L = 122, R = 54, W = 660, RH = 30, T = 8, H = T + rows.length * RH + 20;
    let lo = Math.min(...rows.map((r) => r.q1), thr ?? Infinity), hi = Math.max(...rows.map((r) => r.q3), thr ?? -Infinity);
    if (hi === lo) hi = lo + 1;
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const x = (v) => L + (v - lo) / (hi - lo) * (W - L - R);
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
    if (thr !== undefined) s += `<line x1="${f1(x(thr))}" y1="${T - 2}" x2="${f1(x(thr))}" y2="${H - 18}" stroke="${red}" stroke-dasharray="4 3" opacity="0.8"/><text x="${f1(x(thr))}" y="${H - 5}" font-size="9" fill="${red}" text-anchor="middle">${num(thr)}</text>`;
    rows.forEach((r, i) => {
      const y = T + i * RH + RH / 2;
      s += `<text x="${L - 10}" y="${y + 4}" font-size="11" fill="${ink}" text-anchor="end">${esc(r.start)}–${esc(r.end)}</text>`
         + `<line x1="${L}" y1="${y}" x2="${W - R}" y2="${y}" stroke="${grid}" stroke-width="1"/>`
         + `<rect x="${f1(x(r.q1))}" y="${y - 7}" width="${f1(Math.max(2, x(r.q3) - x(r.q1)))}" height="14" rx="4" fill="${color}" opacity="${i === rows.length - 1 ? 0.75 : 0.4}" data-tip="${esc(r.start)}–${esc(r.end)}\nq1 ${num(r.q1)} · 중앙 ${num(r.med)} · q3 ${num(r.q3)} ${esc(unit || "")}"/>`
         + `<line x1="${f1(x(r.med))}" y1="${y - 10}" x2="${f1(x(r.med))}" y2="${y + 10}" stroke="${ink}" stroke-width="2.4"/>`
         + `<text x="${f1(x(r.q3)) + 8}" y="${y + 4}" font-size="10" fill="${dim}">${num(r.med)}</text>`;
    });
    return s + "</svg>";
  }

  // day-of-week x hour rhythm: 7x24 median heatmap (rows Mon..Sun, KST)
  function dowheat(grid, thr, key, unit) {
    const DAYS = ["월", "화", "수", "목", "금", "토", "일"];
    const L = 34, T = 22, CW = 25, CH_ = 22, GAP = 2;
    const W = L + 24 * CW + 6, H = T + 7 * CH_ + 6;
    const dim = css("--dim"), red = css("--red"), plot = css("--plot");
    const vals = grid.flat().filter((v) => v !== null && v !== undefined);
    if (!vals.length) return `<svg class="chart" viewBox="0 0 ${W} ${H}"><text x="${W / 2}" y="${H / 2}" font-size="11" fill="${dim}" text-anchor="middle">no data</text></svg>`;
    const lo = Math.min(...vals), hi = Math.max(...vals);
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
    for (let h = 0; h < 24; h += 4) s += `<text x="${L + h * CW + CW / 2}" y="${T - 8}" font-size="9" fill="${dim}" text-anchor="middle">${String(h).padStart(2, "0")}</text>`;
    grid.forEach((row, di) => {
      s += `<text x="${L - 8}" y="${T + di * CH_ + CH_ / 2 + 3.5}" font-size="10" fill="${di >= 5 ? red : dim}" text-anchor="end">${DAYS[di]}</text>`;
      row.forEach((v, h) => {
        const x = L + h * CW, y = T + di * CH_;
        if (v === null || v === undefined) { s += `<rect x="${x}" y="${y}" width="${CW - GAP}" height="${CH_ - GAP}" rx="3" fill="${plot}"/>`; return; }
        const t = hi === lo ? 0.5 : (v - lo) / (hi - lo);
        const over = thr !== undefined && v > thr;
        s += `<rect x="${x}" y="${y}" width="${CW - GAP}" height="${CH_ - GAP}" rx="3" fill="rgb(${cmapAt(cmap(key), t)})" fill-opacity="0.92"${over ? ` class="hb-over" stroke="${red}" stroke-width="1.6"` : ""} data-tip="${DAYS[di]} ${String(h).padStart(2, "0")}:00–${String(h).padStart(2, "0")}:59\n중앙 ${num(v)} ${esc(unit || "")}${over ? `\n⚠ 임계 초과` : ""}"/>`;
      });
    });
    return s + "</svg>";
  }

  // per-node ON-threshold exceedance: % of rows above the rules-layer threshold
  function pbars(rows, key) {
    const ink = css("--ink"), dim = css("--dim");
    const mx = Math.max(1, ...rows.map((r) => r.pct));
    const H = 8 + rows.length * 29 + 4;
    let s = `<svg class="chart" viewBox="0 0 400 ${H}">`;
    rows.forEach((r, i) => {
      const y = 8 + i * 29, w = Math.max(1, r.pct / mx * 280);
      const t = 0.25 + 0.75 * (r.pct / mx);
      s += `<text x="72" y="${y + 14}" font-size="11" fill="${ink}" text-anchor="end">${esc(r.label)}</text>`
         + `<rect x="80" y="${y}" width="${f1(w)}" height="20" rx="3" fill="rgb(${cmapAt(cmap(key), t)})" opacity="0.9" data-tip="${esc(r.label)} 초과율 ${num(r.pct, 1)}%\n28일 중앙값 ${num(r.med, 1)}"/>`
         + `<text x="${f1(84 + w)}" y="${y + 14}" font-size="10" fill="${dim}">${num(r.pct, 1)}%</text>`;
    });
    return s + "</svg>";
  }

  function hbars(rows, color, unit) {
    const ink = css("--ink"), dim = css("--dim");
    const mx = Math.max(1, ...rows.map((r) => r.mean));
    const H = 8 + rows.length * 29 + 4;
    let s = `<svg class="chart" viewBox="0 0 400 ${H}">`;
    rows.forEach((r, i) => {
      const y = 8 + i * 29, w = r.mean / mx * 290;
      const op = 0.35 + 0.6 * (i === 0 ? 1 : (rows.length - i) / rows.length);
      s += `<text x="72" y="${y + 14}" font-size="11" fill="${ink}" text-anchor="end">${esc(r.label)}</text>`
         + `<rect x="80" y="${y}" width="${f1(w)}" height="20" rx="3" fill="${color}" opacity="${f1(op)}" data-tip="${esc(r.label)} 평균 ${num(r.mean, 1)} ${esc(unit)}"/>`
         + `<text x="${f1(84 + w)}" y="${y + 14}" font-size="10" fill="${dim}">${num(r.mean)}</text>`;
    });
    return s + "</svg>";
  }

  function line(times, values, color, opts = {}) {
    const H = opts.height || 120, L = 34, R = 6, T = 8, B = 22, W = 300;
    const vs = values.filter((v) => v !== null);
    if (!vs.length) return `<svg class="chart" viewBox="0 0 ${W} ${H}"><text x="${W / 2}" y="${H / 2}" font-size="11" fill="${css("--dim")}" text-anchor="middle">no data</text></svg>`;
    let lo = Math.min(...vs, opts.threshold ?? Infinity), hi = Math.max(...vs, opts.threshold ?? -Infinity);
    if (hi === lo) { hi = lo + 1; }
    const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
    const x = (i) => L + (values.length === 1 ? 0 : i / (values.length - 1) * (W - L - R));
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const grid = css("--grid"), dim = css("--dim"), red = css("--red");
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
    for (const v of [lo + pad, (lo + hi) / 2, hi - pad]) s += `<line x1="${L}" y1="${f1(y(v))}" x2="${W - R}" y2="${f1(y(v))}" stroke="${grid}"/><text x="${L - 4}" y="${f1(y(v) + 3)}" font-size="8" fill="${dim}" text-anchor="end">${num(v, Math.abs(v) < 100 ? 1 : 0)}</text>`;
    if (opts.threshold !== undefined) s += `<line x1="${L}" y1="${f1(y(opts.threshold))}" x2="${W - R}" y2="${f1(y(opts.threshold))}" stroke="${red}" stroke-dasharray="3 3" opacity="0.7"/>`;
    let d = "", pen = false;
    values.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? "L" : "M"}${f1(x(i))},${f1(y(v))}`; pen = true; });
    s += `<path d="${d}" fill="none" stroke="${color}" stroke-width="${opts.target ? 2.4 : 1.8}"${glow(color, opts.glow)}/>`;
    values.forEach((v, i) => { if (v === null) return; s += `<circle cx="${f1(x(i))}" cy="${f1(y(v))}" r="${opts.target ? 3 : 2.4}" fill="${color}" data-tip="${esc(times[i] || "")}\n${num(v, 1)} ${esc(opts.unit || "")}"/>`; });
    const ticks = [0, Math.floor((values.length - 1) / 2), values.length - 1].filter((v, i, a) => a.indexOf(v) === i);
    ticks.forEach((i) => { const t = (times[i] || "").slice(5, 16); s += `<text x="${f1(x(i))}" y="${H - 8}" font-size="8" fill="${dim}" text-anchor="${i === 0 ? "start" : i === values.length - 1 ? "end" : "middle"}">${esc(t)}</text>`; });
    return s + "</svg>";
  }

  function occBars(hist) {
    if (!hist || !hist.length) return "";
    const top = Math.max(1, ...hist.map((h) => h.occ_max || 0));
    return hist.map((h, i) => `<i${i === hist.length - 1 ? ' class="now"' : ""} style="height:${Math.max(3, Math.round((h.occ || 0) / top * 100))}%" data-tip="${esc(h.recv_time)}\n평균 ${num(h.occ, 1)} · 최대 ${num(h.occ_max)}"></i>`).join("");
  }

  // ---- page 2 ---------------------------------------------------------------------------
  const SLOTS = [["middle", 0, -12], ["middle", 0, 20], ["start", 12, 4], ["end", -12, 4], ["start", 10, -10], ["end", -10, 16], ["end", -10, -10], ["start", 10, 16]];
  function labelSlots(pts, near) {
    const out = [];
    pts.forEach(([x, y], i) => {
      const used = new Set();
      for (let j = 0; j < i; j++) { const [px, py] = pts[j]; if (Math.hypot(x - px, y - py) < near) used.add(out[j]); }
      out.push([...Array(SLOTS.length).keys()].find((k) => !used.has(k)) ?? 0);
    });
    return out;
  }

  function plane(rooms, cfg, meta, height = 440) {
    const Wd = 660, H = height, L = 56, R = 16, T = 18, B = 44;
    const sc = cfg.regime, ax = sc.anchor_co2_ppm / sc.co2_scale, ay = sc.anchor_voc_index / sc.voc_scale;
    const pts = rooms.filter((r) => r.co2 !== null && r.voc !== null).map((r) => ({ ...r, x: r.co2 / sc.co2_scale, y: r.voc / sc.voc_scale }));
    const comps = (meta && meta.components) || [];
    const xmax = Math.max(5, ...pts.map((p) => p.x), ...comps.map((c) => c.mu_scaled[0])) * 1.1;
    const ymax = Math.max(3, ...pts.map((p) => p.y), ...comps.map((c) => c.mu_scaled[1])) * 1.15;
    const px = (x) => L + x / xmax * (Wd - L - R), py = (y) => H - B - y / ymax * (H - T - B);
    const grid = css("--grid"), dim = css("--dim"), ink = css("--ink"), plot = css("--plot"), foot = css("--foot");
    let s = `<svg class="chart" viewBox="0 0 ${Wd} ${H}" preserveAspectRatio="xMidYMid meet" style="height:${H}px">`;
    s += `<rect x="${L}" y="${T}" width="${Wd - L - R}" height="${H - T - B}" fill="${plot}"/>`;
    for (const [k, x0, y0, x1, y1] of [["clean", 0, 0, ax, ay], ["matter", 0, ay, ax, ymax], ["human", ax, 0, xmax, ay], ["mixed", ax, ay, xmax, ymax]]) {
      s += `<rect x="${f1(px(x0))}" y="${f1(py(y1))}" width="${f1(px(x1) - px(x0))}" height="${f1(py(y0) - py(y1))}" fill="${AQ.regimeColor(k)}" opacity="0.07"/>`;
    }
    for (let i = 0; i <= Math.floor(xmax); i++) s += `<line x1="${f1(px(i))}" y1="${T}" x2="${f1(px(i))}" y2="${H - B}" stroke="${grid}"/><text x="${f1(px(i))}" y="${H - B + 16}" font-size="10" fill="${dim}" text-anchor="middle">${i}</text>`;
    for (let i = 0; i <= Math.floor(ymax); i++) s += `<line x1="${L}" y1="${f1(py(i))}" x2="${Wd - R}" y2="${f1(py(i))}" stroke="${grid}"/><text x="${L - 8}" y="${f1(py(i) + 4)}" font-size="10" fill="${dim}" text-anchor="end">${i}</text>`;
    s += `<line x1="${f1(px(ax))}" y1="${T}" x2="${f1(px(ax))}" y2="${H - B}" stroke="${dim}" stroke-dasharray="5 4"/><line x1="${L}" y1="${f1(py(ay))}" x2="${Wd - R}" y2="${f1(py(ay))}" stroke="${dim}" stroke-dasharray="5 4"/>`;
    const quads = [["clean", ax / 2, ay / 2], ["matter", ax / 2, (ay + ymax) / 2], ["human", (ax + xmax) / 2, ay / 2], ["mixed", (ax + xmax) / 2, (ay + ymax) / 2]];
    for (const [k, qx, qy] of quads) s += `<text x="${f1(px(qx))}" y="${f1(py(qy))}" font-size="12" fill="${AQ.regimeColor(k)}" opacity="0.85" text-anchor="middle" class="sans">${AQ.REGIME_KO[k]} · ${k}</text>`;
    for (const c of comps) {
      const X = px(c.mu_scaled[0]), Y = py(c.mu_scaled[1]), col = AQ.regimeColor(c.regime);
      s += `<g data-tip="${c.regime} centroid\nco2 ${num(c.mu_raw[0])} ppm · voc ${num(c.mu_raw[1])}"><line x1="${f1(X - 6)}" y1="${f1(Y - 6)}" x2="${f1(X + 6)}" y2="${f1(Y + 6)}" stroke="${col}" stroke-width="2.5"/><line x1="${f1(X - 6)}" y1="${f1(Y + 6)}" x2="${f1(X + 6)}" y2="${f1(Y - 6)}" stroke="${col}" stroke-width="2.5"/></g>`;
    }
    const slots = labelSlots(pts.map((p) => [px(p.x), py(p.y)]), 40);
    pts.forEach((p, i) => {
      const X = px(p.x), Y = py(p.y), [anc, dx, dy] = SLOTS[slots[i]];
      const star = [...Array(10).keys()].map((j) => { const r = j % 2 ? 4 : 9, a = -Math.PI / 2 + j * Math.PI / 5; return `${f1(X + r * Math.cos(a))},${f1(Y + r * Math.sin(a))}`; }).join(" ");
      const tip = `${p.label}\n${AQ.REGIME_KO[p.regime] || p.regime} · co2 ${num(p.co2)} ppm · voc ${num(p.voc)}\ndwell ${p.dwell_censored ? "≥" : ""}${num(p.dwell_min)} min`;
      s += `<polygon points="${star}" fill="${p.color}" stroke="${ink}" stroke-width="1" data-tip="${esc(tip)}"/>`
         + `<text x="${f1(X + dx)}" y="${f1(Y + dy)}" font-size="10" fill="${p.color}" text-anchor="${anc}">${esc(p.label)}</text>`;
    });
    s += `<text x="${f1((L + Wd - R) / 2)}" y="${H - 6}" font-size="11" fill="${dim}" text-anchor="middle" class="sans">CO₂ / ${sc.co2_scale}</text>`
       + `<text transform="translate(12 ${f1((T + H - B) / 2)}) rotate(-90)" font-size="11" fill="${dim}" text-anchor="middle" class="sans">VOC / ${sc.voc_scale}</text>`
       + `<text x="${Wd - R}" y="${T - 5}" font-size="10" fill="${foot}" text-anchor="end">★ 현재 (QC 통과 ${pts.length}노드) · × 모델 중심 · 점선 = 앵커 ${sc.anchor_co2_ppm} ppm / ${sc.anchor_voc_index}</text>`;
    return s + "</svg>";
  }

  function band(b) {
    const nodes = b.nodes;
    const buckets = [...new Set(nodes.flatMap((n) => n.slots.map((s) => s.bucket_kst)))].sort();
    const idx = new Map(buckets.map((k, i) => [k, i]));
    const Wd = 1100, L = 80, T = 18, rowH = 30, gap = 6, cw = (Wd - L - 10) / Math.max(1, buckets.length);
    const ink = css("--ink"), dim = css("--dim"), grid = css("--grid"), panel = css("--panel");
    const bot = T + nodes.length * (rowH + gap);
    let s = `<svg class="chart" viewBox="0 0 ${Wd} ${bot + 24}">`;
    nodes.forEach((n, ri) => {
      const y = T + ri * (rowH + gap);
      s += `<text x="${L - 10}" y="${f1(y + rowH / 2 + 4)}" font-size="11" fill="${ink}" text-anchor="end">${esc(n.label)}</text>`;
      for (const sl of n.slots) {
        const i = idx.get(sl.bucket_kst), col = sl.regime ? AQ.regimeColor(sl.regime) : grid;
        s += `<rect x="${f1(L + i * cw)}" y="${y}" width="${f1(cw + 0.4)}" height="${rowH}" fill="${col}" fill-opacity="${sl.regime ? 0.75 : 1}" data-tip="${esc(n.label)} · ${esc(sl.bucket_kst)} KST\n${sl.regime ? AQ.REGIME_KO[sl.regime] : "결측"}"/>`;
      }
    });
    buckets.forEach((k, i) => {
      if (k.slice(11) === "00:00" || i === 0) {
        const x = L + i * cw;
        s += `<line x1="${f1(x)}" y1="${T - 4}" x2="${f1(x)}" y2="${bot}" stroke="${panel}" stroke-width="2"/><text x="${f1(x + 3)}" y="${bot + 14}" font-size="10" fill="${dim}">${esc(k.slice(5, 10))}</text>`;
      }
    });
    return s + "</svg>";
  }

  function matrix(counts, regimes) {
    const L = 64, T = 40, c = 56, blue = css("--blue"), dim = css("--dim"), ink = css("--ink"), badge = css("--badge-ink"), foot = css("--foot");
    let s = '<svg class="chart" viewBox="0 0 320 300" style="max-width:320px">';
    s += `<text x="${L}" y="16" font-size="11" fill="${dim}" class="sans">→ 다음 레짐 (5분 후)</text>`;
    regimes.forEach((r, j) => { s += `<text x="${f1(L + j * c + c / 2)}" y="${T - 8}" font-size="11" fill="${AQ.regimeColor(r)}" text-anchor="middle" class="sans">${AQ.REGIME_KO[r]}</text>`; });
    regimes.forEach((a, i) => {
      const tot = regimes.reduce((acc, b) => acc + (counts[a][b] || 0), 0);
      s += `<text x="${L - 10}" y="${f1(T + i * c + c / 2 + 4)}" font-size="11" fill="${AQ.regimeColor(a)}" text-anchor="end" class="sans">${AQ.REGIME_KO[a]}</text>`;
      regimes.forEach((b, j) => {
        const v = tot ? counts[a][b] / tot : 0, dg = i === j;
        s += `<rect x="${L + j * c}" y="${T + i * c}" width="${c - 3}" height="${c - 3}" rx="4" fill="${blue}" opacity="${f1((dg ? 0.9 : Math.min(0.9, v * 14)) + 0.05)}" data-tip="${AQ.REGIME_KO[a]} → ${AQ.REGIME_KO[b]}\n${counts[a][b]} / ${tot}"/>`
           + `<text x="${f1(L + j * c + c / 2 - 1.5)}" y="${f1(T + i * c + c / 2 + 4)}" font-size="12" fill="${dg ? badge : ink}" text-anchor="middle" font-weight="${dg || v >= 0.04 ? 600 : 400}">${v.toFixed(3)}</text>`;
      });
    });
    s += `<text x="${L - 50}" y="${T + 4 * c + 22}" font-size="10" fill="${foot}" class="sans">현재 ↓ · 대각 = 지속확률</text>`;
    return s + "</svg>";
  }

  function corr(ex) {
    const vars = ex.vars, L = 44, T = 30, c = 40, dim = css("--dim"), pos = css("--corr-pos"), neg = css("--corr-neg"), cink = css("--corr-ink");
    let s = '<svg class="chart" viewBox="0 0 300 280">';
    vars.forEach((v, j) => { s += `<text x="${f1(L + j * c + c / 2)}" y="${T - 8}" font-size="9" fill="${dim}" text-anchor="middle" class="sans">${esc(v)}</text>`; });
    vars.forEach((a, i) => {
      s += `<text x="${L - 6}" y="${f1(T + i * c + c / 2 + 3)}" font-size="9" fill="${dim}" text-anchor="end" class="sans">${esc(a)}</text>`;
      vars.forEach((b, j) => {
        const v = ex.corr[a] ? ex.corr[a][b] : null;
        const f = v === null || v === undefined ? "transparent" : v > 0 ? `rgba(${pos},${f1(0.15 + 0.85 * v)})` : `rgba(${neg},${f1(0.15 + 0.85 * -v)})`;
        s += `<rect x="${L + j * c}" y="${T + i * c}" width="${c - 2}" height="${c - 2}" rx="3" fill="${f}" data-tip="${esc(a)} × ${esc(b)}\nρ ${v === null || v === undefined ? "—" : v.toFixed(2)}"/>`
           + `<text x="${f1(L + j * c + c / 2 - 1)}" y="${f1(T + i * c + c / 2 + 3)}" font-size="9" fill="${cink}" text-anchor="middle">${v === null || v === undefined ? "" : v.toFixed(2)}</text>`;
      });
    });
    return s + "</svg>";
  }

  const rc = (v, med, iqr) => (iqr && iqr > 0) ? (v - med) / iqr : 0;
  function density(d, current) {
    const Wd = 300, H = 280, L = 34, R = 8, T = 8, B = 30, amax = d.amax, bins = d.bins;
    const px = (x) => L + (x + amax) / (2 * amax) * (Wd - L - R), py = (y) => H - B - (y + amax) / (2 * amax) * (H - T - B);
    const plot = css("--plot"), ink = css("--ink"), dim = css("--dim");
    const uid = "q" + Math.random().toString(36).slice(2, 8);
    // quadrant colours: x = CO2 (human factor), y = VOC (matter factor)
    const qcol = (x, y) => AQ.regimeColor(x >= 0 ? (y >= 0 ? "mixed" : "human") : (y >= 0 ? "matter" : "clean"));
    let s = `<svg class="chart" viewBox="0 0 ${Wd} ${H}"><defs>`;
    const quads = [["clean", L, py(0), px(0) - L, H - B - py(0), px(0), py(0)], ["matter", L, T, px(0) - L, py(0) - T, px(0), py(0)],
                   ["human", px(0), py(0), Wd - R - px(0), H - B - py(0), px(0), py(0)], ["mixed", px(0), T, Wd - R - px(0), py(0) - T, px(0), py(0)]];
    for (const [k, x, y, w, h, cx, cy] of quads) {
      const fx = ((cx - x) / w) * 100, fy = ((cy - y) / h) * 100;      // gradient origin = the anchor corner
      s += `<radialGradient id="${uid}-${k}" cx="${f1(fx)}%" cy="${f1(fy)}%" r="110%"><stop offset="0%" stop-color="${AQ.regimeColor(k)}" stop-opacity="0.04"/><stop offset="100%" stop-color="${AQ.regimeColor(k)}" stop-opacity="0.22"/></radialGradient>`;
    }
    s += `</defs><rect x="${L}" y="${T}" width="${Wd - L - R}" height="${H - T - B}" fill="${plot}"/>`;
    for (const [k, x, y, w, h] of quads) s += `<rect x="${f1(x)}" y="${f1(y)}" width="${f1(w)}" height="${f1(h)}" fill="url(#${uid}-${k})"/>`;
    const cw = (Wd - L - R) / bins, ch = (H - T - B) / bins, step = 2 * amax / bins;
    const zmax = Math.max(1e-9, ...d.hist.flat());
    d.hist.forEach((col, i) => col.forEach((z, j) => {
      if (!z) return;
      const x = -amax + i * step, y = -amax + (j + 1) * step;
      s += `<rect x="${f1(px(x))}" y="${f1(py(y))}" width="${f1(cw + 0.3)}" height="${f1(ch + 0.3)}" fill="${qcol(x + step / 2, y - step / 2)}" opacity="${f1(Math.min(0.85, 0.12 + 0.75 * Math.sqrt(z / zmax)))}"/>`;
    }));
    s += `<line x1="${f1(px(0))}" y1="${T}" x2="${f1(px(0))}" y2="${H - B}" stroke="${ink}" stroke-width="1.5"/><line x1="${L}" y1="${f1(py(0))}" x2="${Wd - R}" y2="${f1(py(0))}" stroke="${ink}" stroke-width="1.5"/>`;
    for (const [x, y, t, k] of [[0.6, 0.6, "Human ≈ Matter", "mixed"], [-0.6, 0.6, "Matter > Human", "matter"], [0.6, -0.6, "Human > Matter", "human"], [-0.6, -0.6, "Clean", "clean"]]) s += `<text x="${f1(px(x * amax))}" y="${f1(py(y * amax))}" font-size="9" font-weight="600" fill="${AQ.regimeColor(k)}" text-anchor="middle" class="sans">${t}</text>`;
    for (const c of current) {
      const cx = Math.max(-amax, Math.min(amax, c.x)), cy = Math.max(-amax, Math.min(amax, c.y)), X = px(cx), Y = py(cy);
      const star = [...Array(10).keys()].map((j) => { const r = j % 2 ? 3.5 : 8, a = -Math.PI / 2 + j * Math.PI / 5; return `${f1(X + r * Math.cos(a))},${f1(Y + r * Math.sin(a))}`; }).join(" ");
      s += `<line x1="${f1(px(0))}" y1="${f1(py(0))}" x2="${f1(X)}" y2="${f1(Y)}" stroke="${c.color}" stroke-width="1.5" opacity="0.7"/><polygon points="${star}" fill="${c.color}" stroke="${ink}" stroke-width="1" data-tip="${esc(c.label)}\nco2 ${f1(c.x)} · voc ${f1(c.y)} (robust)"/><text x="${f1(X + 9)}" y="${f1(Y - 7)}" font-size="9" fill="${c.color}">${esc(c.label)}</text>`;
    }
    s += `<text x="${f1((L + Wd - R) / 2)}" y="${H - 6}" font-size="9" fill="${dim}" text-anchor="middle" class="sans">CO₂ (robust)</text><text transform="translate(10 ${f1((T + H - B) / 2)}) rotate(-90)" font-size="9" fill="${dim}" text-anchor="middle" class="sans">VOC (robust)</text>`;
    return s + "</svg>";
  }

  // ---- page 2 E: hysteresis band gauge + 24 h strip -----------------------------------
  // One value axis for both: OFF zone (< off) 25 %, band (off..on) 50 %, ON zone (> on) 25 %.
  const W_OFF = 0.25, W_BAND = 0.5;
  const bandCfg = (rules, dev) => {
    const r = rules[dev], on = dev === "fan" ? r.on_co2 : r.on_voc, off = dev === "fan" ? r.off_co2 : r.off_voc, span = on - off;
    return { on, off, lo: Math.max(0, off - span), hi: on + span, key: dev === "fan" ? "co2" : "voc", var: dev === "fan" ? "CO₂" : "VOC", unit: dev === "fan" ? "ppm" : "" };
  };
  const bandFrac = (c, v) => {
    v = Math.min(Math.max(v, c.lo), c.hi);
    if (v < c.off) return (v - c.lo) / (c.off - c.lo) * W_OFF;
    if (v <= c.on) return W_OFF + (v - c.off) / (c.on - c.off) * W_BAND;
    return W_OFF + W_BAND + (v - c.on) / (c.hi - c.on) * (1 - W_OFF - W_BAND);
  };
  const bandZone = (c, v) => v === null || v === undefined ? null : v > c.on ? "on" : v < c.off ? "off" : "band";
  const hex = (c) => c.length === 4 ? [1, 2, 3].map((i) => parseInt(c[i] + c[i], 16)) : [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const mix = (a, b, p) => "#" + hex(a).map((v, i) => Math.round(v * p + hex(b)[i] * (1 - p)).toString(16).padStart(2, "0")).join("");
  // zone fills = regime palette (off → 청정, band → 인체, on → 복합) mixed toward the panel, as app.css --zone-*
  const zoneFill = (k) => mix(css({ off: "--rg-clean", band: "--rg-human", on: "--rg-mixed" }[k]), css("--panel"), parseFloat(css("--zone-mix")) / 100);
  // plotly sequential colormaps -- 핵심 변수 값 크기: CO₂ = YlOrRd, VOC = cmocean "matter"
  const CMAPS = {
    co2: [[0, "255,255,204"], [0.125, "255,237,160"], [0.25, "254,217,118"], [0.375, "254,178,76"],
          [0.5, "253,141,60"], [0.625, "252,78,42"], [0.75, "227,26,28"], [0.875, "189,0,38"], [1, "128,0,38"]],
    voc: [[0, "253,237,176"], [0.091, "250,205,145"], [0.182, "246,173,119"], [0.273, "240,142,98"],
          [0.364, "231,109,84"], [0.455, "216,80,83"], [0.545, "195,56,90"], [0.636, "168,40,96"],
          [0.727, "138,29,99"], [0.818, "107,24,93"], [0.909, "76,21,80"], [1, "47,15,61"]],
  };
  const cmap = (key) => CMAPS[key] || CMAPS.co2;
  const cvar = (key) => `rgb(${cmapAt(cmap(key), 0.5)})`;   // 단일 색이 필요한 차트용 중앙값 색
  // 변수 대표색: 핵심 = 컬러맵 중앙값, 보조 = plotly 불연속 초이스 (붉은·주황 회피)
  const PALETTE = { pm2p5: "#636EFA", pm10p0: "#AB63FA", scd_temp: "#00CC96", scd_hum: "#19D3F3" };
  const varColor = (key, fb) => key === "co2" || key === "voc" ? cvar(key)
    : PALETTE[key] || (fb && fb.startsWith("--") ? css(fb) : fb) || css("--blue");
  // 다크 테마에서 핵심 변수 라인 가독성 보강용 네온 글로우 (라이트 테마는 무효과)
  const glow = (color, on) => on && document.documentElement.getAttribute("data-theme") !== "light" ? ` style="filter:drop-shadow(0 0 3px ${color})"` : "";
  function cmapDef(map, id, vertical, op) {
    const stops = map.map(([o, c]) => `<stop offset="${f1(o * 100)}%" stop-color="rgb(${c})" stop-opacity="${op}"/>`).join("");
    return `<linearGradient id="${id}" x1="0" y1="${vertical ? 1 : 0}" x2="${vertical ? 0 : 1}" y2="0">${stops}</linearGradient>`;
  }
  function cmapAt(map, t) {
    t = Math.min(1, Math.max(0, t));
    let i = 1;
    while (i < map.length - 1 && map[i][0] < t) i++;
    const [o0, a] = map[i - 1], [o1, b] = map[i], p = o1 === o0 ? 0 : (t - o0) / (o1 - o0);
    const u = a.split(",").map(Number), w = b.split(",").map(Number);
    return u.map((v, j) => Math.round(v + (w[j] - v) * p)).join(",");
  }
  const ZONE_KO = { off: "OFF 구간", band: "밴드", on: "ON 구간" };

  function bandGauge(c, v) {
    const W = 320, H = 14, barY = 1, barH = 12, x = (val) => bandFrac(c, val) * W;
    const uid = `jg${Math.random().toString(36).slice(2, 7)}`;
    let s = `<svg class="chart gauge" viewBox="0 0 ${W} ${H}"><defs>${cmapDef(cmap(c.key), uid, false, 0.55)}</defs>`;
    s += `<rect x="0" y="${barY}" width="${W}" height="${barH}" rx="3" fill="url(#${uid})"/>`;
    for (const t of [c.off, c.on]) s += `<line x1="${f1(x(t))}" x2="${f1(x(t))}" y1="${barY - 1}" y2="${barY + barH + 1}" stroke="${css("--panel")}" stroke-width="2" stroke-dasharray="2 2"/>`;
    if (v !== null && v !== undefined) {
      const cx = Math.min(Math.max(x(v), 5), W - 5), z = bandZone(c, v);
      s += `<g data-tip="${c.var} ${num(v)} ${c.unit} · ${ZONE_KO[z]}\n하한 ${c.off} · 상한 ${c.on}"><line x1="${f1(cx)}" x2="${f1(cx)}" y1="${barY - 1}" y2="${barY + barH + 1}" stroke="${css("--ink")}" stroke-width="2"/>`
         + `<circle cx="${f1(cx)}" cy="${barY + barH / 2}" r="4.5" fill="${css("--ink")}" stroke="${css("--panel")}" stroke-width="2"/></g>`;
    }
    return s + "</svg>";
  }

  function bandStrip(c, b, dev, devKo) {
    const data = dev === "fan" ? b.co2 : b.voc, n = data.length, hours = b.hours || 24;
    const W = 320, H = 58, top = 2, plotH = 36, trkY = top + plotH + 4, trkH = 5, axisY = H - 1;
    const ink = css("--ink"), foot = css("--foot"), grid = css("--grid"), plot = css("--plot"), panel = css("--panel");
    const y = (v) => top + plotH - bandFrac(c, v) * plotH, x = (i) => (i / (n - 1)) * W, xh = (h) => (h / hours) * W;
    const uid = `h${Math.random().toString(36).slice(2, 7)}`;
    let s = `<svg class="chart strip" viewBox="0 0 ${W} ${H}"><defs>${cmapDef(cmap(c.key), uid + "g", true, 0.32)}<pattern id="${uid}" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="${foot}" stroke-width="1"/></pattern></defs>`;
    s += `<rect x="0" y="${top}" width="${W}" height="${plotH}" fill="url(#${uid}g)"/>`;
    for (const t of [c.off, c.on]) s += `<line x1="0" x2="${W}" y1="${f1(y(t))}" y2="${f1(y(t))}" stroke="${foot}" stroke-width="1" stroke-dasharray="3 3" opacity="0.85"/>`;
    // value trace: one path per run of non-null buckets
    let d = "", pen = false;
    data.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? "L" : "M"}${f1(x(i))} ${f1(y(v))} `; pen = true; });
    if (d) s += `<path d="${d.trim()}" fill="none" stroke="${ink}" stroke-width="1.5" stroke-linejoin="round"/>`;
    // ON history track + unjudged (QC-excluded) hours
    s += `<rect x="0" y="${trkY}" width="${W}" height="${trkH}" fill="${plot}" stroke="${grid}" stroke-width="1"/>`;
    for (const [a, z] of (b.on || {})[dev] || []) s += `<rect x="${f1(xh(a))}" y="${trkY}" width="${f1(Math.max(0, xh(z) - xh(a)))}" height="${trkH}" fill="${css("--track-on")}"/>`;
    for (const [a, z] of b.unjudged || []) s += `<rect x="${f1(xh(a))}" y="${trkY}" width="${f1(Math.max(0, xh(z) - xh(a)))}" height="${trkH}" fill="url(#${uid})"/>`;
    // hourly hover columns
    const per = n / hours;
    for (let h = 0; h < hours; h++) {
      const seg = data.slice(Math.round(h * per), Math.round((h + 1) * per)).filter((v) => v !== null);
      const mean = seg.length ? seg.reduce((p, q) => p + q, 0) / seg.length : null;
      const on = ((b.on || {})[dev] || []).some(([a, z]) => h + 0.5 >= a && h + 0.5 < z);
      const unj = (b.unjudged || []).some(([a, z]) => h + 0.5 >= a && h + 0.5 < z);
      const tip = `${hours - h}h 전 ~ ${hours - h - 1}h 전 · ${c.var} ${mean === null ? "결측" : `평균 ${num(Math.round(mean))} · ${ZONE_KO[bandZone(c, mean)]}`}\n${devKo} ${on ? "ON" : "OFF"}${unj ? " · 규칙 미평가(QC)" : ""}`;
      s += `<rect x="${f1(xh(h))}" y="${top}" width="${f1(xh(1))}" height="${trkY + trkH - top}" fill="transparent" data-tip="${esc(tip)}"/>`;
    }
    for (const h of [0, 8, 16]) s += `<text x="${f1(xh(h))}" y="${axisY}" font-size="9" fill="${foot}">-${hours - h}h</text>`;
    s += `<text x="${W}" y="${axisY}" text-anchor="end" font-size="9" fill="${foot}">지금</text>`;
    let last = n - 1;
    while (last >= 0 && data[last] === null) last--;
    if (last >= 0) s += `<circle cx="${f1(x(last))}" cy="${f1(y(data[last]))}" r="4" fill="${ink}" stroke="${panel}" stroke-width="2" pointer-events="none"/>`;
    return s + "</svg>";
  }

  return { radar, box, hbars, trend, pbars, dowheat, weekbars, line, occBars, plane, band, matrix, corr, density, rc, bandCfg, bandZone, bandGauge, bandStrip, ZONE_KO, cvar, varColor };
})();
