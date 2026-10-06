"""Coordinate validation, geocoding and reverse geocoding."""
import json
import math
import os
import urllib.parse
import urllib.request

from services.feature_engineering import haversine_km

# Approximate locality centroids for offline search / reverse lookup (illustrative, not survey-grade).
GAZETTEER = [
    ("Kalyanpur", 26.5040, 80.2680), ("Swaroop Nagar", 26.4780, 80.3330), ("Civil Lines", 26.4720, 80.3560),
    ("Kakadeo", 26.4780, 80.2970), ("Arya Nagar", 26.4720, 80.3390), ("Govind Nagar", 26.4420, 80.3190),
    ("Kidwai Nagar", 26.4300, 80.3390), ("Barra", 26.4180, 80.3180), ("Panki", 26.4730, 80.2470),
    ("Vikas Nagar", 26.5006, 80.2880), ("Juhi", 26.4450, 80.3550), ("Gwaltoli", 26.4570, 80.3590),
    ("Rawatpur", 26.4700, 80.3170), ("Kanpur Central Station", 26.4540, 80.3498), ("IIT Kanpur", 26.5123, 80.2329),
    ("Mall Road", 26.4690, 80.3480),
]


class LocationError(ValueError):
    pass


def validate_coordinates(lat, lon):
    try:
        if isinstance(lat, bool) or isinstance(lon, bool):
            raise TypeError
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise LocationError("Please select a valid property location.")
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise LocationError("The coordinates are not valid. Please select a valid property location.")
    return lat, lon


def _nominatim(path, params):
    if os.getenv("ONLINE_GEOCODING", "1") != "1":
        return None
    url = f"https://nominatim.openstreetmap.org/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "PropSightAI/1.0 (local prototype)"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def geocode(query):
    q = (query or "").strip()
    if len(q) < 2:
        raise LocationError("Type at least 2 characters to search.")
    ql = q.lower().replace(",", " ")
    results = [{"label": f"{n}, Kanpur, Uttar Pradesh (approx. centre)", "latitude": la, "longitude": lo, "source": "local gazetteer"}
               for n, la, lo in GAZETTEER if n.lower() in ql or any(w and w in n.lower() for w in ql.split() if len(w) > 3)]
    online = _nominatim("search", {"q": q, "format": "json", "limit": 5, "countrycodes": "in"})
    for r in online or []:
        results.append({"label": r["display_name"], "latitude": float(r["lat"]), "longitude": float(r["lon"]), "source": "OpenStreetMap Nominatim"})
    return results[:8]


def reverse_geocode(lat, lon):
    name, dist = min(((n, float(haversine_km(lat, lon, la, lo))) for n, la, lo in GAZETTEER), key=lambda x: x[1])
    info = {"address": f"Near {name}, Kanpur, Uttar Pradesh", "city": "Kanpur", "locality": name, "source": "local gazetteer (approximate)"} \
        if dist <= 4 else {"address": f"{lat:.5f}, {lon:.5f}", "city": None, "locality": None, "source": "coordinates only"}
    data = _nominatim("reverse", {"lat": lat, "lon": lon, "format": "json", "zoom": 16})
    if data and data.get("display_name"):
        a = data.get("address", {})
        info = {"address": data["display_name"], "city": a.get("city") or a.get("town") or a.get("state_district"),
                "locality": a.get("suburb") or a.get("neighbourhood") or a.get("village") or info["locality"],
                "source": "OpenStreetMap Nominatim"}
    return info
