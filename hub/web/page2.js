/* Page 2 -- diagnosis: everything from one /api/analysis bundle (analysis table only). */
"use strict";
(() => {
  const { $, esc, css, num, dash, sec, dot, regime, chip, actionChip, getJSON, poll, table } = AQ;
  let A = null, within = null;
  const pct = (v) => v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;
  const kstRange = (w) => w ? `${w.start.slice(5, 10)} → ${w.end.slice(5, 10)}` : "—";
  const actionColor = { fan: "--rg-human", purifier: "--rg-matter", both: "--rg-mixed", none: "--rg-clean", hold: "--grid" };

  function metric(l, v, d) { return `<div class="metric"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d || ""}</div></div>`; }
  const nm = (r) => `${dot(r.color)}${esc(r.label)}`;

  function render() {
    if (!A) return;
    if (A.empty) {
      $("#page2").innerHTML = `<div class="panel"><div class="empty">아직 분석 결과가 없습니다 — analyst.py의 hourly / daily 타이머가 처음 실행되면 A~I 절이 나타납니다.<br><span class="mono">analyst.py run --mode hourly</span></div></div>`;
      return;
    }
    const cfg = A.cfg, r = cfg.rules, run = cfg.run;
    let h = "";
    // (hourly summary panel removed 2026-09-01 -- the sections below show the same
    // information visually; /api/analysis still carries "summary" untouched)

    // A
    const meta = A.model.meta, tr = A.transition;
    const judged = A.rooms.filter((x) => x.judged).length, held = A.rooms.length - judged;
    h += sec("shield", "cyan", "유효 범위 — 이 페이지의 해석이 성립하는 조건", `daily 06:00 UTC · ${run.daily_window_days}일 창 · hourly ${run.hourly_window_hours}h`)
      + `<div class="panel"><div class="grid g4" style="gap:10px">`
      + metric("daily 분석 창", kstRange(A.daily_window), A.run_at.daily_kst ? `daily ${esc(A.run_at.daily_kst)} KST` : "daily 미실행")
      + metric("진단 모델", esc(A.model.ver || "—"), meta ? `${num(meta.rows)}행 · ${meta.window_days}d 학습` : "")
      + metric("전이 집계 유효 쌍", tr ? num(tr.valid_pairs) : "—", tr ? `결측 단절 ${num(tr.gap_pairs)}회 제외` : "daily 미실행")
      + metric("hourly 마지막 실행", esc(A.run_at.hourly_kst || "—"), `${judged}노드 판정${held ? ` · 보류 ${held}` : ""}`)
      + `</div>`;
    if (A.qc.length) {
      const strip = (q) => q.days.length ? `<span class="row" style="gap:3px" data-tip="${esc(q.days.map((d) => `${d.date.slice(5)} ${d.passed ? "통과" : "탈락"} (co2 ${pct(d.valid_co2_pct)})`).join("\n"))}">${q.days.map((d) => `<i style="width:9px;height:9px;border-radius:2px;display:inline-block;background:${d.passed ? css("--green") : css("--red")};opacity:${d.passed ? 0.7 : 1}"></i>`).join("")}${q.failed_days ? `<span class="tt" style="margin-left:4px">탈락 ${q.failed_days}일</span>` : ""}</span>` : "—";
      h += table(["교실", "노드", "CO₂ 유효율", "VOC 유효율", "판정", "사유", `최근 ${run.daily_window_days}일`], A.qc.map((q) => ({ cells: [nm(q), esc(q.node), pct(q.valid_co2_pct), pct(q.valid_voc_pct), q.passed ? chip("사용", "ok") : chip("제외", "ex"), esc(q.reason || "—"), strip(q)], txt: [5] })), "").replace('<div class="wrap">', '<div class="wrap" style="margin-top:12px">');
    }
    h += `<p class="note">QC: 노드×일 CO₂ 유효율 ≥ ${cfg.qc.daily_valid_pct_min}%(수신 행 기준, KST 일)만 사용 · ${cfg.regime.bucket_minutes}분 floor 버킷 · 보간 없음</p></div>`;

    // B
    const BH = 470;
    const brows = A.rooms.map((x) => ({ cls: x.judged ? "" : "dim", cells: [nm(x), regime(x.regime), num(x.co2), num(x.voc), x.judged ? `${x.dwell_censored ? "≥" : ""}${num(x.dwell_min)}` : "—", actionChip(x.action.kind, x.action.word)], txt: [5] }));
    h += sec("plane", "cyan", "현재 레짐 — 고정 스케일 CO₂×VOC 평면", `hourly · ${esc(A.model.ver || "—")} predict · ${cfg.regime.smooth_window * cfg.regime.bucket_minutes}분 평활 · CO₂÷${cfg.regime.co2_scale} · VOC÷${cfg.regime.voc_scale}`)
      + `<div class="grid g5" style="align-items:stretch"><div class="span3 panel" style="height:${BH}px">${CH.plane(A.rooms, cfg, meta, BH - 30)}</div>`
      + `<div class="span2 panel" style="height:${BH}px;display:flex;flex-direction:column">${table(["교실", "레짐", "CO₂", "VOC", "체류(min)", "행동"], brows)}<p class="note" style="margin-top:auto">체류 = 현재 레짐에 머문 시간(관측 하한). 축은 외기 기준 고정 — 재학습해도 4분면 위치가 유지되어 지난주와 비교 가능. 제외 = QC 게이트 미달 — 평면에 별 없음.</p></div></div>`;

    // C
    h += sec("band", "orange", `레짐 스위칭 밴드 — ${run.daily_window_days}일 × 교실`, "daily · 시간 단위 mode · 회색 = 결측 / 게이트 탈락");
    if (A.band) {
      const sh = A.band.share;
      const legend = A.regimes.map((k) => `<span><i style="--sw:${AQ.regimeColor(k)}"></i>${AQ.REGIME_KO[k]} ${pct(sh[k] || 0)}</span>`).join("") + (sh.missing ? `<span><i style="--sw:${css("--grid")}"></i>결측 ${pct(sh.missing)}</span>` : "");
      h += `<div class="panel">${CH.band(A.band)}<div class="legend">${legend}</div></div>`;
    } else h += '<div class="info">daily 실행 후 표시됩니다.</div>';

    // D
    h += sec("transition", "blue", "전이확률 · 체류시간", `Δt = ${cfg.time.transition_dt_minutes} min ± ${cfg.time.transition_dt_tolerance} · 단절 쌍 ${tr ? num(tr.gap_pairs) : "—"}개 제외 · 체류시간은 하한`);
    if (tr) {
      const drows = tr.rows.map((x) => ({ cells: [`${regime(x.regime)} · ${x.regime}`, dash(x.persist === null ? null : x.persist.toFixed(3)), num(x.dwell_median), x.next ? `→ ${AQ.REGIME_KO[x.next]} ${x.next_p.toFixed(3)}` : "—", num(x.pairs)], txt: [3] }));
      h += `<div class="grid g5"><div class="span3 panel">${table(["레짐", "지속확률", "중앙 체류(min)", "가장 흔한 다음 전이", "관측 쌍"], drows)}</div><div class="span2 panel">${CH.matrix(tr.counts, A.regimes)}</div></div>`;
    } else h += '<div class="info">daily 실행 후 표시됩니다.</div>';

    // E
    h += sec("action", "red", "행동지침 — 레짐(ML) × 임계(규칙) × 히스테리시스", `hourly · 환풍기 ON CO₂&gt;${r.fan.on_co2} / OFF &lt;${r.fan.off_co2} · 공청기 ON VOC&gt;${r.purifier.on_voc} / OFF &lt;${r.purifier.off_voc} · 최소 ${r.min_run_minutes}분`);
    h += `<div class="panel howto"><div><span class="sw z-off"></span>OFF 구간 — 하한 미만, 끔</div><div><span class="sw z-band"></span>밴드 — 하한~상한, 이전 상태 유지</div><div><span class="sw z-on"></span>ON 구간 — 상한 초과, 레짐 게이트 열리면 켬</div>`
      + `<div><span class="sw mk"></span>현재값 (hourly ${esc(A.action_run_at_kst || "—")} KST 판정) · 스트립 끝 = 최신 수신</div><div><span class="sw trk"></span>장치 ON 이력</div><div><span class="sw hat"></span>QC 탈락 — 규칙 미평가, 상태 유지</div></div>`
      + `<div class="acts">${A.rooms.map((x) => actionCard(x, r)).join("")}</div>`;

    // F
    h += sec("forecast", "purple", "예측 · 경보 — 30분 후 CO₂ · VOC", "hourly · 다중출력 회귀(StandardScaler → Ridge) · 타깃 = 미래 실측값 · 경보 = 예측값이 ON 임계 초과");
    if (A.forecast.length) {
      const hz = A.forecast[0].horizon_min;
      h += `<div class="panel">${table(["교실", "CO₂ now", `CO₂ +${hz}min`, "VOC now", `VOC +${hz}min`, "경보", "학습 행"], A.forecast.map((f) => ({ cells: [nm(f), num(f.co2_now), num(f.co2_pred), num(f.voc_now), num(f.voc_pred), f.alert ? `<span style="color:var(--orange)">⚠ 임계 초과 예상</span>` : "—", num(f.train_rows)], txt: [5] })))}</div>`;
    } else h += '<div class="info">예측 없음 (연속 버킷이 4시간 미만이거나 QC 탈락)</div>';

    // G
    h += sec("people", "orange", "재실 × CO₂ — 비전 노드 조인", `daily · (교실, ${cfg.regime.bucket_minutes}분 버킷) 정확 조인 · occ n ≥ ${cfg.occ_co2.min_occ_n} · ρ는 포화형 관계라 Spearman`);
    const oc = A.occ_co2;
    if (oc) {
      const grows = oc.by_room.map((x) => ({ cells: [esc(x.room), num(x.n), x.rho === null ? "—" : x.rho.toFixed(4), x.slope === null ? "—" : num(x.slope, 1), x.last_bucket_kst ? `${esc(x.last_bucket_kst)}${x.stopped ? ` ${chip("중단", "warn")}` : ""}` : "—"] }));
      h += `<div class="grid g3"><div class="panel">${metric("pooled Spearman ρ", oc.rho === null ? "—" : oc.rho.toFixed(2), `n = ${num(oc.n)} · 기울기 ${oc.slope === null ? "—" : num(oc.slope, 1)} ppm/인 (참고값)`)}<p class="note">중단 = 마지막 비전 버킷이 분석 창(${run.daily_window_days}일) 이전 · 비전 노드 ${oc.by_room.length}개 중 ${oc.by_room.filter((x) => x.stopped).length}개 중단</p></div>`
        + `<div class="span2 panel">${grows.length ? table(["교실", "조인 행", "Spearman ρ", "기울기 (ppm/인)", "마지막 비전 버킷 (KST)"], grows) : '<div class="info">조인된 (교실, 버킷)이 없습니다 — 비전 노드 데이터 확인</div>'}</div></div>`;
    } else h += '<div class="info">daily 실행 후 표시됩니다.</div>';

    // H
    h += sec("explore", "gray", "탐색 시각화 — 상관 · 상대 레짐 (RobustScaling)", `daily · 페이지 1에서 이관 · 판정에 쓰지 않음 · 서버 집계본(${A.explore ? A.explore.pooled.bins : 24}×${A.explore ? A.explore.pooled.bins : 24})`);
    if (A.explore) {
      const ex = A.explore, p = ex.pooled;
      const cur = A.rooms.filter((x) => x.co2 !== null && x.voc !== null).map((x) => ({ label: x.label, color: x.color, x: CH.rc(x.co2, p.co2_med, p.co2_iqr), y: CH.rc(x.voc, p.voc_med, p.voc_iqr) }));
      const nodes = A.rooms.filter((x) => ex.nodes[x.node]);
      if (!within || !ex.nodes[within]) within = nodes.length ? nodes[0].node : null;
      const wn = within ? ex.nodes[within] : null, wr = A.rooms.find((x) => x.node === within);
      const wcur = wn && wr && wr.co2 !== null && wr.voc !== null ? [{ label: wr.label, color: css("--orange"), x: CH.rc(wr.co2, wn.co2_med, wn.co2_iqr), y: CH.rc(wr.voc, wn.voc_med, wn.voc_iqr) }] : [];
      h += `<div class="grid g3"><div class="panel"><div class="tt" style="margin-bottom:6px">Spearman 상관 (${run.daily_window_days}일)</div>${CH.corr(ex)}</div>`
        + `<div class="panel"><div class="tt" style="margin-bottom:6px">Pooled 상대 레짐 — 노드 간 비교 · ★ 현재 (n=${num(p.n)})</div>${CH.density(p, cur)}</div>`
        + `<div class="panel"><div class="row" style="margin-bottom:6px"><span class="tt">자기 기준 (within-node${wn ? `, n=${num(wn.n)}` : ""})</span><select id="within-sel">${nodes.map((x) => `<option value="${esc(x.node)}"${x.node === within ? " selected" : ""}>${esc(x.label)}</option>`).join("")}</select></div>${wn ? CH.density(wn, wcur) : '<div class="info">노드 집계본 없음</div>'}</div></div>`
        + '<p class="note">여기 두 산점도는 "층위 1: 보는 도구". 판정 엔진(B~E)은 고정 스케일 GMM만 사용 — 데이터 의존 스케일러는 재학습 때 군집이 뒤집히기 때문.</p>';
    } else h += '<div class="info">daily 실행 후 표시됩니다.</div>';

    // I
    const g = cfg.governance;
    h += sec("history", "purple", "모델 이력", `weekly · refit → 비교 → 조건부 승격: 4분면 상이 ∧ (로그우도 +${Math.round(g.loglik_gain_min * 100)}% ∨ 중심 이동 ≥ ${g.centroid_shift_min}) ∨ 학사 경계일 · 학습 창 ${g.train_window_days}d`)
      + `<div class="panel"><div style="font-size:13px;margin-bottom:8px">저장된 버전: ${A.model.versions.length ? A.model.versions.map(esc).join(", ") : "없음"} · current <b>${esc(A.model.current || "없음")}</b></div>`
      + (A.model_events.length ? table(["run_at (KST)", "후보", "결정", "학습 창", "행 수", "중심 이동", "로그우도 Δ", "current", "사유"], A.model_events.map((e) => ({ cells: [esc(e.run_at_kst), esc(e.candidate_ver || "—"), chip(e.decision || "—", e.decision === "promote" ? "ok" : e.decision === "reject" ? "ex" : ""), esc(e.window || "—"), num(e.rows), dash(e.centroid_shift), dash(e.loglik_delta), esc(e.current_after || "—"), esc(e.reason)], txt: [8] })))
         : '<div class="info">weekly 실행 후 표시됩니다.</div>') + "</div>";

    $("#page2").innerHTML = h;
    const ws = $("#within-sel");
    if (ws) ws.addEventListener("change", (e) => { within = e.target.value; render(); });
  }

  // E card: header + action word, then per device "now" (value · zone chip · band gauge)
  // over its 24 h trace. Device state is always ON / OFF (actuator_state); a QC-excluded
  // run only means the rule layer was not evaluated ("미평가"), the state carries over.
  function actionCard(x, rules) {
    const a = x.action, k = a.kind, col = css(actionColor[k] || "--grid");
    const why = x.judged ? `${AQ.REGIME_KO[x.regime] || x.regime} · 체류 ${x.dwell_censored ? "≥" : ""}${num(x.dwell_min)}분 · ${esc(a.reason)}` : esc(a.reason || "QC 게이트 미달 — 규칙 미평가, 장치 상태는 마지막 값 그대로");
    return `<div class="act${k === "hold" ? " hold" : ""}" style="border-left-color:${col}"><div class="h">${nm(x)}${regime(x.regime)}</div><div class="do">${actionChip(k, a.word, true)}</div>`
      + `<div class="devs">${deviceBlock(x, "fan", rules)}${deviceBlock(x, "purifier", rules)}</div><div class="why">${why}</div></div>`;
  }

  function deviceBlock(x, dev, rules) {
    const ko = dev === "fan" ? "환풍기" : "공청기", d = (x.devices || {})[dev], c = CH.bandCfg(rules, dev), b = x.band24 || {};
    const state = d ? d.state === 1 : false, kept = state && /^(keep|min_run)/.test(d.rule || "");
    const st = !d ? '<span class="st">—</span>' : d.rule === "hold" ? `<span class="st${state ? " on" : ""}">${state ? "ON" : "OFF"} · 미평가</span>`
      : state ? (kept ? '<span class="st keep">ON · 유지</span>' : '<span class="st on">ON</span>') : '<span class="st">OFF</span>';
    const key = dev === "fan" ? "co2" : "voc";
    const v = x.judged ? x[key] : ((d || {}).values || {})[key] ?? null, z = CH.bandZone(c, v);   // unjudged: the value the skipped rule saw
    const val = v === null || v === undefined ? "<span>—</span>" : `<b>${c.var} ${num(Math.round(v))}</b>${c.unit ? `<span>${c.unit}</span>` : ""}<span class="zc z-${z}">${CH.ZONE_KO[z]}</span>`;
    const series = dev === "fan" ? b.co2 : b.voc;
    const body = series && series.length ? CH.bandGauge(c, v) + CH.bandStrip(c, b, dev, ko) : `<div class="empty">${b.hours || 24}h 수신 없음</div>`;
    return `<div class="dev"><div class="lbl"><span class="nm">${ko} ${st}</span><span class="val">${val}</span></div>${body}</div>`;
  }

  async function load() {
    const d = await getJSON("/api/analysis");
    if (!A || A.version !== d.version) { A = d; render(); }
  }
  AQ.initTheme(); AQ.initTip(); AQ.initSidebar();
  AQ.onTheme(render);
  poll(load, 60000);
})();
