"""Feature engineering shared by training and serving (single source of truth)."""
import math
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

# radii (km) used for the *_nearby count features
RADII_KM = {"schools": 1, "hospitals": 3, "markets": 2, "malls": 3, "parks": 1, "banks": 2, "restaurants": 1}

LOCATION_FEATURES = [
    "schools_nearby", "hospitals_nearby", "markets_nearby", "malls_nearby", "parks_nearby",
    "banks_nearby", "restaurants_nearby",
    "metro_distance_km", "railway_distance_km", "highway_distance_km",
    "major_road_distance_km", "airport_distance_km",
    "commercial_score", "development_score",
]
# Features fed to the model: only what is known at prediction time (location + area).
MODEL_FEATURES = ["area_sqft"] + LOCATION_FEATURES + ["local_average_price"]

FEATURE_LABELS = {
    "area_sqft": "Property size", "schools_nearby": "Schools within 1 km",
    "hospitals_nearby": "Hospitals within 3 km", "markets_nearby": "Markets within 2 km",
    "malls_nearby": "Malls within 3 km", "parks_nearby": "Parks within 1 km",
    "banks_nearby": "Banks within 2 km", "restaurants_nearby": "Restaurants within 1 km",
    "metro_distance_km": "Metro distance", "railway_distance_km": "Railway station distance",
    "highway_distance_km": "Highway distance", "major_road_distance_km": "Major road distance",
    "airport_distance_km": "Airport distance", "commercial_score": "Commercial activity",
    "development_score": "Development level", "local_average_price": "Nearby property prices",
}
FEATURE_GROUPS = {
    "Location / Historical Market Data": ["local_average_price"],
    "Connectivity": ["highway_distance_km", "major_road_distance_km"],
    "Nearby Facilities": ["schools_nearby", "hospitals_nearby", "markets_nearby", "malls_nearby",
                          "parks_nearby", "banks_nearby", "restaurants_nearby"],
    "Commercial Development": ["commercial_score", "development_score"],
    "Transport": ["metro_distance_km", "railway_distance_km", "airport_distance_km"],
    "Property Size": ["area_sqft"],
}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def composite_scores(c):
    """Heuristic 0-1 scores from facility counts/distances (documented in README)."""
    commercial = 1 - math.exp(-(0.04 * c["markets_nearby"] + 0.10 * c["malls_nearby"]
                                + 0.03 * c["banks_nearby"] + 0.015 * c["restaurants_nearby"]))
    dev_raw = (0.12 * c["schools_nearby"] + 0.04 * c["hospitals_nearby"] + 0.15 * c["parks_nearby"]
               + 0.6 * math.exp(-c["major_road_distance_km"] / 1.5))
    return round(commercial, 3), round(1 - math.exp(-dev_raw), 3)


class LocalMarket:
    """Inverse-distance weighted price of the k nearest training properties (local_average_price)."""

    def __init__(self, k=10):
        self.k = k

    def fit(self, df):
        self.lat = df["latitude"].to_numpy(float)
        self.lon = df["longitude"].to_numpy(float)
        self.price = df["price_per_sqft"].to_numpy(float)
        return self

    def query(self, lat, lon, exclude_self=False):
        d = haversine_km(lat, lon, self.lat, self.lon)
        order = np.argsort(d)
        if exclude_self:
            order = order[1:]
        idx = order[: self.k]
        w = 1.0 / (d[idx] + 0.2)
        avg = float(np.sum(w * self.price[idx]) / np.sum(w))
        n_2km = int(np.sum(d <= 2.0)) - (1 if exclude_self else 0)
        return avg, max(n_2km, 0), float(d[idx].max())


class Preprocessor:
    """Imputation + local-market feature + coverage area + training distribution (preprocessor.pkl)."""

    def fit(self, train_df):
        self.features = list(MODEL_FEATURES)
        self.market = LocalMarket().fit(train_df)
        X = self._build(train_df, exclude_self=True)
        self.imputer = SimpleImputer(strategy="median").fit(X)
        Xi = pd.DataFrame(self.imputer.transform(X), columns=self.features)
        self.sorted_values = {c: np.sort(Xi[c].to_numpy()) for c in self.features}
        m = 0.3  # about 30 km margin around the training data
        self.coverage = {"lat_min": float(train_df.latitude.min() - m), "lat_max": float(train_df.latitude.max() + m),
                         "lon_min": float(train_df.longitude.min() - m), "lon_max": float(train_df.longitude.max() + m)}
        return self

    def _build(self, df, exclude_self=False):
        df = df.copy()
        df["local_average_price"] = [self.market.query(a, b, exclude_self)[0] for a, b in zip(df.latitude, df.longitude)]
        for col in self.features:
            if col not in df:
                df[col] = np.nan
        return df[self.features].astype(float)

    def transform(self, df, exclude_self=False):
        X = self._build(df, exclude_self)
        return pd.DataFrame(self.imputer.transform(X), columns=self.features, index=df.index)

    def in_coverage(self, lat, lon):
        c = self.coverage
        return c["lat_min"] <= lat <= c["lat_max"] and c["lon_min"] <= lon <= c["lon_max"]

    def percentile(self, feature, value):
        arr = self.sorted_values[feature]
        return float(100.0 * np.searchsorted(arr, value, side="right") / len(arr))
