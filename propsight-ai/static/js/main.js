/* Shared helpers + small pages (nav, result, model, history, admin). Vanilla JS only. */
const fmtINR = (n) => "₹" + Math.round(n).toLocaleString("en-IN");
function fmtShort(n) {
  if (n >= 1e7) return "₹" + (n / 1e7).toFixed(2) + " Crore";
  if (n >= 1e5) return "₹" + (n / 1e5).toFixed(1) + " Lakhs";
  return fmtINR(n);
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (s, r = document) => r.querySelector(s);
async function api(url, opts) {
  let res;
  try { res = await fetch(url, opts); } catch (e) { throw new Error("Cannot reach the server. Check that the Flask app is running."); }
  let data = {}; try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) throw new Error(data.error || "Something went wrong. Please try again.");
  return data;
}
function showMsg(el, text, ok) { el.textContent = text; el.className = "msg" + (ok ? " ok" : ""); el.hidden = !text; }

document.addEventListener("DOMContentLoaded", () => {
  const t = $(".nav-toggle"), nav = $("#nav");
  t.addEventListener("click", () => { const o = nav.classList.toggle("open"); t.setAttribute("aria-expanded", o); });
  const page = document.body.dataset.page;
  if (page === "home") $('[data-nav="home"]').classList.add("active");
  if (page === "valuation" || page === "result") $('[data-nav="valuation"]').classList.add("active");
  ({ result: initResult, model: initModel, history: initHistory, admin: initAdmin }[page] || (() => {}))();
});

/* ---------- result dashboard ---------- */
async function initResult() {
  const root = $("#resultRoot"), id = root.dataset.id;
  try {
    let r;
    if (id === "0") { r = JSON.parse(sessionStorage.getItem("ps_last") || "null"); if (!r) throw new Error("Result not found."); }
    else r = await api("/api/prediction/" + id);
    renderResult(r); $("#resultLoading").hidden = true; $("#resultBody").hidden = false;
  } catch (e) { $("#resultLoading").hidden = true; showMsg($("#resultError"), e.message); }
}

function bar(label, pct, text, cls) {
  return `<div class="row"><span>${esc(label)}</span><div class="track"><div class="fill ${cls || ""}" data-w="${pct}"></div></div><span class="small">${esc(text)}</span></div>`;
}
function renderResult(r) {
  const loc = (r.location && (r.location.locality ? r.location.locality + ", " + (r.location.city || "") : r.location.address)) || `${r.latitude.toFixed(4)}, ${r.longitude.toFixed(4)}`;
  const span = r.upper_estimate - r.lower_estimate, pos = span > 0 ? ((r.estimated_property_value - r.lower_estimate) / span) * 100 : 50;
  const gi = Object.entries(r.group_importance), gmax = Math.max(...gi.map((x) => x[1]));
  const counts = ["schools", "hospitals", "markets", "malls", "parks", "banks", "restaurants"].map((k) => [k, r.features[k + "_nearby"] ?? 0]);
  const cmax = Math.max(1, ...counts.map((c) => c[1]));
  const radii = { schools: 1, hospitals: 3, markets: 2, malls: 3, parks: 1, banks: 2, restaurants: 1 };
  const dist = (k) => (r.features[k] == null ? "n/a" : r.features[k].toFixed(1) + " km");
  const factorRows = r.factors.map((f) => {
    const dst = !f.higher_is_better, isPrice = f.feature === "local_average_price";
    const val = f.value == null ? "n/a" : isPrice ? fmtINR(f.value) + "/sq.ft" : dst ? f.value.toFixed(1) + " km" : f.feature.endsWith("score") ? f.value.toFixed(2) : String(f.value);
    const txt = dst ? `closer than ${100 - f.percentile}% of training locations` : `higher than ${f.percentile}% of training locations`;
    return `<tr><td>${esc(f.label)}</td><td class="num">${esc(val)}</td><td><div class="pct" title="${esc(txt)}"><i style="left:calc(${f.percentile}% - 2px)"></i></div><span class="small">${esc(txt)}</span></td></tr>`;
  }).join("");
  const nearest = (r.facilities || []).slice(0, 10).map((f) => `<tr><td>${esc(f.name)}</td><td>${esc(f.type)}</td><td class="num">${f.distance_km.toFixed(2)} km</td></tr>`).join("");
  $("#resultBody").innerHTML = `
  <div class="r-top"><div><h1 class="page-title">Property Valuation</h1><p>📍 ${esc(loc)} <span class="small">(${r.latitude.toFixed(5)}, ${r.longitude.toFixed(5)})</span></p></div>
    <div><a class="btn" href="/valuation">New valuation</a> <button class="btn" onclick="window.print()">Print</button></div></div>
  ${r.is_demo ? `<div class="warn"><span class="tag-demo">Demo data</span> ${esc(r.warnings.filter((w) => /DEMO/.test(w)).join(" "))} Load a real dataset on the <a href="/admin">admin page</a> and retrain.</div>` : ""}
  <section class="r-hero">
    <div><div class="label">Estimated Market Value</div><div class="r-value" id="valCount" data-v="${r.estimated_property_value}">${fmtINR(r.estimated_property_value)}</div>
      <div class="range-text">${fmtShort(r.estimated_property_value)}</div>
      <div class="rangebar" aria-label="Estimated range"><i></i><b style="left:calc(${pos.toFixed(1)}% - 2px)"></b></div>
      <div class="rb-labels"><span>${fmtINR(r.lower_estimate)}</span><span>${fmtINR(r.upper_estimate)}</span></div>
      <p class="small" style="color:#aebdc6;margin-top:.8rem">Estimated range: ${fmtShort(r.lower_estimate)} to ${fmtShort(r.upper_estimate)}. This is an ML-based estimate, not a guaranteed transaction price.</p></div>
    <div><div class="stat"><span class="label">Property Area</span><strong>${r.area_sqft.toLocaleString("en-IN")} sq.ft</strong></div>
      <div class="stat"><span class="label">Estimated Market Rate</span><strong>${fmtINR(r.predicted_price_per_sqft)} / sq.ft</strong></div>
      <div class="stat"><span class="label">Market range (rate)</span><strong>${fmtINR(r.lower_rate)} – ${fmtINR(r.upper_rate)}</strong></div>
      <div class="small" style="color:#aebdc6">Model: ${esc(r.model)}</div></div>
  </section>
  ${r.warnings.filter((w) => !/DEMO/.test(w)).map((w) => `<div class="warn">${esc(w)}</div>`).join("")}
  <section class="grid2">
    <div class="panel"><h3>Factors Influencing Valuation</h3>
      <table><tbody>
       <tr><td>Location Quality</td><td class="num"><span class="lvl ${r.summary["Location Quality"]}">${r.summary["Location Quality"]}</span></td></tr>
       <tr><td>Road Connectivity</td><td class="num"><span class="lvl ${r.summary["Road Connectivity"]}">${r.summary["Road Connectivity"]}</span></td></tr>
       <tr><td>Nearby Schools (1 km)</td><td class="num">${r.features.schools_nearby}</td></tr>
       <tr><td>Nearby Hospitals (3 km)</td><td class="num">${r.features.hospitals_nearby}</td></tr>
       <tr><td>Nearby Markets (2 km)</td><td class="num">${r.features.markets_nearby}</td></tr>
       <tr><td>Metro Distance</td><td class="num">${dist("metro_distance_km")}</td></tr>
       <tr><td>Commercial Activity</td><td class="num"><span class="lvl ${r.summary["Commercial Activity"]}">${r.summary["Commercial Activity"]}</span></td></tr>
       <tr><td>Local Historical Trend</td><td class="num small">Not available (no time data)</td></tr>
       <tr><td>Nearby property prices</td><td class="num">${fmtINR(r.local_market.average_rate)}/sq.ft <span class="small">(${r.local_market.comparables_within_2km} records within 2 km)</span></td></tr>
      </tbody></table></div>
    <div class="panel bars"><h3>Model feature importance</h3>
      ${gi.map(([k, v]) => bar(k, (v / gmax) * 100, (v * 100).toFixed(0) + "%")).join("")}
      <p class="small">${esc(r.importance_note)} It shows what the model relied on overall, not a claim that these factors cause the price.</p></div>
  </section>
  <section class="grid2">
    <div class="panel bars"><h3>Nearby facilities</h3>
      ${counts.map(([k, v]) => bar(k[0].toUpperCase() + k.slice(1) + " (" + radii[k] + " km)", (v / cmax) * 100, v, "g")).join("")}</div>
    <div class="panel"><h3>Connectivity</h3><table><tbody>
      <tr><td>Metro station</td><td class="num">${dist("metro_distance_km")}</td></tr><tr><td>Railway station</td><td class="num">${dist("railway_distance_km")}</td></tr>
      <tr><td>Highway</td><td class="num">${dist("highway_distance_km")}</td></tr><tr><td>Major road</td><td class="num">${dist("major_road_distance_km")}</td></tr>
      <tr><td>Airport</td><td class="num">${dist("airport_distance_km")}</td></tr></tbody></table>
      <p class="small">Facility source: ${r.facility_source === "demo" ? "simulated demo data" : "OpenStreetMap (live)"}.</p></div>
  </section>
  <section class="panel"><h3>How this location compares with the training data</h3><div class="table-scroll"><table>
    <thead><tr><th>Feature</th><th class="num">Value</th><th>Position</th></tr></thead><tbody>${factorRows}</tbody></table></div></section>
  <section class="panel" style="margin-top:1.2rem"><h3>Nearest facilities</h3><div class="table-scroll"><table><thead><tr><th>Name</th><th>Type</th><th class="num">Distance</th></tr></thead><tbody>${nearest}</tbody></table></div></section>
  <section class="panel" style="margin-top:1.2rem"><h3>How the range is calculated</h3><p class="small">${esc(r.range_method)}. Range = predicted rate × those ratios × your area.</p></section>`;
  requestAnimationFrame(() => document.querySelectorAll(".fill").forEach((f) => (f.style.width = f.dataset.w + "%")));
  const el = $("#valCount"), target = +el.dataset.v;
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const t0 = performance.now();
    (function tick(t) { const p = Math.min(1, (t - t0) / 900); el.textContent = fmtINR(target * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); })(t0);
  }
}

/* ---------- model performance ---------- */
async function initModel() {
  try {
    const m = await api("/api/model-info"), rows = Object.entries(m.models);
    const f = (x) => x.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    $("#modelBody").innerHTML = `
      ${m.uses_synthetic_demo_data ? '<div class="warn"><span class="tag-demo">Demo data</span> These metrics come from synthetic demo data. They show the pipeline works, not how accurate it is on real prices.</div>' : ""}
      <p>Selected model: <strong>${esc(m.selected_model)}</strong> (${esc(m.selection_rule)}). Trained ${esc(m.trained_at)} on ${m.n_records} cleaned records (train ${m.n_train} / validation ${m.n_validation} / test ${m.n_test}).</p>
      <div class="grid3">${rows.map(([n, r]) => `<div class="panel ${n === m.selected_model ? "best" : ""}"><h3>${esc(n)} ${n === m.selected_model ? '<span class="tag-demo">Selected</span>' : ""}</h3>
        <p class="small">Validation</p>MAE: ${f(r.validation.MAE)} ₹/sq.ft<br>RMSE: ${f(r.validation.RMSE)} ₹/sq.ft<br>R²: ${r.validation.R2.toFixed(3)}
        <p class="small" style="margin-top:.8rem">Held-out test</p>MAE: ${f(r.test.MAE)}<br>RMSE: ${f(r.test.RMSE)}<br>R²: ${r.test.R2.toFixed(3)}</div>`).join("")}</div>
      <div class="panel bars"><h3>Model feature importance (selected model)</h3>${Object.entries(m.feature_group_importance).map(([k, v]) => bar(k, v * 100 / Math.max(...Object.values(m.feature_group_importance)), (v * 100).toFixed(0) + "%")).join("")}<p class="small">${esc(m.importance_note)}</p></div>
      <div class="panel" style="margin-top:1.2rem"><h3>Data cleaning</h3><p class="small">Loaded ${m.cleaning.rows_loaded} rows. Dropped: ${esc(JSON.stringify(m.cleaning.dropped))}. Fixed: ${esc(JSON.stringify(m.cleaning.fixed))}. Missing values imputed: ${esc(JSON.stringify(m.cleaning.missing_values_before_imputation))}.</p>
      <p class="small">Price range method: ${esc(m.interval.method)}.</p></div>`;
    requestAnimationFrame(() => document.querySelectorAll(".fill").forEach((x) => (x.style.width = x.dataset.w + "%")));
  } catch (e) { $("#modelBody").innerHTML = ""; showMsg($("#modelError"), e.message); }
}

/* ---------- history ---------- */
async function initHistory() {
  try {
    const { items } = await api("/api/history");
    $("#histBody").innerHTML = items.length ? `<div class="table-scroll"><table><thead><tr><th>When (UTC)</th><th>Location</th><th class="num">Area</th><th class="num">Rate</th><th class="num">Estimated value</th><th></th></tr></thead><tbody>
      ${items.map((i) => `<tr><td>${esc(i.created_at.replace("T", " "))}</td><td>${esc(i.locality || i.latitude.toFixed(4) + ", " + i.longitude.toFixed(4))}</td><td class="num">${i.area_sqft.toLocaleString("en-IN")} sq.ft</td><td class="num">${fmtINR(i.predicted_price_per_sqft)}</td><td class="num">${fmtShort(i.estimated_total_value)}</td><td><a href="/result/${i.id}">Open</a></td></tr>`).join("")}</tbody></table></div>`
      : '<p>No valuations yet. <a href="/valuation">Start your first valuation</a>.</p>';
  } catch (e) { $("#histBody").innerHTML = ""; showMsg($("#histError"), e.message); }
}

/* ---------- admin ---------- */
function adminHeaders() { const t = $("#adminToken"); return t ? { "X-Admin-Token": t.value } : {}; }
async function loadAdminStats() {
  try {
    const s = await api("/api/admin/stats", { headers: adminHeaders() }), m = s.model;
    $("#adminStats").innerHTML = `<div class="panel"><h3>${s.dataset_rows ?? "?"}</h3><p class="small">records in dataset</p></div>
      <div class="panel"><h3>${m ? esc(m.selected_model) : "No model"}</h3><p class="small">${m ? "trained " + esc(m.trained_at) + (m.uses_synthetic_demo_data ? " (synthetic demo data)" : "") : "run python models/train_model.py"}</p></div>
      <div class="panel"><h3>${s.history_count}</h3><p class="small">predictions stored</p></div>`;
  } catch (e) { $("#adminStats").innerHTML = `<p class="msg">${esc(e.message)}</p>`; }
}
function initAdmin() {
  loadAdminStats();
  const tok = $("#adminToken"); if (tok) tok.addEventListener("change", loadAdminStats);
  $("#uploadBtn").onclick = async () => {
    const f = $("#csvFile").files[0], out = $("#uploadMsg"); if (!f) return showMsg(out, "Choose a CSV file first.");
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api("/api/admin/upload", { method: "POST", body: fd, headers: adminHeaders() }); showMsg(out, `${r.message} ${r.usable_rows} usable rows.`, true); loadAdminStats(); }
    catch (e) { showMsg(out, e.message); }
  };
  $("#retrainBtn").onclick = async () => {
    const b = $("#retrainBtn"), out = $("#retrainMsg"); b.disabled = true; showMsg(out, "Training… this can take a minute.", true);
    try { const r = await api("/api/admin/retrain", { method: "POST", headers: adminHeaders() }); showMsg(out, `${r.message} Selected: ${r.model.selected_model}.`, true); loadAdminStats(); }
    catch (e) { showMsg(out, e.message); } finally { b.disabled = false; }
  };
}
