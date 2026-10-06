"""Train, compare and save the property price model.

    python models/train_model.py [path/to/data.csv]
"""
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from services.feature_engineering import (FEATURE_GROUPS, LOCATION_FEATURES, MODEL_FEATURES, Preprocessor)  # noqa: E402

DATA_PATH = os.path.join(ROOT, "data", "property_data.csv")
MODEL_PATH = os.path.join(ROOT, "models", "property_price_model.pkl")
PRE_PATH = os.path.join(ROOT, "models", "preprocessor.pkl")
METRICS_PATH = os.path.join(ROOT, "models", "metrics.json")


def load_and_clean(path):
    """Returns (clean_df, report). Never silently invents prices."""
    df = pd.read_csv(path)
    rep = {"rows_loaded": int(len(df)), "dropped": {}, "fixed": {}}
    for c in ("latitude", "longitude", "area_sqft"):
        if c not in df:
            raise ValueError(f"Dataset must contain a '{c}' column.")
    if "price" not in df and "price_per_sqft" not in df:
        raise ValueError("Dataset needs 'price' and/or 'price_per_sqft'.")
    for c in df.columns:
        if c not in ("city", "locality", "property_type", "data_source"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    def drop(mask, why):
        nonlocal df
        n = int(mask.sum())
        if n:
            rep["dropped"][why] = rep["dropped"].get(why, 0) + n
            df = df[~mask]

    drop(df.latitude.isna() | df.longitude.isna() | ~df.latitude.between(-90, 90) | ~df.longitude.between(-180, 180), "invalid coordinates")
    drop(df.area_sqft.isna() | (df.area_sqft <= 0) | (df.area_sqft > 100000), "invalid area")
    if "price" in df and "price_per_sqft" in df:   # validate rate against price/area
        calc = df.price / df.area_sqft
        bad = df.price_per_sqft.notna() & calc.notna() & ((df.price_per_sqft - calc).abs() / calc > 0.05)
        rep["fixed"]["price_per_sqft recomputed from price/area (mismatch > 5%)"] = int(bad.sum())
        df.loc[bad, "price_per_sqft"] = calc[bad]
        df["price_per_sqft"] = df.price_per_sqft.fillna(calc)
    elif "price" in df:
        df["price_per_sqft"] = df.price / df.area_sqft
    else:
        df["price"] = df.price_per_sqft * df.area_sqft
    drop(df.price_per_sqft.isna() | (df.price_per_sqft < 300) | (df.price_per_sqft > 200000), "invalid price_per_sqft")
    before = len(df)
    df = df.drop_duplicates(subset=["latitude", "longitude", "area_sqft", "price_per_sqft"])
    if before - len(df):
        rep["dropped"]["duplicates"] = int(before - len(df))
    lp = np.log(df.price_per_sqft)
    mad = np.median(np.abs(lp - lp.median())) or 1e-9
    drop(np.abs(lp - lp.median()) / (1.4826 * mad) > 6, "price outliers (robust z > 6)")
    # location features missing entirely -> compute them (demo/overpass per FACILITY_SOURCE)
    missing = [c for c in LOCATION_FEATURES if c not in df]
    if missing:
        from services.facility_service import get_facility_features
        rep["fixed"]["location features computed by facility_service"] = missing
        feats = [get_facility_features(a, b)["features"] for a, b in zip(df.latitude, df.longitude)]
        df = pd.concat([df.reset_index(drop=True), pd.DataFrame(feats)[missing]], axis=1)
    rep["missing_values_before_imputation"] = {c: int(df[c].isna().sum()) for c in LOCATION_FEATURES if c in df and df[c].isna().any()}
    rep["rows_clean"] = int(len(df))
    return df.reset_index(drop=True), rep


def _metrics(y, p):
    return {"MAE": float(mean_absolute_error(y, p)), "RMSE": float(np.sqrt(mean_squared_error(y, p))), "R2": float(r2_score(y, p))}


def candidates():
    models = {
        "Linear Regression": make_pipeline(StandardScaler(), LinearRegression()),
        "Random Forest": RandomForestRegressor(n_estimators=300, min_samples_leaf=2, n_jobs=-1, random_state=42),
        "Gradient Boosting": GradientBoostingRegressor(n_estimators=300, learning_rate=0.05, max_depth=3, subsample=0.8, random_state=42),
    }
    try:
        from xgboost import XGBRegressor
        models["XGBoost"] = XGBRegressor(n_estimators=400, learning_rate=0.05, max_depth=4, subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=2)
    except Exception:
        pass
    return models


def importance(model, X, y):
    est = model[-1] if hasattr(model, "steps") else model
    if hasattr(est, "feature_importances_"):
        imp = np.asarray(est.feature_importances_, float)
    else:  # linear model: |standardised coefficient|
        imp = np.abs(est.coef_)
    imp = imp / imp.sum()
    per_feature = dict(zip(MODEL_FEATURES, map(float, imp)))
    groups = {g: float(sum(per_feature[f] for f in fs)) for g, fs in FEATURE_GROUPS.items()}
    return per_feature, dict(sorted(groups.items(), key=lambda kv: -kv[1]))


def train(data_path=DATA_PATH):
    df, report = load_and_clean(data_path)
    if len(df) < 50:
        raise ValueError(f"Only {len(df)} usable rows; need at least 50 to train.")
    train_df, rest = train_test_split(df, test_size=0.30, random_state=42)
    val_df, test_df = train_test_split(rest, test_size=0.50, random_state=42)
    pre = Preprocessor().fit(train_df)
    Xtr, Xva, Xte = pre.transform(train_df, exclude_self=True), pre.transform(val_df), pre.transform(test_df)
    ytr, yva, yte = train_df.price_per_sqft, val_df.price_per_sqft, test_df.price_per_sqft

    results, fitted = {}, {}
    for name, model in candidates().items():
        model.fit(Xtr, ytr)
        fitted[name] = model
        results[name] = {"validation": _metrics(yva, model.predict(Xva)), "test": _metrics(yte, model.predict(Xte))}
    best = min(results, key=lambda n: results[n]["validation"]["RMSE"])
    model = fitted[best]

    ratio = yte.to_numpy() / np.maximum(model.predict(Xte), 1)
    q10, q90 = np.quantile(ratio, [0.10, 0.90])
    per_feature, groups = importance(model, Xte, yte)
    is_demo = bool("data_source" in df and (df["data_source"].astype(str) == "synthetic_demo").mean() > 0.5)

    joblib.dump(model, MODEL_PATH)
    joblib.dump(pre, PRE_PATH)
    info = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selected_model": best, "selection_rule": "lowest RMSE on the validation split",
        "models": results, "n_records": report["rows_clean"],
        "n_train": len(train_df), "n_validation": len(val_df), "n_test": len(test_df),
        "cleaning": report, "uses_synthetic_demo_data": is_demo,
        "interval": {"method": "10th/90th percentile of actual/predicted ratio on the held-out test set (about 80% of test properties fell inside)",
                     "ratio_low": float(q10), "ratio_high": float(q90), "n": int(len(ratio))},
        "feature_importance": per_feature, "feature_group_importance": groups,
        "importance_note": "Model feature importance (how much the model relies on a feature), not causal impact.",
        "features": MODEL_FEATURES, "data_path": os.path.relpath(data_path, ROOT),
    }
    with open(METRICS_PATH, "w") as fh:
        json.dump(info, fh, indent=2)
    return info


if __name__ == "__main__":
    info = train(sys.argv[1] if len(sys.argv) > 1 else DATA_PATH)
    print(f"Records used: {info['n_records']}  (train/val/test = {info['n_train']}/{info['n_validation']}/{info['n_test']})")
    print("Cleaning:", json.dumps(info["cleaning"]["dropped"]))
    for n, r in info["models"].items():
        v = r["validation"]
        print(f"{n:20s} val MAE={v['MAE']:.0f}  RMSE={v['RMSE']:.0f}  R2={v['R2']:.3f}" + ("   <- selected" if n == info["selected_model"] else ""))
    if info["uses_synthetic_demo_data"]:
        print("NOTE: trained on SYNTHETIC DEMO data. Outputs are not real market estimates.")
