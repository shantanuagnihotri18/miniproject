/* Map layer: Google Maps when a key is configured, otherwise a dependency-free OpenStreetMap tile map. */
(function () {
  const TILE = 256;
  const clampLat = (v) => Math.max(-85, Math.min(85, v));

  function pinSvg() {
    return '<svg viewBox="0 0 30 40" width="30" height="40"><path d="M15 1C7 1 1 7 1 14.5 1 25 15 39 15 39s14-14 14-24.500C29 7 23 1 15 1z" fill="#E8A317" stroke="#12212B" stroke-width="2"/><circle cx="15" cy="14.5" r="5" fill="#12212B"/></svg>';
  }

  /* ---------- OpenStreetMap fallback (vanilla JS slippy map) ---------- */
  class OsmMap {
    constructor(el, center, zoom, onPick) {
      this.provider = "osm"; this.el = el; this.onPick = onPick;
      this.lat = center.lat; this.lng = center.lng; this.z = zoom; this.marker = null; this.tiles = new Map(); this.failed = 0;
      el.innerHTML = "";
      this.root = document.createElement("div"); this.root.className = "osm";
      this.root.innerHTML = '<div class="zoom"><button type="button" aria-label="Zoom in">+</button><button type="button" aria-label="Zoom out">−</button></div><div class="attrib">© OpenStreetMap contributors</div>';
      this.layer = document.createElement("div"); this.root.prepend(this.layer);
      this.pin = document.createElement("div"); this.pin.className = "mpin"; this.pin.innerHTML = pinSvg(); this.pin.hidden = true;
      this.root.appendChild(this.pin); el.appendChild(this.root);
      const [zi, zo] = this.root.querySelectorAll(".zoom button");
      zi.onclick = (e) => { e.stopPropagation(); this.setZoom(this.z + 1); };
      zo.onclick = (e) => { e.stopPropagation(); this.setZoom(this.z - 1); };
      this.bind(); new ResizeObserver(() => this.render()).observe(el); this.render();
    }
    size() { return { w: this.el.clientWidth, h: this.el.clientHeight }; }
    toWorld(lat, lng, z = this.z) {
      const s = TILE * Math.pow(2, z), r = clampLat(lat) * Math.PI / 180;
      return { x: (lng + 180) / 360 * s, y: (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * s };
    }
    fromWorld(x, y, z = this.z) {
      const s = TILE * Math.pow(2, z), n = Math.PI - 2 * Math.PI * y / s;
      return { lat: 180 / Math.PI * Math.atan(Math.sinh(n)), lng: x / s * 360 - 180 };
    }
    render() {
      const { w, h } = this.size(); if (!w) return;
      const c = this.toWorld(this.lat, this.lng), tlx = c.x - w / 2, tly = c.y - h / 2, n = Math.pow(2, this.z);
      const want = new Set();
      for (let tx = Math.floor(tlx / TILE); tx <= Math.floor((tlx + w) / TILE); tx++) {
        for (let ty = Math.floor(tly / TILE); ty <= Math.floor((tly + h) / TILE); ty++) {
          if (ty < 0 || ty >= n) continue;
          const wx = ((tx % n) + n) % n, key = this.z + "/" + tx + "/" + ty; want.add(key);
          let img = this.tiles.get(key);
          if (!img) {
            img = new Image(); img.alt = ""; img.draggable = false;
            img.onerror = () => { img.style.display = "none"; if (++this.failed > 2) this.offline(); };
            img.src = "https://tile.openstreetmap.org/" + this.z + "/" + wx + "/" + ty + ".png";
            this.layer.appendChild(img); this.tiles.set(key, img);
          }
          img.style.left = Math.round(tx * TILE - tlx) + "px"; img.style.top = Math.round(ty * TILE - tly) + "px";
        }
      }
      for (const [k, img] of this.tiles) if (!want.has(k)) { img.remove(); this.tiles.delete(k); }
      this.placePin();
    }
    offline() {
      if (this.root.classList.contains("offline")) return;
      this.root.classList.add("offline");
      const d = document.createElement("div"); d.className = "offline-note";
      d.textContent = "Map tiles need an internet connection. Search and clicking still work."; this.root.appendChild(d);
    }
    placePin() {
      if (!this.marker) { this.pin.hidden = true; return; }
      const { w, h } = this.size(), c = this.toWorld(this.lat, this.lng), p = this.toWorld(this.marker.lat, this.marker.lng);
      this.pin.style.left = Math.round(p.x - c.x + w / 2) + "px"; this.pin.style.top = Math.round(p.y - c.y + h / 2) + "px"; this.pin.hidden = false;
    }
    bind() {
      let drag = null;
      this.root.addEventListener("pointerdown", (e) => {
        if (e.target.closest(".zoom")) return;
        drag = { x: e.clientX, y: e.clientY, lat: this.lat, lng: this.lng, moved: false }; this.root.setPointerCapture(e.pointerId);
      });
      this.root.addEventListener("pointermove", (e) => {
        if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true;
        if (!drag.moved) return;
        const c = this.toWorld(drag.lat, drag.lng), p = this.fromWorld(c.x - dx, c.y - dy);
        this.lat = clampLat(p.lat); this.lng = p.lng; this.render();
      });
      this.root.addEventListener("pointerup", (e) => {
        if (!drag) return; const was = drag; drag = null;
        if (!was.moved && !e.target.closest(".zoom")) {
          const r = this.root.getBoundingClientRect(), c = this.toWorld(this.lat, this.lng);
          const p = this.fromWorld(c.x + (e.clientX - r.left) - r.width / 2, c.y + (e.clientY - r.top) - r.height / 2);
          this.setMarker(p.lat, p.lng, true);
        }
      });
      this.root.addEventListener("wheel", (e) => { e.preventDefault(); this.setZoom(this.z + (e.deltaY < 0 ? 1 : -1)); }, { passive: false });
    }
    setZoom(z) { this.z = Math.max(3, Math.min(18, z)); this.render(); }
    setMarker(lat, lng, notify) { this.marker = { lat, lng }; this.placePin(); if (notify) this.onPick(lat, lng); }
    goTo(lat, lng, zoom) { this.lat = lat; this.lng = lng; if (zoom) this.z = zoom; this.render(); }
  }

  /* ---------- Google Maps ---------- */
  class GoogleMap {
    constructor(el, center, zoom, onPick) {
      this.provider = "google"; this.onPick = onPick;
      this.map = new google.maps.Map(el, { center, zoom, mapTypeControl: false, streetViewControl: false, fullscreenControl: true });
      this.geocoder = new google.maps.Geocoder(); this.marker = null;
      this.map.addListener("click", (e) => this.setMarker(e.latLng.lat(), e.latLng.lng(), true));
    }
    setMarker(lat, lng, notify) {
      const pos = { lat, lng };
      if (!this.marker) {
        this.marker = new google.maps.Marker({ position: pos, map: this.map, draggable: true, animation: google.maps.Animation.DROP });
        this.marker.addListener("dragend", (e) => this.onPick(e.latLng.lat(), e.latLng.lng()));
      } else this.marker.setPosition(pos);
      if (notify) this.onPick(lat, lng);
    }
    goTo(lat, lng, zoom) { this.map.setCenter({ lat, lng }); if (zoom) this.map.setZoom(zoom); }
    search(q) {
      return new Promise((resolve, reject) => this.geocoder.geocode({ address: q, region: "IN" }, (res, status) => {
        if (status === "OK") resolve(res.slice(0, 6).map((r) => ({ label: r.formatted_address, latitude: r.geometry.location.lat(), longitude: r.geometry.location.lng() })));
        else if (status === "ZERO_RESULTS") resolve([]); else reject(new Error(status));
      }));
    }
  }

  function loadGoogle(key) {
    return new Promise((resolve, reject) => {
      window.gm_authFailure = () => reject(new Error("auth"));
      window.__gmReady = () => resolve();
      const s = document.createElement("script");
      s.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent(key) + "&callback=__gmReady";
      s.async = true; s.onerror = () => reject(new Error("load")); document.head.appendChild(s);
      setTimeout(() => reject(new Error("timeout")), 8000);
    });
  }

  window.PropMap = {
    async create(el, onPick) {
      let cfg = { google_maps_api_key: "", default_center: { lat: 26.4499, lng: 80.3319 } };
      try { cfg = await (await fetch("/api/config")).json(); } catch (e) { /* use defaults */ }
      const c = cfg.default_center;
      if (cfg.google_maps_api_key) {
        try { await loadGoogle(cfg.google_maps_api_key); return new GoogleMap(el, c, 12, onPick); }
        catch (e) { console.warn("Google Maps unavailable, using OpenStreetMap fallback:", e.message); }
      }
      return new OsmMap(el, c, 12, onPick);
    },
  };
})();
