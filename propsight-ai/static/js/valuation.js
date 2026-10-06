/* Valuation flow: pick location -> confirm -> enter area -> predict. */
(function () {
  const $ = (s) => document.querySelector(s);
  let map, sel = null, confirmed = false;
  const msg1 = $("#msg1"), msg2 = $("#msg2");

  function setSelected(lat, lng, label) {
    sel = { lat, lng }; confirmed = false; lockStep2();
    $("#selLat").textContent = lat.toFixed(6); $("#selLng").textContent = lng.toFixed(6);
    $("#selName").textContent = label || "Pinned location"; $("#confirmBtn").disabled = false;
    $("#analysis").hidden = true; showMsg(msg1, "");
  }
  function lockStep2() { $("#step2").classList.add("locked"); $("#step2").setAttribute("aria-disabled", "true"); $("#areaInput").disabled = true; $("#predictBtn").disabled = true; }
  function unlockStep2() { $("#step2").classList.remove("locked"); $("#step2").removeAttribute("aria-disabled"); $("#areaInput").disabled = false; $("#predictBtn").disabled = false; $("#areaInput").focus(); }

  async function pick(lat, lng, label) { map.setMarker(lat, lng, false); setSelected(lat, lng, label); }

  async function search() {
    const q = $("#searchInput").value.trim(), list = $("#searchResults");
    if (q.length < 2) { showMsg(msg1, "Type at least 2 characters to search for a location."); return; }
    showMsg(msg1, ""); list.hidden = true;
    try {
      const res = map.provider === "google" ? await map.search(q) : (await api("/api/geocode?q=" + encodeURIComponent(q))).results;
      if (!res.length) { showMsg(msg1, "No places matched that search. Try a nearby locality or click directly on the map."); return; }
      list.innerHTML = res.map((r, i) => `<li><button type="button" data-i="${i}">${esc(r.label)}${r.source ? ` <small>(${esc(r.source)})</small>` : ""}</button></li>`).join(""); list.hidden = false;
      list.onclick = (e) => {
        const b = e.target.closest("button"); if (!b) return; const r = res[+b.dataset.i];
        map.goTo(r.latitude, r.longitude, 15); pick(r.latitude, r.longitude, r.label.split(",").slice(0, 2).join(",")); list.hidden = true;
      };
    } catch (e) { showMsg(msg1, "Search is unavailable right now. You can still click the map to place the marker."); }
  }

  async function confirm() {
    if (!sel) return showMsg(msg1, "Please select a valid property location.");
    const btn = $("#confirmBtn"); btn.disabled = true; btn.textContent = "Analysing…";
    try {
      const r = await api("/api/location", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ latitude: sel.lat, longitude: sel.lng }) });
      confirmed = true; $("#selName").textContent = r.location.address;
      const chips = Object.entries(r.counts).map(([k, v]) => `<span class="chip">${esc(k.replace("_nearby", ""))}: <strong>${v}</strong></span>`).join("");
      $("#analysis").innerHTML = `<strong>Location confirmed.</strong> ${r.is_demo ? '<span class="tag-demo">Demo facility data</span>' : ""}<div class="chips">${chips}</div>
        <span class="small">Nearest metro: ${r.features.metro_distance_km?.toFixed(1) ?? "n/a"} km · railway: ${r.features.railway_distance_km?.toFixed(1) ?? "n/a"} km · major road: ${r.features.major_road_distance_km?.toFixed(1) ?? "n/a"} km</span>`;
      $("#analysis").hidden = false; unlockStep2();
    } catch (e) { showMsg(msg1, e.message); }
    finally { btn.disabled = false; btn.textContent = "Confirm Location"; }
  }

  async function predict() {
    showMsg(msg2, "");
    if (!sel || !confirmed) return showMsg(msg2, "Please select and confirm a valid property location first.");
    const raw = $("#areaInput").value.trim(), area = Number(raw);
    if (!raw) return showMsg(msg2, "Please enter the property area in sq.ft.");
    if (!isFinite(area) || area <= 0) return showMsg(msg2, "Please enter a property area greater than 0 sq.ft.");
    if (area > 100000) return showMsg(msg2, "Property area looks too large. Please enter a value up to 1,00,000 sq.ft.");
    const btn = $("#predictBtn"); btn.disabled = true; btn.textContent = "Estimating…";
    try {
      const r = await api("/api/predict", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ latitude: sel.lat, longitude: sel.lng, area_sqft: area }) });
      if (r.id) location.href = "/result/" + r.id;
      else { sessionStorage.setItem("ps_last", JSON.stringify(r)); location.href = "/result/0"; }
    } catch (e) { showMsg(msg2, e.message); btn.disabled = false; btn.textContent = "Predict Property Value"; }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    map = await PropMap.create($("#map"), (lat, lng) => setSelected(lat, lng));
    if (map.provider === "osm") $("#mapHint").textContent = "Using the built-in OpenStreetMap view (add GOOGLE_MAPS_API_KEY to .env for Google Maps). Click the map to place the marker, drag to pan, scroll to zoom.";
    $("#searchBtn").onclick = search;
    $("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
    $("#confirmBtn").onclick = confirm; $("#predictBtn").onclick = predict;
    $("#areaInput").addEventListener("keydown", (e) => { if (e.key === "Enter") predict(); });
    $("#locateBtn").onclick = () => {
      if (!navigator.geolocation) return showMsg(msg1, "Your browser cannot share its location. Search or click the map instead.");
      navigator.geolocation.getCurrentPosition((p) => { map.goTo(p.coords.latitude, p.coords.longitude, 16); pick(p.coords.latitude, p.coords.longitude, "My location"); },
        () => showMsg(msg1, "Location permission was denied. Search or click the map instead."), { timeout: 8000 });
    };
  });
})();
