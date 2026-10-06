"""Loads the trained model and turns (lat, lon, area) into a valuation."""
import json
import os
import threading

import joblib
import pandas as pd

from services.facility_service import get_facility_features
from services.feature_engineering import FEATURE_LABELS, MODEL_FEATURES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(ROOT, "models", "property_price_model.pkl")
PRE_PATH = os.path.join(ROOT, "models", "preprocessor.pkl")
METRICS_PATH = os.path.join(ROOT, "models", "metrics.json")


class ModelNotReady(RuntimeError):
    pass


class OutsideCoverage(ValueError):
    pass


def _level(v, lo, hi, labels=("Low", "Medium", "High")):
    return labels[0] if v < lo else labels[1] if v < hi else labels[2]


class Predictor:
    def __init__(self):
        self._lock = threading.Lock()
        self.model = self.pre = self.info = None

    def load(self):
        with self._lock:
            if not (os.path.exists(MODEL_PATH) and os.path.exists(PRE_PATH) and os.path.exists(METRICS_PATH)):
                raise ModelNotReady("The valuation model has not been trained yet. Run: python models/train_model.py")
            try:
                self.model, self.pre = joblib.load(MODEL_PATH), joblib.load(PRE_PATH)
                with open(METRICS_PATH) as fh:
                    self.info = json.load(fh)
            except Exception as exc:
                self.model = None
                raise ModelNotReady(f"The valuation model could not be loaded ({type(exc).__name__}). Retrain it with python models/train_model.py") from exc

    def ensure(self):
        if self.model is None:
            self.load()

    def model_info(self):
        self.ensure()
        return self.info

    def analyse(self, lat, lon):
        """Facility analysis only (used by /api/location)."""
        self.ensure()
        if not self.pre.in_coverage(lat, lon):
            raise OutsideCoverage("This location is outside the area covered by the training data, so no reliable estimate can be made.")
        return get_facility_features(lat, lon)

    def predict(self, lat, lon, area, facility=None):
        facility = facility or self.analyse(lat, lon)
        feats = dict(facility["features"], area_sqft=area, latitude=lat, longitude=lon)
        X = self.pre.transform(pd.DataFrame([feats]))
        rate = float(max(self.model.predict(X)[0], 0))
        iv = self.info["interval"]
        lo_rate, hi_rate = rate * iv["ratio_low"], rate * iv["ratio_high"]
        avg, n_comp, radius = self.pre.market.query(lat, lon)
        factors = []
        for f in MODEL_FEATURES:
            if f == "area_sqft":
                continue
            raw = feats[f] if f != "local_average_price" else avg
            pct = self.pre.percentile(f, float(X.iloc[0][f]))
            good_when_high = not f.endswith("_distance_km")
            factors.append({"feature": f, "label": FEATURE_LABELS[f], "value": None if raw is None or raw != raw else round(float(raw), 3),
                            "percentile": round(pct), "higher_is_better": good_when_high,
                            "imputed": feats.get(f) is None or feats.get(f) != feats.get(f)})
        c, d = feats["commercial_score"], feats["development_score"]
        return {
            "latitude": lat, "longitude": lon, "area_sqft": area,
            "predicted_price_per_sqft": round(rate), "estimated_property_value": round(rate * area),
            "lower_estimate": round(lo_rate * area), "upper_estimate": round(hi_rate * area),
            "lower_rate": round(lo_rate), "upper_rate": round(hi_rate),
            "model": self.info["selected_model"], "trained_at": self.info["trained_at"],
            "range_method": iv["method"], "facility_source": facility["source"],
            "is_demo": bool(facility["is_demo"] or self.info.get("uses_synthetic_demo_data")),
            "warnings": facility["warnings"] + (["The model was trained on SYNTHETIC DEMO data, so this figure is not a real market estimate."]
                                                if self.info.get("uses_synthetic_demo_data") else []),
            "summary": {"Location Quality": _level((c + d) / 2, 0.45, 0.7),
                        "Road Connectivity": _level(-feats["major_road_distance_km"], -1.5, -0.5, ("Limited", "Good", "Excellent")),
                        "Commercial Activity": _level(c, 0.33, 0.66)},
            "local_market": {"average_rate": round(avg), "comparables_within_2km": n_comp,
                             "trend": "Not available: the dataset has no time dimension"},
            "factors": factors, "features": {k: facility["features"][k] for k in facility["features"]},
            "group_importance": self.info["feature_group_importance"],
            "importance_note": self.info["importance_note"],
            "facilities": facility["facilities"],
        }


predictor = Predictor()
