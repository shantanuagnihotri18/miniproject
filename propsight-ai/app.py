"""PropSight AI - Flask application."""
import hmac
import math
import os
import shutil
import threading
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

from database import db  # noqa: E402
from models import train_model  # noqa: E402
from services.location_service import LocationError, geocode, reverse_geocode, validate_coordinates  # noqa: E402
from services.prediction_service import ModelNotReady, OutsideCoverage, predictor  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
MAX_AREA = 100000
train_lock = threading.Lock()
db.init_db()


# ---------- helpers ----------
def err(message, status=400, **extra):
    return jsonify({"error": message, **extra}), status


def parse_area(value):
    if value is None or value == "":
        raise ValueError("Please enter a property area greater than 0 sq.ft.")
    if isinstance(value, bool):
        raise ValueError("Please enter a valid property area in sq.ft.")
    try:
        area = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        raise ValueError("Please enter a valid property area in sq.ft.")
    if not math.isfinite(area) or area <= 0:
        raise ValueError("Please enter a property area greater than 0 sq.ft.")
    if area > MAX_AREA:
        raise ValueError(f"Property area looks too large. Please enter a value up to {MAX_AREA:,} sq.ft.")
    return area


def require_admin():
    token = os.getenv("ADMIN_TOKEN", "")
    if not token:
        return None
    given = request.headers.get("X-Admin-Token") or request.form.get("token") or ""
    if not hmac.compare_digest(given, token):
        return err("Admin token missing or incorrect.", 401)
    return None


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise LocationError("Please send the request as a JSON object.")
    return data


# ---------- pages ----------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/valuation")
def valuation():
    return render_template("valuation.html")


@app.get("/result/<int:pid>")
def result_page(pid):
    return render_template("result.html", prediction_id=pid)


@app.get("/model")
def model_page():
    return render_template("model.html")


@app.get("/history")
def history_page():
    return render_template("history.html")


@app.get("/admin")
def admin_page():
    return render_template("admin.html", token_required=bool(os.getenv("ADMIN_TOKEN")))


# ---------- API ----------
@app.get("/api/config")
def api_config():
    # A browser Maps key is public by design: restrict it by HTTP referrer in Google Cloud Console.
    return jsonify({"google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY", ""), "default_center": {"lat": 26.4499, "lng": 80.3319}})


@app.get("/api/geocode")
def api_geocode():
    try:
        return jsonify({"results": geocode(request.args.get("q", ""))})
    except LocationError as e:
        return err(str(e))


@app.post("/api/location")
def api_location():
    try:
        data = json_body()
        lat, lon = validate_coordinates(data.get("latitude"), data.get("longitude"))
        facility = predictor.analyse(lat, lon)
        loc = reverse_geocode(lat, lon)
        counts = {k: v for k, v in facility["features"].items() if k.endswith("_nearby")}
        return jsonify({"latitude": lat, "longitude": lon, "location": loc, "counts": counts, "features": facility["features"],
                        "facility_source": facility["source"], "is_demo": facility["is_demo"], "warnings": facility["warnings"],
                        "nearest": facility["facilities"][:8]})
    except OutsideCoverage as e:
        return err(str(e), 422)
    except LocationError as e:
        return err(str(e))
    except ModelNotReady as e:
        return err(str(e), 503)
    except Exception:
        app.logger.exception("location analysis failed")
        return err("We could not analyse this location right now. Please try again.", 500)


@app.post("/api/predict")
def api_predict():
    try:
        data = json_body()
        lat, lon = validate_coordinates(data.get("latitude"), data.get("longitude"))
        area = parse_area(data.get("area_sqft"))
        facility = predictor.analyse(lat, lon)
        result = predictor.predict(lat, lon, area, facility)
        location = reverse_geocode(lat, lon)
        result["location"] = location
        try:
            pid, created = db.save_prediction(result, location, facility["facilities"])
            result["id"], result["created_at"] = pid, created
        except Exception:
            app.logger.exception("could not store prediction")
            result["id"] = None
            result["warnings"].append("The result could not be saved to history (database problem).")
        return jsonify(result)
    except OutsideCoverage as e:
        return err(str(e), 422)
    except (LocationError, ValueError) as e:
        return err(str(e))
    except ModelNotReady as e:
        return err(str(e), 503)
    except Exception:
        app.logger.exception("prediction failed")
        return err("Something went wrong while estimating the value. Please try again.", 500)


@app.get("/api/prediction/<int:pid>")
def api_prediction(pid):
    try:
        res = db.get_prediction(pid)
    except Exception:
        return err("History is temporarily unavailable.", 500)
    return jsonify(res) if res else err("Prediction not found.", 404)


@app.get("/api/history")
def api_history():
    try:
        return jsonify({"items": db.history()})
    except Exception:
        return err("History is temporarily unavailable.", 500)


@app.get("/api/model-info")
def api_model_info():
    try:
        return jsonify(predictor.model_info())
    except ModelNotReady as e:
        return err(str(e), 503)


@app.get("/api/admin/stats")
def api_admin_stats():
    denied = require_admin()
    if denied:
        return denied
    n = None
    try:
        with open(train_model.DATA_PATH, encoding="utf-8") as fh:
            n = max(sum(1 for _ in fh) - 1, 0)
    except OSError:
        pass
    try:
        info = predictor.model_info()
    except ModelNotReady:
        info = None
    return jsonify({"dataset_rows": n, "model": info, "history_count": len(db.history(10000))})


@app.post("/api/admin/upload")
def api_admin_upload():
    denied = require_admin()
    if denied:
        return denied
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        return err("Please choose a .csv file.")
    tmp = os.path.join(train_model.ROOT, "uploads", "upload_tmp.csv")
    f.save(tmp)
    try:
        df, report = train_model.load_and_clean(tmp)
        if len(df) < 50:
            raise ValueError(f"Only {len(df)} usable rows after cleaning; at least 50 are needed.")
    except Exception as e:
        os.remove(tmp)
        return err(f"This CSV can't be used: {e}")
    if os.path.exists(train_model.DATA_PATH):
        shutil.copy(train_model.DATA_PATH, train_model.DATA_PATH.replace(".csv", f".backup_{datetime.now():%Y%m%d%H%M%S}.csv"))
    shutil.move(tmp, train_model.DATA_PATH)
    return jsonify({"message": "Dataset uploaded. Retrain the model to use it.", "usable_rows": len(df), "cleaning": report})


@app.post("/api/admin/retrain")
def api_admin_retrain():
    denied = require_admin()
    if denied:
        return denied
    if not train_lock.acquire(blocking=False):
        return err("Training is already running.", 409)
    try:
        info = train_model.train()
        predictor.load()
        return jsonify({"message": "Model retrained.", "model": info})
    except Exception as e:
        app.logger.exception("training failed")
        return err(f"Training failed: {e}", 500)
    finally:
        train_lock.release()


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return err("Endpoint not found.", 404)
    return render_template("index.html"), 404


@app.errorhandler(413)
def too_large(e):
    return err("That file is too large (20 MB maximum).", 413)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
