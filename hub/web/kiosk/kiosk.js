/* Hallway display (/kiosk) -- fixed side panel + auto-rotating slides for people who
   are not domain experts. Reads only the public JSON API; adds no endpoint.

   Honesty rule: a coloured grade needs a valid reading from a hub that is fresh and
   a network that still answers. Anything doubtful is grey, and the screen is never
   blanked on an error -- the last good data stays, marked as late.

   Query: ?interval=15 (s per slide, 5-300) &slides=s1,s3 &anim=0 &fit=0 &debug=1 */
"use strict";
(() => {
  const { esc, num, regime: regimeChip, icons } = AQ;
  const $ = (id) => document.getElementById(id);
  const root = $("k-root"), main = $("k-main"), stage = $("k-stage");
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  /** Display name on the hallway screen: CLASS_03 -> 1-3 (API labels stay the join key). */
  const room = (label) => { const m = /^CLASS_0*(\d+)$/.exec(label || ""); return esc(m ? `1-${m[1]}` : label); };

  // ---- options -----------------------------------------------------------------------
  const q = new URLSearchParams(location.search);
  const intOpt = (k, d, lo, hi) => { const v = parseInt(q.get(k), 10); return Number.isFinite(v) ? clamp(v, lo, hi) : d; };
  const OPT = {
    dwell: intOpt("interval", 15, 5, 300) * 1000,
    slides: (q.get("slides") || "").toLowerCase().split(",").map((s) => s.trim()).filter(Boolean),
    anim: q.get("anim") !== "0",
    fit: q.get("fit") !== "0",
    debug: q.get("debug") === "1",
  };
  if (!OPT.anim) document.documentElement.classList.add("noanim");

  // ---- feeds: timeout, backoff, last-good data kept ----------------------------------------
  const FEEDS = { live: ["/api/live", 60], analysis: ["/api/analysis", 60], plugs: ["/api/plugs", 60],
                  stats: ["/api/stats", 300], status: ["/api/status", 60] };
  const D = {}, lastOk = {}, fails = {};
  if (q.get("debug") === "1") window.__kiosk = { D, lastOk };        // verification hook (debug only)
  const T0 = Date.now();
  async function pull(name) {
    const [url, every] = FEEDS[name];
    const ac = new AbortController(), to = setTimeout(() => ac.abort(), 10000);
    let next = every * 1000;
    try {
      const r = await fetch(url, { cache: "no-store", signal: ac.signal });
      if (!r.ok) throw new Error(`${url} ${r.status}`);
      D[name] = await r.json();
      lastOk[name] = Date.now();
      fails[name] = 0;
    } catch (e) {
      fails[name] = (fails[name] || 0) + 1;
      next = Math.min(60000, 5000 * 2 ** (fails[name] - 1));
    } finally {
      clearTimeout(to);
    }
    setTimeout(() => pull(name), next);             // reschedule first: a render error must not stop polling
    try {
      const c = renderSide();
      // first data in, or the trust state flipped (grey <-> colour): repaint now, not after the dwell
      if ((!seq.length && D.live) || (seq.length && c.colour !== painted)) { seq = []; pos = -1; kick(); }
    } catch (e) { warnOnce(e); }
  }

  const warned = new Set();
  const warnOnce = (e) => { const k = String(e); if (!warned.has(k)) { warned.add(k); console.warn("kiosk", e); } };
  /** A feed counts only while it keeps answering: 3 missed polls = no longer trusted. */
  const feedFresh = (n) => !!lastOk[n] && Date.now() - lastOk[n] < FEEDS[n][1] * 3000;

  // ---- model -------------------------------------------------------------------------------
  const GRADE_KO = { good: "좋음", mid: "보통", bad: "나쁨", none: "측정 없음" };
  function netState() {
    if (!lastOk.live) return Date.now() - T0 > 10000 ? "lost" : "loading";
    const age = (Date.now() - lastOk.live) / 1000;
    return age > 600 ? "lost" : age > 150 ? "late" : "ok";
  }
  function thresholds() {
    const r = ((D.analysis || {}).cfg || {}).rules || {}, t = (D.stats || {}).thr || {};
    const fan = r.fan || {}, pur = r.purifier || {};
    return { co2On: fan.on_co2 ?? t.co2 ?? 1000, co2Off: fan.off_co2 ?? 700,
             vocOn: pur.on_voc ?? t.voc ?? 200, vocOff: pur.off_voc ?? 120 };
  }
  /** One merged, frozen view of every feed -- a slide renders from a snapshot so
      numbers do not jump while it is on screen. */
  function snapshot() {
    const net = netState(), thr = thresholds();
    // status.fresh is the only signal that the hub itself stopped ingesting (live is memoised
    // on the newest row), so an unanswered status feed means "unknown", not "fine"
    const hubOk = !!D.status && D.status.fresh === true && feedFresh("status");
    const colour = net !== "lost" && net !== "loading" && hubOk;
    const A = D.analysis && !D.analysis.empty && feedFresh("analysis") ? D.analysis : null;
    const aBy = {}, pBy = {}, fBy = {};
    for (const x of ((A && A.rooms) || [])) aBy[x.label] = x;
    for (const x of ((D.plugs || {}).rooms || [])) pBy[x.room] = x;
    for (const x of (A ? A.forecast || [] : [])) fBy[x.label] = x;
    const rooms = ((D.live || {}).nodes || []).filter(Boolean).map((n) => {
      const v = n.values || {}, co2 = v.co2 ?? null, voc = v.voc ?? null;
      const valid = colour && !n.down && co2 !== null && co2 >= 300 && co2 <= 5000;   // 물리 범위 밖 = 센서 이상
      let grade = "none";
      if (valid) {
        grade = co2 > thr.co2On || (voc !== null && voc > thr.vocOn) ? "bad"
          : co2 >= thr.co2Off || (voc !== null && voc >= thr.vocOff) ? "mid" : "good";
      }
      // the tile shows CO2 only, so say so when the grade comes from VOC instead
      const byVoc = valid && (grade === "bad" ? co2 <= thr.co2On : grade === "mid" && co2 < thr.co2Off);
      return { label: n.label, co2, voc, valid, grade, byVoc, down: !!n.down, a: aBy[n.label] || null,
               p: pBy[n.label] || null, f: fBy[n.label] || null };
    });
    const plugsOk = !!D.plugs && feedFresh("plugs") && !D.plugs.watcher_stale && (D.plugs.rooms || []).length > 0;
    return { net, hubOk, colour, thr, rooms, A, plugs: D.plugs || null, plugsOk, status: D.status || null };
  }

  // ---- side panel ----------------------------------------------------------------------------
  const DOW = ["일", "월", "화", "수", "목", "금", "토"];
  function renderClock() {
    const d = new Date();
    $("k-clock").textContent = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    $("k-date").textContent = `${d.getMonth() + 1}월 ${d.getDate()}일 ${DOW[d.getDay()]}요일`;
    setTimeout(renderClock, 60050 - (Date.now() % 60000));
  }
  function renderSide() {
    const c = snapshot();
    $("k-list").innerHTML = c.rooms.map((r) =>
      `<div class="k-row g-${r.grade}"><span class="bar"></span><span class="nm">${room(r.label)}</span>`
      + `<span class="gw">${r.valid ? GRADE_KO[r.grade] : ""}</span>`
      + `<span class="v">${r.valid ? num(r.co2) : "—"}</span></div>`).join("");
    // freshness: network first, then the hub's own ingest health
    const s = c.status, fr = $("k-fresh");
    let col = "--green", txt = "";
    if (c.net === "loading" || !s) { col = "--dim"; txt = "연결 확인 중"; }
    else if (c.net === "lost") { col = "--red"; txt = "연결 끊김" + (lastOk.live ? ` · 마지막 ${hhmm(lastOk.live)}` : ""); }
    else if (c.net === "late") { col = "--orange"; txt = `갱신 지연 · 마지막 ${hhmm(lastOk.live)}`; }
    else if (!c.hubOk) { col = "--orange"; txt = `수신 지연 · 마지막 ${esc((s.hub_last_kst || "").slice(-5))}`; }
    else {
      const a = s && s.hub_age_min !== null && s.hub_age_min !== undefined ? Math.round(s.hub_age_min) : null;
      txt = a === null ? "측정 중" : a < 1 ? "방금 측정" : `${a}분 전 측정`;
    }
    fr.innerHTML = `<i style="--fc:var(${col})"></i>${txt}`;
    fr.classList.toggle("lost", c.net === "lost");
    document.documentElement.classList.toggle("stale", c.net === "late" || c.net === "lost" || (!!s && !c.hubOk));
    if (OPT.debug) renderDebug(c);
    return c;
  }
  const hhmm = (ms) => { const d = new Date(ms); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

  // ---- slides ----------------------------------------------------------------------------------
  const fanIcon = `<svg viewBox="0 0 24 24">${icons.fan}</svg>`;
  const rise = (i) => `class="k-rise" style="--i:${i}"`;

  const S1 = {
    id: "s1",
    ok: (c) => c.rooms.length > 0,
    title: () => "지금 교실 공기",
    key: (c) => {
      const v = c.rooms.filter((r) => r.valid);
      return v.length ? `<b>${v.filter((r) => r.grade === "good").length}</b> / ${c.rooms.length}곳 좋음` : "";
    },
    html(c) {
      const LEN = 471.2, ring = new Set(c.rooms.filter((r) => r.grade === "bad")
        .sort((a, b) => b.co2 - a.co2).slice(0, 3).map((r) => r.label));
      return `<div class="s1">` + c.rooms.map((r, i) => {
        const frac = r.valid ? clamp((r.co2 - 400) / 1600, 0.02, 1) : 0;
        const fanOn = c.plugsOk && r.p && r.p.fan && r.p.fan.running, purOn = c.plugsOk && r.p && r.p.purifier && r.p.purifier.running;
        const doing = fanOn && purOn ? "장치 2대 가동" : fanOn ? "환풍기 가동" : purOn ? "공청기 가동" : "";
        const reg = r.valid && r.a && r.a.judged && r.a.regime && r.a.regime !== "hold" ? regimeChip(r.a.regime) : "";
        return `<div class="tile g-${r.grade} k-rise${ring.has(r.label) ? " k-alert" : ""}" style="--i:${i}">`
          + `<div class="top"><span class="nm">${room(r.label)}</span><span class="gw">${GRADE_KO[r.grade]}</span></div>`
          + `<div class="gauge"><svg viewBox="0 0 236 236" aria-hidden="true"><g transform="rotate(135 118 118)" fill="none" stroke-width="16" stroke-linecap="round">`
          + `<circle class="trk" cx="118" cy="118" r="100" stroke-dasharray="${LEN} 629"/>`
          + (r.valid ? `<circle class="arc" cx="118" cy="118" r="100" stroke-dasharray="${LEN} 629" style="--len:${LEN};--off:${(LEN * (1 - frac)).toFixed(1)};--i:${i}"/>` : "")
          + `</g></svg><div><div class="num"${r.valid ? ` data-count="${Math.round(r.co2)}"` : ""}>${r.valid ? num(r.co2) : "—"}</div>`
          + `<div class="unit${r.byVoc ? " why" : ""}">${!r.valid ? "&nbsp;" : r.byVoc ? "냄새 물질 높음" : "CO₂ ppm"}</div></div></div>`
          + `<div class="foot"><span>${reg}</span><span>${doing}</span></div></div>`;
      }).join("") + `</div>`;
    },
  };

  function devChip(d) {
    if (!d) return `<span class="fanchip" style="opacity:.45">미설치</span>`;
    if (!d.online) return `<span class="fanchip">${fanIcon}미접속</span>`;
    if (d.running) return `<span class="fanchip run">${fanIcon}ON <small>${num(d.apower)} W</small></span>`;
    if (d.output) return `<span class="fanchip idle">${fanIcon}대기</span>`;
    return `<span class="fanchip off">${fanIcon}OFF</span>`;
  }
  const todayWh = (P) => {
    const e = (P || {}).energy || {}, day = (e.days || {})[e.today];
    if (!day) return null;
    let s = 0;
    for (const d of Object.values(day)) s += (d.purifier || 0) + (d.fan || 0);
    return s;
  };
  const fmtWh = (v) => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 1 : 2)} kWh` : `${Math.round(v)} Wh`);

  const S2 = {
    id: "s2",
    ok: (c) => c.plugsOk && c.colour,
    title: () => "환풍기 · 공기청정기",
    key: (c) => (c.plugs.mode === "manual" ? "수동 운전" : "자동 제어"),
    html(c) {
      const P = c.plugs, wh = todayWh(P);
      const rows = P.rooms.map((r, i) => `<div class="rw k-rise" style="--i:${i}"><span class="nm">${room(r.room)}</span>${devChip(r.fan)}${devChip(r.purifier)}</div>`).join("");
      return `<div class="s2"><div class="k-panel tbl2"><div class="hd"><span></span><span>환풍기</span><span>공기청정기</span></div>${rows}</div>`
        + `<div class="tiles"><div class="k-panel k-stat k-rise" style="--i:2"><div class="l">지금 가동 중</div>`
        + `<div class="v"><span data-count="${P.n_running}">${P.n_running}</span><small> / ${P.n_online}대</small></div>`
        + `<div class="d">${P.mode === "manual" ? "지금은 수동으로 켜고 꺼요" : "나빠지면 자동으로 켜요"}</div></div>`
        + `<div class="k-panel k-stat k-rise" style="--i:4"><div class="l">오늘 쓴 전기</div>`
        + `<div class="v">${wh === null ? "—" : fmtWh(wh).replace(/ (k?Wh)$/, "<small> $1</small>")}</div><div class="d">전체 교실 합계</div></div></div></div>`;
    },
  };

  const S3 = {
    id: "s3",
    ok: (c) => c.rooms.some((r) => r.valid),
    title: () => "교실별 CO₂",
    key: (c) => {
      const over = c.rooms.filter((r) => r.valid && r.co2 > c.thr.co2On).length;
      return over ? `기준선 넘음 <b>${over}곳</b>` : "CO₂는 모두 기준선 아래";
    },
    html(c) {
      const valid = c.rooms.filter((r) => r.valid).sort((a, b) => b.co2 - a.co2);
      const rows = [...valid, ...c.rooms.filter((r) => !r.valid)];
      const top = Math.max(1500, valid[0].co2 * 1.2), map = CH.cmap("co2");
      const body = rows.map((r, i) => {
        if (!r.valid) return `<div class="r k-rise" style="--i:${i}"><span class="nm" style="color:var(--dim)">${room(r.label)}</span><div class="trk"><span class="val" style="left:0;color:var(--dim)">측정 없음</span></div></div>`;
        const w = r.co2 / top * 100, over = r.co2 > c.thr.co2On;
        const soon = !over && r.f && r.f.co2_pred > c.thr.co2On ? `<em>↑ 곧 높아져요</em>` : "";   // CO2 예측만 (alert는 VOC도 포함)
        return `<div class="r k-rise" style="--i:${i}"><span class="nm">${room(r.label)}</span><div class="trk">`
          + `<div class="bar" style="width:${w.toFixed(2)}%;--i:${i};background:rgba(${CH.cmapAt(map, clamp((r.co2 - 400) / 1600, 0.05, 1))},0.8)"></div>`
          + `<span class="val${over ? " over" : ""}" style="left:${w.toFixed(2)}%;--i:${i}">${num(r.co2)}${soon}</span></div></div>`;
      }).join("");
      const x = c.thr.co2On / top;
      return `<div class="k-panel hb"><div class="rows">${body}`
        + `<div class="thr" style="left:calc(200px + (100% - 200px) * ${x.toFixed(4)})"><b>기준선 ${num(c.thr.co2On)} ppm</b></div></div></div>`;
    },
  };

  /** The room whose CO2 peaked highest over the 24 h window, downsampled 288 -> 96. */
  function pickDay(c) {
    let best = null;
    for (const r of c.rooms) {
      const b = r.a && r.a.band24;
      if (!b || !b.co2 || b.co2.length < 12) continue;
      const pts = [];
      for (let i = 0; i < b.co2.length; i += 3) {
        const seg = b.co2.slice(i, i + 3).filter((v) => v !== null && v >= 300 && v <= 5000);
        pts.push(seg.length ? seg.reduce((s, v) => s + v, 0) / seg.length : null);
      }
      const ok = pts.filter((v) => v !== null);
      if (ok.length < 12) continue;
      const peak = Math.max(...ok);
      if (!best || peak > best.peak) best = { label: r.label, b, pts, peak, at: pts.indexOf(peak), room: r };
    }
    return best;
  }
  function fanSpans(c, room, hours) {
    const fan = c.plugsOk && room.p && room.p.fan, runW = ((c.plugs || {}).run_w || {}).fan ?? 10;
    if (!fan || !fan.hist) return [];
    const end = Math.floor(Date.now() / 1000 / 300) * 300 + 300, start = end - hours * 3600, out = [];
    for (const [t, w] of fan.hist) {
      if (t < start || w <= runW) continue;
      const h0 = (t - start) / 3600, h1 = h0 + 300 / 3600, last = out[out.length - 1];
      if (last && h0 - last[1] < 0.01) last[1] = h1; else out.push([h0, h1]);
    }
    return out;
  }
  const S4 = {
    id: "s4",
    ok: (c) => c.colour && !!pickDay(c),
    title: (c) => `최근 24시간 CO₂ · ${room(pickDay(c).label)}`,
    key: (c) => `최고 <b>${num(pickDay(c).peak)}</b> ppm`,
    html(c) {
      const d = pickDay(c), W = 1344, H = 836, L = 96, R = 40, T = 56, B = 64, n = d.pts.length;
      const hours = d.b.hours || 24, thr = c.thr.co2On;
      const hi = Math.max(1200, Math.ceil(d.peak * 1.12 / 100) * 100), lo = 400;
      const x = (i) => L + i / (n - 1) * (W - L - R), xh = (h) => L + h / hours * (W - L - R);
      const y = (v) => T + (1 - (clamp(v, lo, hi) - lo) / (hi - lo)) * (H - T - B);
      const ink = AQ.css("--ink"), dim = AQ.css("--dim"), grid = AQ.css("--grid"), red = AQ.css("--red");
      const col = CH.cvar("co2"), fanCol = CH.devColor("fan");
      // clock labels: window end = now-ish; start_kst is "MM-DD HH:MM"
      const m = /(\d\d):(\d\d)$/.exec(d.b.start_kst || ""), startMin = m ? +m[1] * 60 + +m[2] : null;
      const clock = (h) => { const t = ((Math.round((startMin + h * 60) / 5) * 5) % 1440 + 1440) % 1440; return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.round(t % 60)).padStart(2, "0")}`; };
      let s = `<svg viewBox="0 0 ${W} ${H}"><defs><linearGradient id="k-area" x1="0" y1="0" x2="0" y2="1">`
        + `<stop offset="0" stop-color="${col}" stop-opacity="0.26"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>`;
      // fan-on spans = what the plug measured (apower above the run threshold), not the judgement
      const spans = fanSpans(c, d.room, hours);
      for (const [h0, h1] of spans) {
        s += `<rect class="fade early" x="${xh(h0).toFixed(1)}" y="${T}" width="${Math.max(3, xh(h1) - xh(h0)).toFixed(1)}" height="${H - T - B}" fill="${fanCol}" fill-opacity="0.22"/>`;
      }
      for (const v of [lo, (lo + hi) / 2, hi]) {
        s += `<line x1="${L}" y1="${y(v).toFixed(1)}" x2="${W - R}" y2="${y(v).toFixed(1)}" stroke="${grid}"/>`
          + `<text x="${L - 14}" y="${(y(v) + 9).toFixed(1)}" font-size="26" fill="${dim}" text-anchor="end">${num(v)}</text>`;
      }
      if (startMin !== null) {
        const first = Math.ceil(startMin / 180) * 180 - startMin;      // minutes to the next 3 h mark
        for (let t = first; t <= hours * 60; t += 180) {
          const h = t / 60;
          s += `<text x="${xh(h).toFixed(1)}" y="${H - 20}" font-size="26" fill="${dim}" text-anchor="middle">${clock(h).slice(0, 2)}시</text>`;
        }
      }
      s += `<line x1="${L}" y1="${y(thr).toFixed(1)}" x2="${W - R}" y2="${y(thr).toFixed(1)}" stroke="${red}" stroke-width="3" stroke-dasharray="12 8"/>`
        + `<text x="${W - R}" y="${(y(thr) - 12).toFixed(1)}" font-size="26" font-weight="600" fill="${red}" text-anchor="end">기준선</text>`;
      let path = "", area = "", open = false, x0 = 0, lastI = -1;
      d.pts.forEach((v, i) => {
        if (v === null) { if (open) { area += `L${x(lastI).toFixed(1)},${H - B}L${x0.toFixed(1)},${H - B}Z`; open = false; } return; }
        const p = `${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        if (!open) { path += `M${p}`; area += `M${p}`; x0 = x(i); open = true; } else { path += `L${p}`; area += `L${p}`; }
        lastI = i;
      });
      if (open) area += `L${x(lastI).toFixed(1)},${H - B}L${x0.toFixed(1)},${H - B}Z`;
      s += `<path class="fade" d="${area}" fill="url(#k-area)"/>`
        + `<path class="ln" pathLength="1" d="${path}" fill="none" stroke="${col}" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>`;
      const px = x(d.at), py = y(d.peak), anchor = px > W - 320 ? "end" : px < L + 200 ? "start" : "middle";
      s += `<g class="fade"><circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="10" fill="${ink}" stroke="${AQ.css("--panel")}" stroke-width="4"/>`
        + `<text x="${px.toFixed(1)}" y="${(py - 22).toFixed(1)}" font-size="32" font-weight="700" fill="${ink}" text-anchor="${anchor}">${num(d.peak)}${startMin !== null ? ` · ${clock(d.at / (n - 1) * hours)}` : ""}</text></g>`;
      if (spans.length) {
        s += `<g class="fade early"><rect x="${L + 8}" y="${T - 44}" width="28" height="28" rx="5" fill="${fanCol}" fill-opacity="0.45"/>`
          + `<text x="${L + 48}" y="${T - 20}" font-size="26" fill="${dim}">환풍기 가동</text></g>`;
      }
      return `<div class="k-panel s4">${s}</svg></div>`;
    },
  };

  /** Per-room Wh over the last `nDays` KST days (same sum as screens/energy.js). */
  function energyRows(P, nDays) {
    const e = (P || {}).energy || {}, days = e.days || {};
    if (!e.today) return [];
    const t = new Date(`${e.today}T00:00:00Z`), per = {};
    for (let i = 0; i < nDays; i++) {
      const day = days[new Date(t.getTime() - i * 86400000).toISOString().slice(0, 10)];
      if (!day) continue;
      for (const [room, d] of Object.entries(day)) {
        const p = per[room] || (per[room] = { room, p: 0, f: 0 });
        p.p += d.purifier || 0; p.f += d.fan || 0;
      }
    }
    return Object.values(per).map((r) => ({ ...r, total: r.p + r.f })).filter((r) => r.total > 0).sort((a, b) => b.total - a.total);
  }
  const S5 = {
    id: "s5",
    ok: (c) => !!c.plugs && feedFresh("plugs") && energyRows(c.plugs, 7).length > 0,
    title: (c) => {
      const e = c.plugs.energy, n = e.since ? Math.round((Date.parse(e.today) - Date.parse(e.since)) / 86400000) + 1 : 7;
      return `교실별 전기 사용 · 최근 ${clamp(n, 1, 7)}일`;
    },
    key: (c) => { const wh = c.plugsOk ? todayWh(c.plugs) : null; return wh === null ? "" : `오늘 <b>${fmtWh(wh)}</b>`; },
    html(c) {
      const rows = energyRows(c.plugs, 7), top = rows[0].total * 1.22;
      const cp = CH.devColor("purifier"), cf = CH.devColor("fan");
      const body = rows.map((r, i) => {
        const w = r.total / top * 100;
        return `<div class="r k-rise" style="--i:${i}"><span class="nm">${room(r.room)}</span><div class="trk">`
          + `<div class="bar" style="width:${w.toFixed(2)}%;--i:${i}"><span style="width:${(r.p / r.total * 100).toFixed(2)}%;background:${cp}"></span><span style="flex:1;background:${cf}"></span></div>`
          + `<span class="val" style="left:${w.toFixed(2)}%;--i:${i}">${fmtWh(r.total)}</span></div></div>`;
      }).join("");
      return `<div class="k-panel hb"><div class="rows">${body}</div>`
        + `<div class="lg"><span><i style="background:${cp}"></i>공기청정기</span><span><i style="background:${cf}"></i>환풍기</span></div></div>`;
    },
  };

  const ALL = [S1, S2, S3, S4, S5];
  const picked = ALL.filter((s) => OPT.slides.includes(s.id));
  const SLIDES = picked.length ? picked : ALL;                    // unknown ids -> everything

  // ---- rotation ----------------------------------------------------------------------------------
  let seq = [], pos = -1, timer = null, raf = 0, painted = null;   // painted = colour state of the slide on screen
  const kick = () => { clearTimeout(timer); timer = setTimeout(next, 0); };
  function buildSeq(c) {
    let list = SLIDES.filter((s) => { try { return s.ok(c); } catch (e) { return false; } });
    if (!c.colour) list = c.rooms.length ? [S1] : [];                 // doubtful data: status board only
    if (list.length > 2 && list[0].id === "s1" && c.rooms.some((r) => r.grade === "bad")) list.splice(2, 0, S1);
    return list;
  }
  function countUp(el) {
    const to = +el.dataset.count, from = Math.round(to * 0.6), t0 = performance.now(), dur = 800;
    let last = 0;
    const step = (t) => {
      if (!el.isConnected) return;
      const k = clamp((t - t0) / dur, 0, 1);
      if (t - last > 33 || k === 1) { el.textContent = num(from + (to - from) * (1 - (1 - k) ** 3)); last = t; }
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function paint(slide, c) {
    main.querySelector("#k-title h1").textContent = slide.title(c);
    main.querySelector("#k-title .k-key").innerHTML = slide.key(c) || "";
    const html = slide.html(c);                                 // build first: a throw leaves the old slide up
    stage.className = "";
    stage.dataset.sid = slide.id;
    stage.innerHTML = html;
    const prog = $("k-prog");
    prog.style.setProperty("--dwell", `${OPT.dwell}ms`);
    prog.innerHTML = seq.map((_, i) => `<span class="${i < pos ? "done" : i === pos ? "on" : ""}"><i></i></span>`).join("");
  }
  const eligible = (s, c) => { try { return (c.colour || s.id === "s1") && s.ok(c); } catch (e) { return false; } };
  function next() {
    clearTimeout(timer);
    let c;
    try { c = snapshot(); } catch (e) { warnOnce(e); timer = setTimeout(next, 3000); return; }
    if (pos + 1 >= seq.length || pos < 0 || !eligible(seq[pos + 1], c)) { seq = buildSeq(c); pos = -1; }
    if (!seq.length) {
      main.querySelector("#k-title h1").textContent = "";
      main.querySelector("#k-title .k-key").textContent = "";
      stage.innerHTML = `<div class="k-empty">${c.net === "lost" ? "연결을 확인하고 있어요" : "데이터를 불러오는 중…"}</div>`;
      $("k-prog").innerHTML = "";
      timer = setTimeout(next, 3000);
      return;
    }
    pos++;
    painted = c.colour;
    const slide = seq[pos];
    // the only eligible slide is already up: refresh it in place, no exit / entry show
    if (seq.length === 1 && stage.dataset.sid === slide.id && stage.classList.contains("go")) {
      const de = document.documentElement, had = de.classList.contains("noanim");
      de.classList.add("noanim");
      try { paint(slide, c); stage.classList.add("go"); } catch (e) { warnOnce(e); }
      void stage.offsetWidth;
      if (!had) de.classList.remove("noanim");
      timer = setTimeout(next, OPT.dwell);
      return;
    }
    const enter = () => {
      try { paint(slide, c); } catch (e) {
        warnOnce(e); main.classList.remove("out"); main.classList.add("in");
        seq = []; pos = -1; timer = setTimeout(next, 1000); return;
      }
      main.classList.remove("out");
      main.classList.add("pre");
      void stage.offsetWidth;                                   // commit the start state
      main.classList.remove("pre");
      main.classList.add("in");
      clearTimeout(raf);                                        // a timer, not rAF: must fire even when frames are throttled
      raf = setTimeout(() => {
        stage.classList.add("go");
      }, 40);
      if (OPT.anim) setTimeout(() => stage.querySelectorAll("[data-count]").forEach(countUp), 300);
      timer = setTimeout(next, OPT.dwell);
    };
    if (!OPT.anim || !stage.firstChild) { enter(); return; }
    main.classList.remove("in");
    main.classList.add("out");
    timer = setTimeout(enter, 250);
  }

  // ---- frame ---------------------------------------------------------------------------------------
  function fit() {
    if (!OPT.fit) return;
    const k = Math.min(innerWidth / 1920, innerHeight / 1080);
    root.style.transform = `translate(${((innerWidth - 1920 * k) / 2).toFixed(1)}px, ${((innerHeight - 1080 * k) / 2).toFixed(1)}px) scale(${k.toFixed(5)})`;
  }
  function renderDebug(c) {
    const el = $("k-debug");
    el.hidden = false;
    const age = (n) => (lastOk[n] ? `${Math.round((Date.now() - lastOk[n]) / 1000)}s` : "-");
    const heap = performance.memory ? ` heap ${(performance.memory.usedJSHeapSize / 1048576).toFixed(1)}MB` : "";
    el.textContent = `${seq[pos] ? seq[pos].id : "-"} ${pos + 1}/${seq.length} net=${c.net} hub=${c.hubOk} live ${age("live")} an ${age("analysis")} pl ${age("plugs")}${heap}`;
  }

  addEventListener("resize", fit);
  fit();
  renderClock();
  renderSide();
  Object.keys(FEEDS).forEach(pull);
  next();
  setInterval(() => {
    try {
      fit();                                  // some kiosk shells never deliver a resize event
      const c = renderSide();
      if (seq.length && c.colour !== painted) { seq = []; pos = -1; kick(); }
    } catch (e) { warnOnce(e); }
  }, 30000);       // freshness text and the stale state move even when no feed changes
})();
