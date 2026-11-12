// Tideline lifecycle timeline. Plain JS + SVG, no build step.
(() => {
  const C = {
    text: "#E5E7EB", muted: "#9CA3AF", line: "#1F2937", panel: "#131A26",
    catch: "#2DD4BF", prauc: "#A78BFA", drift: "#F59E0B",
    healthy: "#22C55E", warn: "#F59E0B", alert: "#EF4444", champion: "#2DD4BF", challenger: "#A78BFA",
  };
  const EVENT = {
    drift_detected: { label: "Drift detected", row: 0, color: C.warn, shape: "triangle" },
    retrain_started: { label: "Retrain started", row: 1, color: C.muted, shape: "ring" },
    challenger_trained: { label: "Challenger trained", row: 1, color: C.challenger, shape: "dot" },
    parity_checked: { label: "Feature parity checked", row: 1, color: C.muted, shape: "dot" },
    gate_passed: { label: "Gate passed", row: 1, color: C.healthy, shape: "check" },
    gate_failed: { label: "Gate failed: champion kept", row: 1, color: C.alert, shape: "cross" },
    canary_step: { label: "Canary step", row: 2, color: C.champion, shape: "bar" },
    promoted: { label: "Promoted to champion", row: 2, color: C.champion, shape: "diamond" },
    rolled_back: { label: "Rolled back", row: 2, color: C.alert, shape: "diamond" },
  };
  const ROWS = ["Monitor", "Pipeline", "Rollout"];
  const $ = (s) => document.querySelector(s);
  const pct = (v, d = 0) => (v == null || Number.isNaN(v) ? "n/a" : `${(100 * v).toFixed(d)}%`);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let scenarios = [], summary = null, current = null, selected = null;

  async function init() {
    [scenarios, summary] = await Promise.all([
      fetch("data/scenarios.json").then((r) => r.json()),
      fetch("data/summary.json").then((r) => r.json()),
    ]);
    const tabs = $("#tabs");
    scenarios.forEach((s, i) => {
      const b = document.createElement("button");
      b.className = "tab"; b.textContent = s.label; b.setAttribute("role", "tab");
      b.onclick = () => load(i);
      tabs.appendChild(b);
    });
    const want = new URLSearchParams(location.search).get("scenario");
    load(Math.max(0, scenarios.findIndex((s) => s.scenario === want)));
    window.addEventListener("resize", () => current && draw());
  }

  async function load(i) {
    [...$("#tabs").children].forEach((b, j) => b.setAttribute("aria-selected", String(i === j)));
    current = await fetch(scenarios[i].file).then((r) => r.json());
    selected = null;
    history.replaceState(null, "", `?scenario=${scenarios[i].scenario}`);
    tiles(); legend(); draw(); table(); resetDetails();
  }

  function stat(key, field) {
    const row = summary.table[`${current.scenario}/${key}`];
    return row ? row[field] : null;
  }

  function tiles() {
    const fmtRange = (s, f) => (s && s.mean != null ? `${f(s.min)} to ${f(s.max)}` : "");
    const items = [];
    const rd = stat("drift", "recall_post"), rs = stat("scheduled", "recall_post"), rn = stat("none", "recall_post");
    items.push({ label: current.scenario === "control" ? "Fraud caught (days 65+)" : "Fraud caught after drift",
      value: pct(rd && rd.mean), sub: `drift-triggered · weekly ${pct(rs && rs.mean)} · none ${pct(rn && rn.mean)}` });
    const det = stat("drift", "time_to_detect");
    items.push(current.scenario === "control"
      ? { label: "False drift alarms", value: String(current.events.filter((e) => e.type === "drift_detected").length), sub: "in the run shown (no drift exists)" }
      : { label: "Days to detect", value: det && det.mean != null ? det.mean.toFixed(1) : "n/a", sub: `range ${fmtRange(det, (v) => v.toFixed(0))} across seeds` });
    const rt = stat("drift", "retrains"), rw = stat("scheduled", "retrains");
    items.push({ label: "Retrains", value: rt ? rt.mean.toFixed(1) : "n/a", sub: `drift-triggered vs ${rw ? rw.mean.toFixed(0) : "?"} weekly` });
    const promos = current.events.filter((e) => e.type === "promoted").length;
    const backs = current.events.filter((e) => e.type === "rolled_back").length;
    const fails = current.events.filter((e) => e.type === "gate_failed").length;
    items.push({ label: "In this run", value: `${promos} / ${fails} / ${backs}`, sub: "promoted / gate failed / rolled back" });
    $("#tiles").innerHTML = items.map((t) => `<div class="panel tile"><div class="label">${esc(t.label)}</div><div class="value">${esc(t.value)}</div><div class="sub">${esc(t.sub)}</div></div>`).join("");
    const src = current.source === "fullloop"
      ? `Full Kubernetes loop, run ${current.run} (seed ${current.seed}). Tiles: fast backtest, mean of ${summary.table[current.scenario + "/drift"].seeds.length} test seeds.`
      : `Fast backtest run (${current.run}). Tiles: mean of test seeds.`;
    $("#source").textContent = src + " Fraud caught uses the true labels; PR-AUC and drift are what the monitor could see that day.";
  }

  function legend() {
    const sw = (color, dash, text) => `<span class="flex items-center"><span class="swatch" style="border-color:${color};border-top-style:${dash}"></span>${text}</span>`;
    $("#legend").innerHTML = [
      sw(C.catch, "solid", "Fraud caught at 1% budget (7-day rolling)"),
      sw(C.prauc, "dashed", "PR-AUC on settled labels (monitor)"),
      sw(C.drift, "solid", "Largest feature drift score"),
    ].join("");
  }

  function draw() {
    const el = $("#chart");
    const W = Math.max(320, el.clientWidth);
    const narrow = W < 640;
    const m = { l: narrow ? 40 : 56, r: 12, t: 12 };
    const hTop = narrow ? 200 : 260, hEv = 3 * 22 + 10, hDrift = narrow ? 80 : 100, hChamp = 26, gap = 14;
    const yTop0 = m.t, yEv0 = yTop0 + hTop + gap, yDr0 = yEv0 + hEv + gap, yCh0 = yDr0 + hDrift + gap;
    const H = yCh0 + hChamp + 26;
    const days = current.days;
    const d0 = days[0].day, d1 = days[days.length - 1].day;
    const x = (d) => m.l + ((d - d0) / Math.max(1, d1 - d0)) * (W - m.l - m.r);
    const yP = (v) => yTop0 + hTop - v * hTop;
    const dmax = Math.max(0.3, ...days.map((d) => d.drift || 0)) * 1.1;
    const yD = (v) => yDr0 + hDrift - Math.min(v, dmax) / dmax * hDrift;
    const s = [];
    s.push(`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Lifecycle timeline for ${esc(current.label)}">`);
    // grid + axes, top panel
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      s.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${yP(v)}" y2="${yP(v)}" stroke="${C.line}"/>`);
      s.push(`<text x="${m.l - 8}" y="${yP(v) + 4}" fill="${C.muted}" font-size="11" text-anchor="end" class="num">${v * 100}%</text>`);
    }
    // drift start
    if (current.drift_start != null && current.scenario !== "control") {
      const xs = x(current.drift_start);
      s.push(`<line x1="${xs}" x2="${xs}" y1="${yTop0}" y2="${yCh0 + hChamp}" stroke="${C.warn}" stroke-dasharray="4 4" opacity=".8"/>`);
      s.push(`<text x="${xs + 6}" y="${yTop0 + 14}" fill="${C.warn}" font-size="12">drift starts (day ${current.drift_start})</text>`);
    }
    const path = (pts) => pts.filter((p) => p[1] != null && !Number.isNaN(p[1])).map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    s.push(`<path d="${path(days.map((d) => [x(d.day), d.delayed_pr_auc == null ? null : yP(d.delayed_pr_auc)]))}" fill="none" stroke="${C.prauc}" stroke-width="2" stroke-dasharray="6 4"/>`);
    s.push(`<path d="${path(days.map((d) => [x(d.day), d.recall == null ? null : yP(d.recall)]))}" fill="none" stroke="${C.catch}" stroke-width="2.5"/>`);
    // event lanes
    ROWS.forEach((r, i) => {
      const y = yEv0 + 5 + i * 22 + 11;
      s.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" stroke="${C.line}"/>`);
      s.push(`<text x="${m.l - 8}" y="${y + 4}" fill="${C.muted}" font-size="10" text-anchor="end">${narrow ? r[0] : r}</text>`);
    });
    const shown = eventsForChart();
    shown.forEach((g, idx) => {
      const e = g.event, spec = EVENT[e.type];
      const cx = x(e.day) + g.offset, cy = yEv0 + 5 + spec.row * 22 + 11;
      s.push(`<g class="marker${selected === idx ? " selected" : ""}" data-idx="${idx}" tabindex="0" role="button" aria-label="${esc(spec.label)} on day ${e.day}">`);
      s.push(`<rect x="${cx - 10}" y="${cy - 10}" width="20" height="20" fill="transparent"/>`);
      s.push(shape(spec, cx, cy));
      s.push(`</g>`);
    });
    // drift panel
    s.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${yDr0 + hDrift}" y2="${yDr0 + hDrift}" stroke="${C.line}"/>`);
    s.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${yD(0.1)}" y2="${yD(0.1)}" stroke="${C.alert}" stroke-dasharray="3 4" opacity=".7"/>`);
    s.push(`<text x="${W - m.r}" y="${yD(0.1) - 4}" fill="${C.alert}" font-size="10" text-anchor="end">threshold 0.1</text>`);
    s.push(`<text x="${m.l - 8}" y="${yDr0 + 10}" fill="${C.muted}" font-size="10" text-anchor="end">drift</text>`);
    s.push(`<path d="${path(days.map((d) => [x(d.day), d.drift == null ? null : yD(d.drift)]))}" fill="none" stroke="${C.drift}" stroke-width="2"/>`);
    // champion strip
    let segStart = 0;
    for (let i = 1; i <= days.length; i++) {
      if (i === days.length || days[i].champion !== days[segStart].champion) {
        const xa = x(days[segStart].day), xb = i === days.length ? W - m.r : x(days[i].day);
        const v = days[segStart].champion, even = Number(v) % 2 === 0;
        s.push(`<rect x="${xa}" y="${yCh0}" width="${Math.max(1, xb - xa - 2)}" height="${hChamp}" rx="4" fill="${even ? "#16313A" : "#123A36"}" stroke="${C.line}"/>`);
        if (xb - xa > 28) s.push(`<text x="${xa + 6}" y="${yCh0 + 17}" fill="${C.text}" font-size="11" class="num">v${esc(v)}</text>`);
        segStart = i;
      }
    }
    s.push(`<text x="${m.l - 8}" y="${yCh0 + 17}" fill="${C.muted}" font-size="10" text-anchor="end">model</text>`);
    // x axis
    const step = narrow ? 20 : 10;
    for (let d = Math.ceil(d0 / step) * step; d <= d1; d += step) {
      s.push(`<text x="${x(d)}" y="${H - 6}" fill="${C.muted}" font-size="11" text-anchor="middle" class="num">day ${d}</text>`);
    }
    s.push(`<line id="cross" x1="0" x2="0" y1="${yTop0}" y2="${yCh0 + hChamp}" stroke="${C.text}" opacity="0" stroke-width="1"/>`);
    s.push(`<rect id="hover" x="${m.l}" y="${yTop0}" width="${W - m.l - m.r}" height="${hTop}" fill="transparent"/>`);
    s.push(`</svg>`);
    el.innerHTML = s.join("");

    const tip = $("#tooltip"), cross = el.querySelector("#cross");
    el.querySelector("#hover").addEventListener("mousemove", (ev) => {
      const rect = el.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const day = Math.round(d0 + ((px - m.l) / (W - m.l - m.r)) * (d1 - d0));
      const d = days.find((r) => r.day === day);
      if (!d) return;
      cross.setAttribute("x1", x(day)); cross.setAttribute("x2", x(day)); cross.setAttribute("opacity", ".35");
      tip.hidden = false;
      tip.innerHTML = `<b>Day ${day}</b> · model v${esc(d.champion)}<br>Fraud caught (7d): <b class="num">${pct(d.recall, 1)}</b><br>PR-AUC, settled labels: <b class="num">${d.delayed_pr_auc == null ? "n/a" : d.delayed_pr_auc.toFixed(3)}</b><br>Largest drift score: <b class="num">${d.drift == null ? "n/a" : d.drift.toFixed(2)}</b>${d.decision ? `<br><span class="text-muted">${esc(d.decision)}</span>` : ""}`;
      place(tip, ev);
    });
    el.querySelector("#hover").addEventListener("mouseleave", () => { tip.hidden = true; cross.setAttribute("opacity", "0"); });
    el.querySelectorAll(".marker").forEach((g) => {
      const idx = Number(g.dataset.idx), e = shown[idx].event;
      g.addEventListener("click", () => select(idx));
      g.addEventListener("keydown", (k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); select(idx); } });
      g.addEventListener("mousemove", (ev) => { tip.hidden = false; tip.innerHTML = `<b>${esc(EVENT[e.type].label)}</b> · day ${e.day}<br>${esc(e.details)}`; place(tip, ev); });
      g.addEventListener("mouseleave", () => { tip.hidden = true; });
    });
    function select(idx) { selected = idx; draw(); details(shown[idx].event); }
  }

  function place(tip, ev) {
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let left = ev.clientX + pad, top = ev.clientY + pad;
    if (left + w > innerWidth - 8) left = ev.clientX - w - pad;
    if (top + h > innerHeight - 8) top = ev.clientY - h - pad;
    tip.style.left = `${Math.max(8, left)}px`; tip.style.top = `${Math.max(8, top)}px`;
  }

  function eventsForChart() {
    // Keep the chart readable: one marker per type per day, small offsets for collisions.
    const seen = new Set(), out = [];
    for (const e of current.events) {
      if (!EVENT[e.type]) continue;
      const key = `${e.type}-${e.day}-${e.weight ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const same = out.filter((o) => o.event.day === e.day && EVENT[o.event.type].row === EVENT[e.type].row).length;
      out.push({ event: e, offset: same * 9 });
    }
    return out;
  }

  function shape(spec, x, y) {
    const c = spec.color;
    switch (spec.shape) {
      case "triangle": return `<path class="ring" d="M${x},${y - 7} L${x + 7},${y + 6} L${x - 7},${y + 6} Z" fill="${c}" stroke="${C.panel}" stroke-width="2"/>`;
      case "ring": return `<circle class="ring" cx="${x}" cy="${y}" r="5.5" fill="${C.panel}" stroke="${c}" stroke-width="2"/>`;
      case "dot": return `<circle class="ring" cx="${x}" cy="${y}" r="5" fill="${c}" stroke="${C.panel}" stroke-width="2"/>`;
      case "check": return `<circle class="ring" cx="${x}" cy="${y}" r="7" fill="${c}" stroke="${C.panel}" stroke-width="2"/><path d="M${x - 3.5},${y} l2.5,2.5 l4.5,-5" stroke="${C.panel}" stroke-width="2" fill="none"/>`;
      case "cross": return `<circle class="ring" cx="${x}" cy="${y}" r="7" fill="${c}" stroke="${C.panel}" stroke-width="2"/><path d="M${x - 3},${y - 3} l6,6 M${x + 3},${y - 3} l-6,6" stroke="${C.panel}" stroke-width="2"/>`;
      case "bar": return `<rect class="ring" x="${x - 3}" y="${y - 7}" width="6" height="14" rx="2" fill="${c}" stroke="${C.panel}" stroke-width="2"/>`;
      case "diamond": return `<path class="ring" d="M${x},${y - 8} L${x + 8},${y} L${x},${y + 8} L${x - 8},${y} Z" fill="${c}" stroke="${C.panel}" stroke-width="2"/>`;
      default: return "";
    }
  }

  function resetDetails() {
    $("#details").innerHTML = `<h2 class="font-semibold mb-2">Event details</h2><p class="text-muted text-sm">Click a marker on the timeline to see what happened: the drifted features and the Evidently report, champion vs challenger at the gate, and each canary step.</p>`;
  }

  function metricRows(a, b) {
    const rows = [["Fraud caught at budget", "recall_at_budget", pct], ["Fraud dollars caught", "dollars_caught", pct], ["PR-AUC", "pr_auc", (v) => v.toFixed(3)]];
    return rows.map(([n, k, f]) => `<tr><td>${n}</td><td class="num">${a ? f(a[k]) : "none"}</td><td class="num">${b ? f(b[k]) : ""}</td></tr>`).join("");
  }

  function details(e) {
    const spec = EVENT[e.type];
    const related = current.events.filter((o) => e.workflow ? o.workflow === e.workflow : o.day === e.day);
    let body = `<p class="text-sm mb-3">${esc(e.details)}</p>`;
    if (e.type === "drift_detected") {
      const fs = Object.entries(e.feature_scores || {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
      if (fs.length) {
        const max = Math.max(0.2, ...fs.map((f) => f[1]));
        body += `<p class="text-xs text-muted mb-1">Top feature drift scores (threshold 0.1)</p>` + fs.map(([f, v]) =>
          `<div class="flex items-center gap-2 text-xs mb-1"><span class="w-40 truncate">${esc(f)}</span><span class="h-2 rounded" style="width:${(v / max) * 120}px;background:${v >= 0.1 ? C.warn : C.line}"></span><span class="num">${v.toFixed(2)}</span></div>`).join("");
      }
      if (e.delayed_recall != null) body += `<p class="text-xs text-muted mt-2">Recall on settled labels that day: <span class="num">${pct(e.delayed_recall, 1)}</span></p>`;
      if (e.report_url) body += `<p class="mt-3"><a class="link text-sm" href="${esc(e.report_url)}" target="_blank" rel="noopener">Open the Evidently drift report</a></p>`;
    }
    const gate = related.find((o) => o.type === "gate_passed" || o.type === "gate_failed");
    if (gate && (gate.champion || gate.challenger)) {
      body += `<p class="text-xs text-muted mt-3 mb-1">Promotion gate on the same recent holdout</p>
        <table class="metric-table text-sm w-full"><tr class="text-muted text-xs"><th class="text-left">Metric</th><th class="text-left" style="color:${C.champion}">Champion${gate.champion_version ? ` v${esc(gate.champion_version)}` : ""}</th><th class="text-left" style="color:${C.challenger}">Challenger${gate.version ? ` v${esc(gate.version)}` : ""}</th></tr>${metricRows(gate.champion, gate.challenger)}</table>
        <p class="mt-2"><span class="pill" style="color:${gate.type === "gate_passed" ? C.healthy : C.alert}">${gate.type === "gate_passed" ? "passed" : "failed"}</span> <span class="text-xs text-muted">${esc(gate.details)}</span></p>`;
    }
    const steps = related.filter((o) => o.type === "canary_step" || o.type === "promoted" || o.type === "rolled_back");
    if (steps.length) {
      body += `<p class="text-xs text-muted mt-3 mb-1">Canary rollout</p><ol class="text-sm space-y-1">` + steps.map((o) =>
        `<li><span class="pill" style="color:${EVENT[o.type].color}">${esc(EVENT[o.type].label)}${o.weight ? ` ${o.weight}%` : ""}</span> <span class="text-xs text-muted">${esc(o.details)}</span></li>`).join("") + `</ol>`;
    }
    const parity = related.find((o) => o.type === "parity_checked");
    if (parity) body += `<p class="text-xs text-muted mt-3">Feature parity: ${esc(parity.details)}</p>`;
    if (e.workflow) body += `<p class="text-xs text-muted mt-3">Argo workflow <span class="num">${esc(e.workflow)}</span></p>`;
    $("#details").innerHTML = `<h2 class="font-semibold mb-1" style="color:${spec.color}">${esc(spec.label)}</h2><p class="text-xs text-muted mb-3">Simulated day ${e.day}</p>${body}`;
  }

  function table() {
    const rows = current.events.filter((e) => e.type !== "canary_step" && e.type !== "parity_checked");
    $("#event-table tbody").innerHTML = rows.map((e) => `<tr><td class="num">${e.day}</td><td style="color:${EVENT[e.type].color}">${esc(EVENT[e.type].label)}</td><td class="text-muted">${esc(e.details)}</td></tr>`).join("") ||
      `<tr><td colspan="3" class="text-muted">No events: the model was never retrained in this run.</td></tr>`;
  }

  init();
})();
