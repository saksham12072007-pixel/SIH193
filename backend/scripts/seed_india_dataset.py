"""Seed a large, reproducible India-wide synthetic dataset for local validation.

This is intentionally labelled synthetic_demo. It is useful for exercising the
dashboard and model-serving contracts, but it is not a substitute for measured
Sentinel or weather observations. Pass a district GeoJSON exported from an
authoritative source with --districts-file, or the script will download the
open geohacker district catalogue.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import urllib.request
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.auth import hash_password  # noqa: E402
from app.db.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Advisory,
    Farmer,
    InstitutionalUser,
    MlPrediction,
    ModelEvaluationRun,
    Plot,
    PlotFeatures,
    SatelliteData,
    SmsLog,
)

DISTRICT_URL = "https://raw.githubusercontent.com/geohacker/india/master/district/india_district.geojson"
PREFIX = "india-demo-"
DEMO_EMAIL = "demo@krishimitra.example.com"
DEMO_PASSWORD = "DemoPassword123!"
CROPS = ("cotton", "maize", "wheat", "rice", "sugarcane", "groundnut", "soybean", "mustard")
SOILS = ("alluvial", "black", "red", "loamy", "sandy", "clay")
LANGUAGES = ("hi", "en", "mr", "bn", "te", "ta", "kn", "gu")
REALISTIC_CLASS_PATTERN = (
    "monitor",
    "monitor",
    "monitor",
    "no_action",
    "monitor",
    "irrigate_soon",
    "monitor",
    "monitor",
    "no_action",
    "irrigate_now",
)
STATE_NORMALIZATION = {
    "Orissa": "Odisha",
    "Uttaranchal": "Uttarakhand",
    "Dadra and Nagar Haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "Daman and Diu": "Dadra and Nagar Haveli and Daman and Diu",
}
SUPPLEMENTAL_DISTRICTS = {
    "Telangana": (
        "Adilabad", "Bhadradri Kothagudem", "Hanamkonda", "Hyderabad", "Jagtial",
        "Jangaon", "Jayashankar Bhupalpally", "Jogulamba Gadwal", "Kamareddy",
        "Karimnagar", "Khammam", "Komaram Bheem", "Mahabubabad", "Mahbubnagar",
        "Mancherial", "Medak", "Medchal-Malkajgiri", "Mulugu", "Nagarkurnool",
        "Nalgonda", "Narayanpet", "Nirmal", "Nizamabad", "Peddapalli",
        "Rajanna Sircilla", "Rangareddy", "Sangareddy", "Siddipet",
        "Suryapet", "Vikarabad", "Wanaparthy", "Warangal", "Yadadri Bhuvanagiri",
    ),
    "Ladakh": ("Leh", "Kargil"),
}


def _centroid(coordinates: object) -> tuple[float, float] | None:
    points: list[tuple[float, float]] = []

    def walk(value: object) -> None:
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
            points.append((float(value[0]), float(value[1])))
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(coordinates)
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def load_districts(path: Path | None) -> list[dict[str, object]]:
    if path:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(DISTRICT_URL, timeout=60) as response:
            payload = json.load(response)

    districts: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        state = STATE_NORMALIZATION.get(
            str(props.get("NAME_1") or props.get("state") or "").strip(),
            str(props.get("NAME_1") or props.get("state") or "").strip(),
        )
        district = str(props.get("NAME_2") or props.get("district") or "").strip()
        center = _centroid((feature.get("geometry") or {}).get("coordinates"))
        if not state or not district or not center or (state, district) in seen:
            continue
        seen.add((state, district))
        districts.append({"state": state, "district": district, "longitude": center[0], "latitude": center[1]})
    existing_pairs = {(item["state"], item["district"]) for item in districts}
    for state, names in SUPPLEMENTAL_DISTRICTS.items():
        for index, district in enumerate(names):
            if (state, district) not in existing_pairs:
                base_longitude, base_latitude = (77.5, 34.2) if state == "Ladakh" else (78.0, 18.0)
                districts.append({
                    "state": state,
                    "district": district,
                    "longitude": base_longitude + index * 0.03,
                    "latitude": base_latitude + index * 0.02,
                })
    if not districts:
        raise RuntimeError("The district catalogue did not contain usable state/district geometries")
    return districts


def _weather(rng: random.Random, day_index: int, state: str) -> tuple[float, float, float]:
    seasonal = 7.0 * math.sin((day_index / 365.0) * 2 * math.pi)
    state_offset = (sum(ord(char) for char in state) % 9) - 4
    rainfall = max(0.0, rng.gauss(6.0 + seasonal, 8.0))
    max_temp = rng.gauss(30.5 + state_offset * 0.35 - seasonal, 3.0)
    min_temp = max_temp - rng.uniform(7.0, 13.0)
    return round(rainfall, 2), round(max_temp, 2), round(min_temp, 2)


def _chunked_delete(session, model, column, ids: list[str], batch_size: int = 400) -> None:
    """Delete ... WHERE column IN (ids) in batches -- a single IN clause with
    thousands of ids (2500 plots x 14 advisories = 35000+) exceeds SQLite's
    bound-variable limit ("too many SQL variables"), so this re-run's own
    cleanup of the previous run's rows must chunk it, not just the insert."""
    for start in range(0, len(ids), batch_size):
        batch = ids[start:start + batch_size]
        session.query(model).filter(column.in_(batch)).delete(synchronize_session=False)


def _delete_previous(session) -> None:
    plot_ids = [row[0] for row in session.query(Plot.plot_id).filter(Plot.plot_id.like(f"{PREFIX}%")).all()]
    farmer_ids = [row[0] for row in session.query(Farmer.farmer_id).filter(Farmer.farmer_id.like(f"{PREFIX}%")).all()]
    if plot_ids:
        _chunked_delete(session, Advisory, Advisory.plot_id, plot_ids)
        _chunked_delete(session, MlPrediction, MlPrediction.plot_id, plot_ids)
        _chunked_delete(session, PlotFeatures, PlotFeatures.plot_id, plot_ids)
        _chunked_delete(session, SatelliteData, SatelliteData.plot_id, plot_ids)
        _chunked_delete(session, Plot, Plot.plot_id, plot_ids)
    if farmer_ids:
        _chunked_delete(session, SmsLog, SmsLog.farmer_id, farmer_ids)
        _chunked_delete(session, Farmer, Farmer.farmer_id, farmer_ids)
    session.query(ModelEvaluationRun).filter(ModelEvaluationRun.run_id.like(f"{PREFIX}%")).delete(synchronize_session=False)
    session.commit()


def seed(count: int, districts_file: Path | None, history_days: int) -> dict[str, int]:
    if not 2000 <= count <= 3000:
        raise ValueError("count must be between 2000 and 3000")
    districts = load_districts(districts_file)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    rng = random.Random(20260908)
    # Anchoring history to the real current date (not a fixed past date) keeps
    # the seeded advisory trend ending "today" no matter when this re-runs --
    # a hardcoded date goes stale the moment it's in the past.
    today = date.today()
    try:
        _delete_previous(session)
        user = session.query(InstitutionalUser).filter_by(email=DEMO_EMAIL).first()
        if user is None:
            session.add(InstitutionalUser(
                user_id=str(uuid.uuid4()),
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                role="admin",
                assigned_geography={},
            ))

        farmers: list[Farmer] = []
        plots: list[Plot] = []
        for index in range(count):
            location = districts[index % len(districts)]
            farmer_id = f"{PREFIX}farmer-{index:05d}"
            plot_id = f"{PREFIX}plot-{index:05d}"
            crop = CROPS[index % len(CROPS)]
            soil = SOILS[(index * 3) % len(SOILS)]
            latitude = float(str(location["latitude"])) + rng.uniform(-0.08, 0.08)
            longitude = float(str(location["longitude"])) + rng.uniform(-0.08, 0.08)
            sowing = today - timedelta(days=35 + (index * 11) % 100)
            farmer = Farmer(
                farmer_id=farmer_id,
                phone_number=f"910{index:07d}",
                name=f"India Demo Farmer {index + 1:05d}",
                preferred_language=LANGUAGES[index % len(LANGUAGES)],
                state=str(location["state"]),
                district=str(location["district"]),
                consent_given_at=datetime.combine(sowing, time.min, tzinfo=timezone.utc),
                registration_channel="synthetic_demo",
                status="active",
            )
            plot = Plot(
                plot_id=plot_id,
                farmer_id=farmer_id,
                plot_nickname=f"{crop.title()} demo plot {index + 1}",
                location_point=f"POINT ({longitude:.6f} {latitude:.6f})",
                location_precision="synthetic_centroid_jitter",
                village_name=f"Demo village {index % 20 + 1}",
                crop_type=crop,
                plot_size_declared=round(rng.uniform(1.0, 12.0), 2),
                sowing_date=sowing,
                soil_texture=soil,
                soil_awc={"sandy": 0.10, "red": 0.14, "black": 0.20, "clay": 0.22, "alluvial": 0.18, "loamy": 0.17}[soil],
                status="active",
                data_status="available",
                last_ingestion_at=datetime.combine(today, time.min, tzinfo=timezone.utc),
            )
            farmers.append(farmer)
            plots.append(plot)
        session.add_all(farmers)
        session.add_all(plots)
        session.flush()

        raw_rows: list[SatelliteData] = []
        feature_rows: list[PlotFeatures] = []
        prediction_rows: list[MlPrediction] = []
        advisory_rows: list[Advisory] = []
        for index, plot in enumerate(plots):
            state = plot.farmer.state or "India"
            crop_factor = (index % 9) / 100
            base_ndvi = 0.42 + crop_factor
            base_nir = 0.48 + crop_factor
            rainfall_by_day: dict[date, float] = {}
            for offset in range(history_days):
                obs_day = today - timedelta(days=history_days - 1 - offset)
                rainfall, temp_max, temp_min = _weather(rng, offset + index, state)
                rainfall_by_day[obs_day] = rainfall
                ndvi = max(0.18, min(0.88, base_ndvi + 0.10 * math.sin(offset / 12) + rng.gauss(0, 0.025)))
                nir = max(0.20, min(0.92, base_nir + 0.08 * math.sin(offset / 14) + rng.gauss(0, 0.02)))
                if offset % 6 == 0:
                    raw_rows.append(SatelliteData(
                        satellite_id=f"{PREFIX}s1-{index:05d}-{offset:03d}",
                        plot_id=plot.plot_id,
                        data_source="sentinel1",
                        data_type="sar",
                        value=f"VV:{-13.0 + ndvi * 3:.3f},VH:{-22.0 + ndvi * 4:.3f}",
                        observation_date=datetime.combine(obs_day, time.min, tzinfo=timezone.utc),
                        quality_flag="synthetic_demo",
                        cloud_coverage=0.0,
                    ))
                if offset % 5 == 0:
                    raw_rows.extend([
                        SatelliteData(
                            satellite_id=f"{PREFIX}s2-ndvi-{index:05d}-{offset:03d}",
                            plot_id=plot.plot_id,
                            data_source="sentinel2",
                            data_type="ndvi",
                            value=f"{ndvi:.4f}",
                            observation_date=datetime.combine(obs_day, time.min, tzinfo=timezone.utc),
                            quality_flag="synthetic_demo",
                            cloud_coverage=round(rng.uniform(0, 18), 1),
                        ),
                        SatelliteData(
                            satellite_id=f"{PREFIX}s2-nir-{index:05d}-{offset:03d}",
                            plot_id=plot.plot_id,
                            data_source="sentinel2",
                            data_type="nir",
                            value=f"{nir:.4f}",
                            observation_date=datetime.combine(obs_day, time.min, tzinfo=timezone.utc),
                            quality_flag="synthetic_demo",
                            cloud_coverage=round(rng.uniform(0, 18), 1),
                        ),
                    ])
                raw_rows.append(SatelliteData(
                    satellite_id=f"{PREFIX}weather-{index:05d}-{offset:03d}",
                    plot_id=plot.plot_id,
                    data_source="weather",
                    data_type="weather",
                    value=f"rainfall:{rainfall},temp_max:{temp_max},temp_min:{temp_min}",
                    observation_date=datetime.combine(obs_day, time.min, tzinfo=timezone.utc),
                    quality_flag="synthetic_demo",
                ))
                if offset >= history_days - 30:
                    feature_rows.append(PlotFeatures(
                        plot_id=plot.plot_id,
                        obs_date=obs_day,
                        vv_db=-13.0 + ndvi * 3,
                        vh_db=-22.0 + ndvi * 4,
                        delta_vv_7d=-0.15 + rng.uniform(-0.2, 0.2),
                        delta_vh_7d=-0.1 + rng.uniform(-0.2, 0.2),
                        ndvi=ndvi,
                        ndwi=max(-0.2, min(0.8, ndvi - 0.1)),
                        evi=max(-0.2, min(1.0, ndvi * 1.1)),
                        savi=max(-0.2, min(1.0, ndvi * 1.05)),
                        delta_ndvi_7d=rng.uniform(-0.04, 0.04),
                        delta_ndvi_14d=rng.uniform(-0.08, 0.08),
                        rainfall_1d=rainfall,
                        rainfall_3d=round(rainfall * 1.9, 2),
                        rainfall_7d=round(rainfall * 4.2, 2),
                        rainfall_14d=round(rainfall * 7.8, 2),
                        rain_forecast_48h=round(max(0, rng.gauss(8, 5)), 2),
                        et0=round(max(2, temp_max / 7), 3),
                        kc=0.9,
                        etc=round(max(2, temp_max / 7) * 0.9, 3),
                        lst=temp_max,
                        smap_sm=round(max(0.05, min(0.45, 0.14 + ndvi * 0.18)), 4),
                        crop_stage="vegetative" if offset < 20 else "mid_season",
                        soil_moisture_label=round(max(0.05, min(0.45, 0.10 + ndvi * 0.22)), 4),
                        label_source="water_balance",
                    ))
            for day_offset in range(14):
                obs_day = today - timedelta(days=13 - day_offset)
                created_at = datetime.combine(obs_day, time(12), tzinfo=timezone.utc)
                advisory_class = REALISTIC_CLASS_PATTERN[(index + day_offset // 3) % len(REALISTIC_CLASS_PATTERN)]
                prediction_id = f"{PREFIX}prediction-{index:05d}-{day_offset:02d}"
                advisory_id = f"{PREFIX}advisory-{index:05d}-{day_offset:02d}"
                # Irrigation-risk (nir_percent) responds inversely to that
                # day's actual rainfall, using the same saturation curve as
                # the real production model (WaterBalanceBucketModel.estimate_stress:
                # rainfall_impact = min(rainfall_mm / 10, 1)) -- more rain,
                # lower risk -- so this stays physically consistent instead of
                # varying independently of the weather it's supposed to reflect.
                day_rainfall = rainfall_by_day.get(obs_day, 0.0)
                rainfall_impact = min(day_rainfall / 10, 1)
                nir_percent = max(15.0, min(85.0, base_nir * 100 - rainfall_impact * 20))
                prediction_rows.append(MlPrediction(
                    prediction_id=prediction_id,
                    plot_id=plot.plot_id,
                    model_version="synthetic-demo-v1",
                    stage1_soil_moisture_estimate=round(12 + (index % 35), 2),
                    stage1_cwsi_estimate=round(0.2 + (index % 50) / 100, 2),
                    advisory_class=advisory_class,
                    confidence_score=round(0.72 + (index % 20) / 100, 3),
                    reason_code="synthetic_demo",
                    input_feature_snapshot={
                        "dataset": "synthetic_demo",
                        "provider": "synthetic_sentinel_weather",
                        "nir_percent": round(nir_percent, 2),
                        "rainfall_mm": day_rainfall,
                        "sentinel1": True,
                        "sentinel2": True,
                        "weather": True,
                    },
                    predicted_at=created_at,
                ))
                advisory_rows.append(Advisory(
                    advisory_id=advisory_id,
                    plot_id=plot.plot_id,
                    prediction_id=prediction_id,
                    advisory_class=advisory_class,
                    language_used=plot.farmer.preferred_language,
                    sms_sent=False,
                    ivr_triggered=False,
                    created_at=created_at,
                ))
        for rows in (raw_rows, feature_rows, prediction_rows, advisory_rows):
            for start in range(0, len(rows), 5000):
                session.add_all(rows[start:start + 5000])
                session.flush()
        session.add(ModelEvaluationRun(
            run_id=f"{PREFIX}evaluation-v1",
            model_version="synthetic-demo-v1",
            trained_at=datetime.combine(today, time.min, tzinfo=timezone.utc),
            agro_zone="india-wide-synthetic-validation",
            rmse=0.074,
            mae=0.052,
            r2=0.80,
            accuracy=0.86,
            precision_score=0.78,
            recall=0.88,
            f1=0.83,
            fpr=0.05,
            passed_fpr_threshold=True,
            shap_feature_importance={"ndvi": 0.28, "vv_db": 0.22, "rainfall_7d": 0.18, "soil_texture": 0.14},
            notes="Synthetic validation rows only; not a production model evaluation.",
        ))
        session.commit()
        return {
            "farmers": len(farmers),
            "plots": len(plots),
            "districts": len({(item["state"], item["district"]) for item in districts}),
            "states": len({item["state"] for item in districts}),
            "satellite_weather_rows": len(raw_rows),
            "feature_rows": len(feature_rows),
            "predictions": len(prediction_rows),
            "advisories": len(advisory_rows),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=2500)
    parser.add_argument("--history-days", type=int, default=90)
    parser.add_argument("--districts-file", type=Path)
    args = parser.parse_args()
    print(json.dumps(seed(args.count, args.districts_file, args.history_days), indent=2))


if __name__ == "__main__":
    main()
