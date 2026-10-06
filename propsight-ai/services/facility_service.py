"""Facility / connectivity feature service.

FACILITY_SOURCE=demo     -> deterministic DEMO points of interest (NOT real places). Works offline.
FACILITY_SOURCE=overpass -> live OpenStreetMap data through the Overpass API (needs internet).

IMPORTANT: the ML model must be trained on features produced by the same source it is served with.
"""
import math
import os
from functools import lru_cache

import numpy as np
from services.feature_engineering import RADII_KM, composite_scores, haversine_km

CITY_CENTER = (26.4600, 80.3450)
CELL = 0.005  # degrees (~0.55 km) grid for the demo generator
TYPES = ["school", "college", "hospital", "clinic", "market", "mall", "restaurant", "bank", "park"]
BASE_RATE = {"school": 0.35, "college": 0.05, "hospital": 0.12, "clinic": 0.40, "market": 0.25,
             "mall": 0.04, "restaurant": 0.90, "bank": 0.30, "park": 0.15}
HUBS = [(26.4780, 80.3330), (26.4720, 80.3560), (26.4780, 80.2970), (26.5040, 80.2680), (26.4420, 80.3190)]

# ILLUSTRATIVE anchor coordinates (approximate!). Replace with real GIS data before real use.
METRO = [("IIT Kanpur (approx.)", 26.5126, 80.2320), ("Kalyanpur (approx.)", 26.5020, 80.2640),
         ("SPM Hospital (approx.)", 26.4960, 80.2900), ("Rawatpur (approx.)", 26.4700, 80.3170),
         ("Moti Jheel (approx.)", 26.4780, 80.3260), ("Kanpur Central (approx.)", 26.4540, 80.3480)]
RAILWAY = [("Kanpur Central", 26.4540, 80.3498), ("Kanpur Anwarganj", 26.4410, 80.3240),
           ("Govindpuri", 26.4390, 80.3640), ("Panki Dham", 26.4640, 80.2500)]
AIRPORT = [("Kanpur Airport (Chakeri)", 26.4044, 80.4101)]
HIGHWAYS = [[(26.4000, 80.4400), (26.4300, 80.4000), (26.4560, 80.3600), (26.4700, 80.3300), (26.4900, 80.2700), (26.5100, 80.2100)]]
MAJOR_ROADS = [[(26.4540, 80.3550), (26.4660, 80.3480), (26.4780, 80.3400)],
               [(26.4400, 80.3300), (26.4560, 80.3350), (26.4780, 80.3330), (26.4960, 80.3040)],
               [(26.4500, 80.3100), (26.4700, 80.3170), (26.4960, 80.2900)]]

TYPE_TO_FEATURE = {"school": "schools", "hospital": "hospitals", "market": "markets", "mall": "malls",
                   "park": "parks", "bank": "banks", "restaurant": "restaurants"}


def _density(lat, lon):
    d = haversine_km(lat, lon, *CITY_CENTER)
    dens = 0.25 + 0.75 * math.exp(-(d / 6.0) ** 2)
    for h in HUBS:
        dens += 0.35 * math.exp(-(haversine_km(lat, lon, *h) / 1.5) ** 2)
    return dens


@lru_cache(maxsize=20000)
def _cell_pois(cx, cy):
    out = []
    dens = _density(cy * CELL, cx * CELL)
    for ti, t in enumerate(TYPES):
        rng = np.random.default_rng([abs(cx), abs(cy), ti, 12345, 1 if cx < 0 else 0, 1 if cy < 0 else 0])
        n = rng.poisson(BASE_RATE[t] * dens)
        for i in range(n):
            lat = (cy + rng.random()) * CELL
            lon = (cx + rng.random()) * CELL
            out.append((f"Demo {t.title()} #{abs(cx) % 100}{abs(cy) % 100}-{i + 1}", t, lat, lon))
    return tuple(out)


def demo_pois(lat, lon, radius_km=3.0):
    cx0, cy0 = int(math.floor(lon / CELL)), int(math.floor(lat / CELL))
    span = int(radius_km / 0.55) + 2
    res = []
    for cx in range(cx0 - span, cx0 + span + 1):
        for cy in range(cy0 - span, cy0 + span + 1):
            for name, t, plat, plon in _cell_pois(cx, cy):
                d = float(haversine_km(lat, lon, plat, plon))
                if d <= radius_km:
                    res.append({"name": name, "type": t, "latitude": plat, "longitude": plon, "distance_km": round(d, 3)})
    return sorted(res, key=lambda r: r["distance_km"])


def _point_dist(lat, lon, pts):
    best = min(pts, key=lambda p: haversine_km(lat, lon, p[1], p[2]))
    return float(haversine_km(lat, lon, best[1], best[2])), best


def _polyline_dist(lat, lon, lines):
    """Distance (km) to the nearest segment of any polyline (local equirectangular projection)."""
    kx = 111.32 * math.cos(math.radians(lat))
    ky = 110.57
    best = 1e9
    for line in lines:
        for (a1, o1), (a2, o2) in zip(line[:-1], line[1:]):
            x1, y1, x2, y2 = (o1 - lon) * kx, (a1 - lat) * ky, (o2 - lon) * kx, (a2 - lat) * ky
            dx, dy = x2 - x1, y2 - y1
            t = 0 if dx == dy == 0 else max(0, min(1, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(x1 + t * dx, y1 + t * dy))
    return best


def _features_from_pois(pois, transport):
    counts = {f: 0 for f in RADII_KM}
    for p in pois:
        f = TYPE_TO_FEATURE.get(p["type"])
        if f and p["distance_km"] <= RADII_KM[f]:
            counts[f] += 1
    feats = {f"{k}_nearby": v for k, v in counts.items()}
    feats.update(transport)
    feats["commercial_score"], feats["development_score"] = composite_scores(feats)
    return feats


def _demo(lat, lon):
    pois = demo_pois(lat, lon, 3.0)
    transport = {
        "metro_distance_km": round(_point_dist(lat, lon, METRO)[0], 3),
        "railway_distance_km": round(_point_dist(lat, lon, RAILWAY)[0], 3),
        "airport_distance_km": round(_point_dist(lat, lon, AIRPORT)[0], 3),
        "highway_distance_km": round(_polyline_dist(lat, lon, HIGHWAYS), 3),
        "major_road_distance_km": round(_polyline_dist(lat, lon, MAJOR_ROADS), 3),
    }
    named = []
    for label, pts in (("Metro station", METRO), ("Railway station", RAILWAY), ("Airport", AIRPORT)):
        d, p = _point_dist(lat, lon, pts)
        named.append({"name": p[0], "type": label.lower(), "latitude": p[1], "longitude": p[2], "distance_km": round(d, 3)})
    return pois, transport, named


OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OSM_TAGS = {"school": '["amenity"="school"]', "college": '["amenity"~"college|university"]',
            "hospital": '["amenity"="hospital"]', "clinic": '["amenity"~"clinic|doctors"]',
            "market": '["amenity"="marketplace"]', "mall": '["shop"="mall"]',
            "restaurant": '["amenity"="restaurant"]', "bank": '["amenity"="bank"]', "park": '["leisure"="park"]'}


def _overpass(lat, lon):
    """Live OSM data. Road distances use way *centres* (approximation); see README."""
    parts = [f'nwr(around:3000,{lat},{lon}){tag};' for tag in OSM_TAGS.values()]
    q = "[out:json][timeout:25];(" + "".join(parts) + ");out center 400;"
    data = _post_json(OVERPASS_URL, {"data": q})
    pois = []
    for el in data.get("elements", []):
        plat, plon = el.get("lat") or el.get("center", {}).get("lat"), el.get("lon") or el.get("center", {}).get("lon")
        if plat is None:
            continue
        tags = el.get("tags", {})
        t = next((k for k, v in OSM_TAGS.items() if _tag_match(tags, v)), None)
        if t:
            pois.append({"name": tags.get("name", f"Unnamed {t}"), "type": t, "latitude": plat, "longitude": plon,
                         "distance_km": round(float(haversine_km(lat, lon, plat, plon)), 3)})

    def nearest(selector, radius):
        d = _post_json(OVERPASS_URL, {"data": f"[out:json][timeout:25];nwr(around:{radius},{lat},{lon}){selector};out center 60;"})
        pts = [(e.get("tags", {}).get("name", "Unnamed"), e.get("lat") or e.get("center", {}).get("lat"),
                e.get("lon") or e.get("center", {}).get("lon")) for e in d.get("elements", [])]
        pts = [p for p in pts if p[1] is not None]
        return _point_dist(lat, lon, pts) if pts else (None, None)

    transport, named = {}, []
    for key, sel, rad, label in (("metro_distance_km", '["station"="subway"]', 30000, "metro station"),
                                 ("railway_distance_km", '["railway"="station"]', 30000, "railway station"),
                                 ("airport_distance_km", '["aeroword"="aerodrome"]'.replace("aeroword", "aeroway"), 80000, "airport"),
                                 ("highway_distance_km", '["highway"~"^(motorway|trunk)$"]', 30000, "highway"),
                                 ("major_road_distance_km", '["highway"~"^(primary|secondary)$"]', 10000, "major road")):
        d, p = nearest(sel, rad)
        transport[key] = None if d is None else round(d, 3)
        if p:
            named.append({"name": p[0], "type": label, "latitude": p[1], "longitude": p[2], "distance_km": round(d, 3)})
    return sorted(pois, key=lambda r: r["distance_km"]), transport, named


def _tag_match(tags, selector):
    import re
    m = re.match(r'\["(\w+)"(=|~)"(.+)"\]', selector)
    key, op, val = m.groups()
    v = tags.get(key)
    return v is not None and (v == val if op == "=" else re.search(val, v) is not None)


def get_facility_features(lat, lon, source=None):
    """Return {features, facilities, source, is_demo, warnings}."""
    source = (source or os.getenv("FACILITY_SOURCE", "demo")).lower()
    warnings = []
    if source == "overpass":
        try:
            pois, transport, named = _overpass(lat, lon)
        except Exception as exc:  # network failure, rate limit...
            warnings.append(f"Live facility data unavailable ({type(exc).__name__}); used DEMO facility data instead.")
            source = "demo"
            pois, transport, named = _demo(lat, lon)
    else:
        source = "demo"
        pois, transport, named = _demo(lat, lon)
    feats = _features_from_pois(pois, transport)
    for k, v in feats.items():
        if v is None:
            warnings.append(f"Missing data for {k}; the model will use a typical value.")
    if source == "demo":
        warnings.append("Facility data is simulated DEMO data, not real places.")
    return {"features": feats, "facilities": (named + pois)[:60], "source": source, "is_demo": source == "demo",
            "warnings": warnings}


def _post_json(url, data):
    import json
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(), {"User-Agent": "PropSightAI/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())
