"""Generate SYNTHETIC DEMO data -> data/property_data.csv

!!! These prices are INVENTED by a simple formula + noise so the prototype can run.
!!! They are NOT real market prices. Replace data/property_data.csv with a real dataset
!!! (or upload one on /admin) and retrain before relying on any number.
"""
import math
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from services.facility_service import get_facility_features  # noqa: E402
from services.location_service import GAZETTEER  # noqa: E402
from services.feature_engineering import haversine_km  # noqa: E402

N = 1500
rng = np.random.default_rng(7)
TYPES = ["Apartment", "Builder Floor", "Independent House", "Plot"]
rows = []
for _ in range(N):
    lat, lon = rng.uniform(26.38, 26.55), rng.uniform(80.20, 80.43)
    f = get_facility_features(lat, lon, "demo")["features"]
    ptype = rng.choice(TYPES, p=[0.45, 0.2, 0.25, 0.1])
    area = float(np.clip(rng.lognormal(math.log(1100), 0.35), 300, 5000).round())
    age = 0 if ptype == "Plot" else int(rng.integers(0, 30))
    rate = (2200 + 3800 * f["commercial_score"] + 1800 * f["development_score"]
            + 900 * math.exp(-f["metro_distance_km"] / 2.5) + 600 * math.exp(-f["railway_distance_km"] / 3)
            + 500 * math.exp(-f["major_road_distance_km"] / 1.0))
    rate *= {"Apartment": 1.0, "Builder Floor": 1.05, "Independent House": 1.08, "Plot": 0.85}[ptype]
    rate *= 1 + 0.10 * np.clip((1000 - area) / 1000, -0.5, 0.5)
    rate *= 1 - 0.006 * age
    rate *= rng.lognormal(0, 0.07)
    rate = round(rate)
    name, dist = min(((n, float(haversine_km(lat, lon, la, lo))) for n, la, lo in GAZETTEER), key=lambda x: x[1])
    beds = 0 if ptype == "Plot" else int(np.clip(round(area / 450), 1, 5))
    rows.append(dict(latitude=round(lat, 6), longitude=round(lon, 6), city="Kanpur", locality=name,
                     property_type=ptype, area_sqft=area, price=round(rate * area), price_per_sqft=rate,
                     bedrooms=beds, bathrooms=0 if ptype == "Plot" else max(1, beds - 1), property_age=age, **f,
                     data_source="synthetic_demo"))
df = pd.DataFrame(rows)
cols = ["latitude", "longitude", "city", "locality", "property_type", "area_sqft", "price", "price_per_sqft", "bedrooms",
        "bathrooms", "property_age", "schools_nearby", "hospitals_nearby", "markets_nearby", "malls_nearby", "parks_nearby",
        "banks_nearby", "restaurants_nearby", "metro_distance_km", "railway_distance_km", "airport_distance_km",
        "highway_distance_km", "major_road_distance_km", "commercial_score", "development_score", "data_source"]
df = df[cols]
# deliberately dirty a few cells/rows so the cleaning step has something to do
for i in rng.choice(N, 12, replace=False):
    df.loc[i, rng.choice(["schools_nearby", "metro_distance_km", "commercial_score"])] = np.nan
df.loc[3, "area_sqft"] = -50
df.loc[9, "latitude"] = 95.0
df.loc[17, "price_per_sqft"] = 0
df.to_csv(os.path.join(ROOT, "data", "property_data.csv"), index=False)
print("wrote", len(df), "SYNTHETIC rows")
