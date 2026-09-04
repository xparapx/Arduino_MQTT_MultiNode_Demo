/* Hash router + screen registry -- one shell, one visible screen at a time.
   Screens register via AQ.router.register({name, group, label, icon, admin,
   activate, deactivate, repaint}); the router builds the primary nav (sidebar)
   and the sub-tab bar from the registry, gates admin entries on AQ.mode, keeps
   per-screen scroll positions, and treats a re-tap as "scroll to top". */
"use strict";

AQ.router = (() => {
  const { $, esc } = AQ;
  const GROUPS = {
    home: { label: "Home", short: "Home", icon: "home", cls: "g-home" },
    mon: { label: "모니터링", short: "모니터", icon: "series", cls: "g-mon" },
    dx: { label: "진단 & 추론", short: "진단", icon: "plane", cls: "g-dx" },
    admin: { label: "관리", short: "관리", icon: "admin", cls: "g-admin", admin: true },
  };
  const reg = [], byName = {};
  const scroll = {};
  let current = null, curParam = null;

  function register(e) { reg.push(e); byName[e.name] = e; }
  // admin entries stay hidden until the first /api/status answer (mode.known)
  const allowed = (e) => !(e.admin && (AQ.mode.public || !AQ.mode.known));
  const groupEntries = (g) => reg.filter((e) => e.group === g && allowed(e));
  const firstOf = (g) => { const es = groupEntries(g); return es.length ? es[0].name : "home"; };

  function navHTML() {
    return Object.entries(GROUPS)
      .filter(([g, cfg]) => !(cfg.admin && (AQ.mode.public || !AQ.mode.known)) && groupEntries(g).length)
      .map(([g, cfg]) => {
        const on = current && current.group === g;
        return `<a class="${cfg.cls}${on ? " on" : ""}" href="#${firstOf(g)}" data-go="${firstOf(g)}"${on ? ' aria-current="page"' : ""}><span class="n"><svg viewBox="0 0 24 24">${AQ.icons[cfg.icon]}</svg></span>${cfg.label}</a>`;
      }).join("");
  }
  function subtabsHTML() {
    if (!current) return "";
    const es = groupEntries(current.group);
    if (es.length < 2) return "";
    return es.map((e) => `<a role="tab" data-go="${e.name}" class="${e.name === current.name ? "on" : ""}" style="--c: var(--${e.color || "cyan"})"${e.name === current.name ? ' aria-current="page"' : ""}><svg viewBox="0 0 24 24">${AQ.icons[e.icon]}</svg><span>${esc(e.label)}</span></a>`).join("");
  }
  function dockHTML() {
    return Object.entries(GROUPS)
      .filter(([g, cfg]) => !(cfg.admin && (AQ.mode.public || !AQ.mode.known)) && groupEntries(g).length)
      .map(([g, cfg]) => {
        const on = current && current.group === g;
        return `<a role="tab" class="${cfg.cls}${on ? " on" : ""}" href="#${firstOf(g)}" data-go="${firstOf(g)}"${on ? ' aria-current="page"' : ""}><svg viewBox="0 0 24 24">${AQ.icons[cfg.icon]}</svg><span>${cfg.short}</span></a>`;
      }).join("");
  }
  function renderNav() {
    const nav = $("#nav");
    if (nav) nav.innerHTML = navHTML();
    const st = $("#subtabs");
    if (st) { const h = subtabsHTML(); st.innerHTML = h; st.style.display = h ? "" : "none"; }
    const dock = $("#dock");
    if (dock) dock.innerHTML = dockHTML();
  }

  function go(name, param = null, push = true) {
    let e = byName[name];
    if (!e || !allowed(e)) { e = byName.home; param = null; }
    const same = current === e && curParam === param;
    if (current && !same) {
      scroll[current.name] = window.scrollY;
      if (current.deactivate) current.deactivate();
      current.el.classList.remove("on");
    }
    current = e; curParam = param;
    const hash = "#" + e.name + (param ? "/" + param : "");
    if (location.hash !== hash) {
      if (push) location.hash = hash; else history.replaceState(null, "", hash);
    }
    e.el.classList.add("on");
    renderNav();
    if (same) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
    if (e.activate) e.activate(param);
    window.scrollTo(0, scroll[e.name] || 0);
  }

  function onHash() {
    const h = location.hash.replace(/^#/, "");
    const i = h.indexOf("/");
    const name = i < 0 ? h : h.slice(0, i), param = i < 0 ? null : h.slice(i + 1);
    if (current && current.name === name && curParam === param) return;
    go(name || "home", param, false);
  }

  function start() {
    const main = $("main");
    reg.forEach((e) => {
      const s = document.createElement("section");
      s.className = "view"; s.dataset.screen = e.name;
      main.appendChild(s); e.el = s;
      if (e.mount) e.mount(s);
    });
    document.addEventListener("click", (ev) => {
      const a = ev.target.closest && ev.target.closest("[data-go]");
      if (!a) return;
      ev.preventDefault();
      const i = a.dataset.go.indexOf("/");
      go(i < 0 ? a.dataset.go : a.dataset.go.slice(0, i), i < 0 ? null : a.dataset.go.slice(i + 1));
    });
    addEventListener("hashchange", onHash);
    AQ.onTheme(() => { if (current && current.repaint) current.repaint(); });
    onHash();
    if (!current) go("home", null, false);
  }

  // called after the first /api/status (mode resolved) and on any mode change
  function refresh() {
    if (current && !allowed(current)) { go("home"); return; }
    renderNav();
  }

  return { register, go, start, refresh, current: () => current, param: () => curParam };
})();
