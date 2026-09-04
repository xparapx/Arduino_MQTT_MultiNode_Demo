/* multinode_aq web front end -- shared: theme, sidebar, fetch, tooltip, section chips. */
"use strict";

const AQ = (() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const num = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const dash = (v) => (v === null || v === undefined) ? "—" : v;

  // ---- theme -------------------------------------------------------------------------
  const listeners = [];
  function theme() { return document.documentElement.getAttribute("data-theme") || "dark"; }
  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("aq-theme", t); } catch (e) { /* private mode */ }
    document.querySelectorAll(".theme button").forEach((b) => b.classList.toggle("on", b.dataset.theme === t));
    listeners.forEach((fn) => fn(t));
  }
  function initTheme() {
    let t = "dark";
    try { t = localStorage.getItem("aq-theme") || "dark"; } catch (e) { /* ignore */ }
    document.documentElement.setAttribute("data-theme", t);
    document.querySelectorAll(".theme button").forEach((b) => {
      b.classList.toggle("on", b.dataset.theme === t);
      b.addEventListener("click", () => setTheme(b.dataset.theme));
    });
  }
  const onTheme = (fn) => listeners.push(fn);

  // ---- fetch -------------------------------------------------------------------------
  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  }
  function poll(fn, ms) {
    const run = () => fn().catch((e) => console.warn(e));
    run();
    return setInterval(run, ms);
  }

  // ---- tooltip (delegated: any element with data-tip) --------------------------------
  function initTip() {
    let tip = $("#tip");
    if (!tip) { tip = document.createElement("div"); tip.id = "tip"; document.body.appendChild(tip); }
    document.addEventListener("mousemove", (e) => {
      const el = e.target.closest && e.target.closest("[data-tip]");
      if (!el) { tip.style.display = "none"; return; }
      tip.innerHTML = el.getAttribute("data-tip").replace(/\n/g, "<br>");
      tip.style.display = "block";
      const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      const y = Math.min(e.clientY + 14, window.innerHeight - tip.offsetHeight - 8);
      tip.style.left = x + "px"; tip.style.top = y + "px";
    });
    document.addEventListener("mouseleave", () => { tip.style.display = "none"; });
    if (matchMedia("(hover: none)").matches) {          // touch: tap shows the tip as a toast
      document.addEventListener("click", (e) => {
        const el = e.target.closest && e.target.closest("[data-tip]");
        if (el) toast(esc(el.getAttribute("data-tip")).replace(/\n/g, "<br>"), 5000);
      });
    }
  }
  function toast(msg, ms = 4000) {
    let t = $("#toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
    t.innerHTML = msg; t.style.display = "block";
    clearTimeout(t._h); t._h = setTimeout(() => { t.style.display = "none"; }, ms);
  }

  // ---- section chip ------------------------------------------------------------------
  const ICONS = {
    radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><line x1="12" y1="12" x2="18" y2="6"/>',
    stats: '<line x1="6" y1="20" x2="6" y2="11"/><line x1="12" y1="20" x2="12" y2="5"/><line x1="18" y1="20" x2="18" y2="14"/><line x1="3" y1="20" x2="21" y2="20"/>',
    series: '<polyline points="3,17 8,10 12,14 17,6 21,9"/>',
    records: '<rect x="4" y="4" width="16" height="16" rx="2"/><line x1="4" y1="10" x2="20" y2="10"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="10" x2="10" y2="20"/>',
    export: '<line x1="12" y1="4" x2="12" y2="15"/><polyline points="7,10 12,15 17,10"/><line x1="4" y1="19" x2="20" y2="19"/>',
    reset: '<path d="M4 12a8 8 0 1 0 3-6.2"/><polyline points="4,4 4,9 9,9"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><polyline points="8,12 11,15 16,9"/>',
    plane: '<line x1="4" y1="20" x2="20" y2="20"/><line x1="4" y1="20" x2="4" y2="4"/><circle cx="10" cy="14" r="1.8"/><circle cx="16" cy="8" r="1.8"/><circle cx="8" cy="8" r="1.8"/>',
    band: '<rect x="3" y="5" width="18" height="4" rx="1"/><rect x="3" y="11" width="18" height="4" rx="1"/><rect x="3" y="17" width="18" height="4" rx="1"/>',
    transition: '<polyline points="4,7 15,7 12,4"/><polyline points="20,17 9,17 12,20"/>',
    action: '<polygon points="13,3 5,14 11,14 10,21 19,9 13,9"/>',
    forecast: '<polyline points="3,17 9,11 13,14 21,6"/><polyline points="15,6 21,6 21,12"/>',
    people: '<circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.5 2.5-6 6-6s6 2.5 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14c3 0 5 2 5 5"/>',
    explore: '<circle cx="11" cy="11" r="7"/><line x1="16" y1="16" x2="21" y2="21"/>',
    history: '<circle cx="12" cy="12" r="9"/><polyline points="12,7 12,12 16,14"/>',
    home: '<path d="M4 11l8-7 8 7"/><path d="M6 10v10h12V10"/><path d="M10 20v-6h4v6"/>',
    admin: '<line x1="5" y1="6" x2="19" y2="6"/><circle cx="10" cy="6" r="2"/><line x1="5" y1="12" x2="19" y2="12"/><circle cx="15" cy="12" r="2"/><line x1="5" y1="18" x2="19" y2="18"/><circle cx="8" cy="18" r="2"/>',
    monitor: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    diagnose: '<circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.5" y1="15.5" x2="21" y2="21"/><polyline points="7,10.5 9,10.5 10,8 11.5,13 12.5,10.5 14,10.5"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1"/>',
    pulse: '<polyline points="3,12 8,12 10,7 13,17 15,12 21,12"/>',
  };
  const secMeta = (meta) => `<div class="sec"><div class="meta">${meta || ""}</div></div>`;
  function sec(icon, color, title, meta) {
    return `<div class="sec"><div class="chip" style="--c: var(--${color})"><svg viewBox="0 0 24 24">${ICONS[icon]}</svg><h2>${esc(title)}</h2></div><div class="meta">${meta || ""}</div></div>`;
  }
  const dot = (c) => `<span class="dot" style="background:${c}"></span>`;
  const REGIME_KO = { clean: "청정", matter: "물질", human: "인체", mixed: "복합", hold: "보류" };
  const regime = (r) => r ? `<span class="regime r-${r in REGIME_KO ? r : "hold"}">${REGIME_KO[r] || r}</span>` : `<span class="chipx ex">제외</span>`;
  const chip = (t, k) => `<span class="chipx ${k || ""}">${esc(t)}</span>`;
  const actionChip = (kind, word, big) => `<span class="achip k-${kind || "hold"}${big ? " big" : ""}">${esc(word)}</span>`;
  const regimeColor = (r) => css({ clean: "--rg-clean", matter: "--rg-matter", human: "--rg-human", mixed: "--rg-mixed" }[r] || "--grid");
  function table(head, rows, cls = "") {
    const th = head.map((h) => `<th>${h}</th>`).join("");
    const body = rows.map((r) => `<tr${r.cls ? ` class="${r.cls}"` : ""}>${r.cells.map((c, i) => `<td${(i > 0 && r.txt && r.txt.includes(i)) ? ' class="txt"' : ""}>${c}</td>`).join("")}</tr>`).join("");
    return `<div class="wrap"><table class="tbl ${cls}"><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  // ---- store: shared version-gated feeds (one interval per URL, active screens only) --
  const feeds = {};
  async function pull(url) {
    const f = feeds[url];
    if (!f || !f.subs.size || f.inflight || document.hidden) return;
    f.inflight = true;
    try {
      const d = await getJSON(url);
      const changed = !f.data || f.data.version !== d.version;
      f.data = d;
      if (changed) f.subs.forEach((cb) => cb(d));
    } catch (e) { console.warn(e); } finally { f.inflight = false; }
  }
  const store = {
    sub(url, every, cb) {
      const f = feeds[url] || (feeds[url] = { subs: new Set(), data: null, timer: null, inflight: false });
      f.subs.add(cb);
      if (!f.timer) f.timer = setInterval(() => pull(url), every);
      if (f.data) cb(f.data); else pull(url);
      return () => { f.subs.delete(cb); if (!f.subs.size && f.timer) { clearInterval(f.timer); f.timer = null; } };
    },
    get: (url) => (feeds[url] || {}).data,
    prime(url) {                      // one-shot warm: fetch into the cache, no interval
      const f = feeds[url] || (feeds[url] = { subs: new Set(), data: null, timer: null, inflight: false });
      if (f.data || f.inflight || document.hidden) return;
      f.inflight = true;
      getJSON(url).then((d) => { f.data = d; f.subs.forEach((cb) => cb(d)); })
        .catch((e) => console.warn(e)).finally(() => { f.inflight = false; });
    },
    refresh(url) { const f = feeds[url]; if (f) { f.data = null; return pull(url); } },
  };
  // a tab restored from background: fetch everything subscribers are waiting for
  document.addEventListener("visibilitychange", () => { if (!document.hidden) Object.keys(feeds).forEach(pull); });

  // ---- sidebar -----------------------------------------------------------------------
  function renderSidebar(s) {
    const set = (id, html, cls) => { const el = $(id); if (!el) return; el.innerHTML = html; el.className = "v " + (cls || ""); };
    set("#st-hub", s.fresh ? "● 수집 중" : "● 수신 지연", s.fresh ? "ok" : "bad");
    set("#st-last", s.hub_last_kst ? `${s.hub_last_kst} KST` : "—");
    set("#st-env", `${s.env_active} / ${s.env_total} 활성`, s.env_active < s.env_total ? "warn" : "");
    set("#st-vis", `${s.vis_recent} / ${s.vis_total} (24h)`);
    set("#st-rows", `${num(s.readings_rows)} 행 · ${s.journal || "—"}`);
    set("#st-analyst", s.hourly_kst ? `● hourly ${s.hourly_kst}` : "○ 실행 없음", s.hourly_kst ? "ok" : "");
    set("#st-daily", `${s.daily_kst || "—"} · ${s.weekly_kst || "—"}`);
    set("#st-model", s.model || "없음");
  }
  const mode = { public: false, known: false, last: null };
  const statusFns = [];
  const onStatus = (fn) => { statusFns.push(fn); if (mode.last) fn(mode.last); };
  function initSidebar(onFirst) {
    let first = true;
    poll(async () => {
      const s = await getJSON("/api/status");
      mode.public = !!s.public;
      mode.known = true;
      mode.last = s;
      renderSidebar(s);
      statusFns.forEach((fn) => { try { fn(s); } catch (e) { console.warn(e); } });
      const foot = $(".foot");
      if (foot && s.public && !foot.dataset.pub) { foot.dataset.pub = "1"; foot.insertAdjacentHTML("afterbegin", "public · 모니터링 전용<br>"); }
      if (first) { first = false; if (onFirst) onFirst(s); }
    }, 60000);
  }

  return { $, esc, css, num, dash, theme, setTheme, initTheme, onTheme, getJSON, poll, initTip, toast, sec, secMeta, dot,
           regime, chip, actionChip, regimeColor, REGIME_KO, table, initSidebar, mode, store, onStatus, icons: ICONS };
})();
