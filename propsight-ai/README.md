# PropSight AI
AI-Powered Property Valuation & Location Intelligence. Pin a property on a map, enter the area in sq.ft, get an estimated ₹/sq.ft, a total value, an uncertainty range and the factors the model relied on.

> **Read this first: the bundled data is synthetic.** `data/property_data.csv` is *generated* by `data/generate_demo_data.py` from an invented formula, and the facility data (schools, hospitals, metro, roads...) comes from a *simulated* demo generator, not real places. Predictions made with it are **not real market estimates**; the UI labels them "Demo data". Accurate real-world predictions need a sufficiently large dataset of reliable local property prices (thousands of recent listings or registered transactions with exact coordinates). Replace the CSV (or upload one on `/admin`) and retrain.

## 1. Overview
Flow: select location on map, confirm, enter area, backend computes location features, ML model predicts ₹/sq.ft, `value = rate x area`, dashboard, stored in SQLite history.

## 2. Features
Map search/click/marker (Google Maps, or a built-in OpenStreetMap fallback) · location analysis (facility counts, distances) · model comparison (Linear, Random Forest, Gradient Boosting, XGBoost if installed) · price range from held-out error · explainability (model feature importance + position vs training data) · prediction history · model performance page · admin CSV upload + retrain · input validation and friendly errors.

## 3. Technology stack
HTML5, CSS3, vanilla JavaScript · Python, Flask · pandas, NumPy, scikit-learn, XGBoost (optional) · SQLite (all SQL lives in `database/db.py`, so PostgreSQL/MySQL can replace it later). No JS frameworks, no Bootstrap/Tailwind.

## 4. Architecture
```
app.py                       Flask routes + validation
services/location_service    coordinate validation, geocoding (local gazetteer, optional Nominatim), reverse geocoding
services/facility_service    facility features: DEMO generator (default) or live OpenStreetMap/Overpass
services/feature_engineering shared feature definitions + Preprocessor (imputer, local-market feature, coverage area)
services/prediction_service  model loading, prediction, range, explanation
models/train_model.py        cleaning, training, comparison, saving, metrics.json
database/db.py, init_db.py   SQLite schema + parameterised queries
templates/, static/          pages, CSS, vanilla JS (map.js, valuation.js, main.js)
```

## 5. ML methodology
1. Clean: invalid coordinates/area/price dropped; `price_per_sqft` validated against `price/area` (recomputed if off by >5%); duplicates and robust-z outliers removed; missing features median-imputed.
2. Features: `area_sqft`; facility counts (schools 1 km, hospitals 3 km, markets 2 km, malls 3 km, parks 1 km, banks 2 km, restaurants 1 km); distances (metro, railway, highway, major road, airport); `commercial_score` and `development_score` (heuristic 0-1 composites of counts/distances); `local_average_price` (inverse-distance weighted ₹/sq.ft of the 10 nearest *training* properties, leave-one-out during training to avoid leakage). Latitude/longitude are not model inputs.
3. Split 70/15/15 (train/validation/test). **The model with the lowest validation RMSE is selected**; test metrics are reported separately. All numbers are computed from your data (`models/metrics.json`).
4. Saved: `models/property_price_model.pkl`, `models/preprocessor.pkl`.
5. **Price range:** on the held-out test set, take actual/predicted ratios; their 10th and 90th percentiles are `ratio_low`/`ratio_high`. Range = predicted rate x ratio x area (about an 80% empirical interval). It reflects typical model error on your data, not every factor that moves a price.
6. **Explainability:** `feature_importances_` (or standardised |coefficients| for linear models) grouped into Location/Market data, Connectivity, Nearby facilities, Commercial development, Transport, Size. This is *model feature importance*, not causal impact. "Local historical trend" is shown as unavailable because the dataset has no time dimension.

## 6. Dataset format (`data/property_data.csv`)
Required: `latitude, longitude, area_sqft` and `price` and/or `price_per_sqft`. Optional/kept for future use: `city, locality, property_type, bedrooms, bathrooms, property_age, data_source`. Location features (`schools_nearby, hospitals_nearby, markets_nearby, malls_nearby, parks_nearby, banks_nearby, restaurants_nearby, metro_distance_km, railway_distance_km, airport_distance_km, highway_distance_km, major_road_distance_km, commercial_score, development_score`) are computed automatically if the columns are absent.
**Important:** features must be computed the same way at training and prediction time. If you train on real data with real POI features, set `FACILITY_SOURCE=overpass` (or add your own provider in `facility_service.py`) so serving matches training.

## 7-9. Installation, environment, database
```bash
python -m venv venv
venv\Scripts\activate          # Windows (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
python database/init_db.py
```
`.env`: `GOOGLE_MAPS_API_KEY` (optional), `FACILITY_SOURCE=demo|overpass`, `ONLINE_GEOCODING=1|0`, `DATABASE_PATH`, `ADMIN_TOKEN` (optional), `FLASK_DEBUG`. Never commit `.env`. A browser Maps key is visible to the browser by design; restrict it by HTTP referrer in Google Cloud Console. Without a key the app uses the built-in OpenStreetMap view (tiles and Nominatim search need internet; local-locality search works offline).

## 10. Train the model
```bash
python data/generate_demo_data.py   # only to regenerate the SYNTHETIC demo data
python models/train_model.py
```
## 11. Run
```bash
python app.py     # http://127.0.0.1:5000
```
## 12. Using the website
**Property Valuation**: search or click the map, **Confirm Location**, enter the area, **Predict Property Value**. Also `/model` (metrics), `/history`, `/admin` (upload CSV, retrain, stats).

## 13. API
| Method | Path | Notes |
|---|---|---|
| GET | `/`, `/valuation`, `/result/<id>`, `/model`, `/history`, `/admin` | pages |
| POST | `/api/location` | `{latitude, longitude}` returns address, facility counts, features |
| POST | `/api/predict` | `{latitude, longitude, area_sqft}` returns `predicted_price_per_sqft, estimated_property_value, lower_estimate, upper_estimate, model` plus `id`, factors, facilities, warnings |
| GET | `/api/prediction/<id>` | stored result |
| GET | `/api/history` | recent predictions |
| GET | `/api/model-info` | metrics, selected model, last training date |
| GET | `/api/geocode?q=` | location search fallback |
| GET/POST | `/api/admin/stats`, `/api/admin/upload`, `/api/admin/retrain` | admin (X-Admin-Token if `ADMIN_TOKEN` set) |

Errors return `{"error": "..."}`: 400 bad input, 422 outside training coverage, 503 model missing.

## 14. Limitations
- Demo data is synthetic; demo facilities are simulated; demo metro/rail/road/airport coordinates are approximate and illustrative.
- Live Overpass mode uses way centres for road distances (approximation), depends on OpenStreetMap completeness and rate limits, and has not been tested against your data.
- Not captured: condition, legal status, construction quality, floor, exact micro-location, negotiation, market timing. Locations outside the training area are refused.
- Admin has no real authentication (optional token only). Do not expose it publicly.

## 15. Future improvements
Real transaction/listing pipeline with timestamps (price trend), real road geometry/PostGIS, spatial cross-validation, property type/age inputs, conformal prediction intervals, SHAP, proper admin auth, PostgreSQL.
