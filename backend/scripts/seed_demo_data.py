"""Seed a repeatable, clearly marked dataset for local dashboard demos.

This script only targets the configured development database. It is idempotent:
running it again updates no existing production records and does not duplicate
the demo rows.
"""

from datetime import date, timedelta
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.auth import hash_password  # noqa: E402
from app.db.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Advisory, Farmer, InstitutionalUser, MlPrediction, ModelEvaluationRun, Plot, PlotFeatures  # noqa: E402
from app.utils.time import utc_now  # noqa: E402

DEMO_EMAIL = "demo@krishimitra.example.com"
DEMO_PASSWORD = "DemoPassword123!"
DEMO_PREFIX = "demo-"
DEMO_STATE = "Maharashtra"
DEMO_DISTRICT = "Yavatmal"
DEMO_VILLAGES = tuple(f"Demo village {index + 1}" for index in range(10))
DEMO_CROPS = ("cotton", "maize", "wheat", "rice", "sugarcane", "groundnut")
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


def get_or_create(session, model, key, values):
    instance = session.get(model, key)
    if instance is None:
        instance = model(**values)
        session.add(instance)
    return instance


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        # Rebuild only rows owned by this local demo dataset so the seed remains
        # deterministic when the pilot scope changes.
        demo_advisories = [
            item.advisory_id
            for item in session.query(Advisory.advisory_id)
            .filter(Advisory.advisory_id.like(f"{DEMO_PREFIX}%"))
            .all()
        ]
        if demo_advisories:
            session.query(Advisory).filter(Advisory.advisory_id.in_(demo_advisories)).delete(
                synchronize_session=False
            )
        session.query(MlPrediction).filter(
            MlPrediction.prediction_id.like(f"{DEMO_PREFIX}%")
        ).delete(synchronize_session=False)
        session.query(PlotFeatures).filter(
            PlotFeatures.plot_id.like(f"{DEMO_PREFIX}%")
        ).delete(synchronize_session=False)
        session.query(Plot).filter(Plot.plot_id.like(f"{DEMO_PREFIX}%")).delete(
            synchronize_session=False
        )
        session.query(Farmer).filter(Farmer.farmer_id.like(f"{DEMO_PREFIX}%")).delete(
            synchronize_session=False
        )
        session.query(ModelEvaluationRun).filter(
            ModelEvaluationRun.run_id.like(f"{DEMO_PREFIX}%")
        ).delete(synchronize_session=False)

        user = session.query(InstitutionalUser).filter_by(email=DEMO_EMAIL).first()
        if user is None:
            session.add(InstitutionalUser(
                user_id=str(uuid.uuid4()),
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                role="admin",
                assigned_geography={},
            ))

        plot_ids = []
        farmers = []
        for index in range(50):
            farmer_id = f"{DEMO_PREFIX}farmer-{index:02d}"
            farmer = get_or_create(session, Farmer, farmer_id, {
                "farmer_id": farmer_id,
                "phone_number": f"900000{index:04d}",
                "name": f"Demo Farmer {index + 1}",
                "preferred_language": ("mr", "hi", "en")[index % 3],
                "state": DEMO_STATE,
                "district": DEMO_DISTRICT,
                "registration_channel": "demo",
                "status": "active",
            })
            farmers.append(farmer)

        for index in range(70):
            farmer = farmers[index % len(farmers)]
            plot_id = f"{DEMO_PREFIX}plot-{index:02d}"
            plot = get_or_create(session, Plot, plot_id, {
                "plot_id": plot_id,
                "farmer_id": farmer.farmer_id,
                "plot_nickname": f"Demo plot {index + 1}",
                "village_name": DEMO_VILLAGES[index % len(DEMO_VILLAGES)],
                "crop_type": DEMO_CROPS[index % len(DEMO_CROPS)],
                "plot_size_declared": 2.5,
                "sowing_date": date.today() - timedelta(days=65),
                "soil_texture": "black",
                "soil_awc": 0.18,
                "status": "active",
                "data_status": "available",
            })
            plot.location_point = f"POINT ({78.0 + (index % 10) * 0.045:.6f} {20.15 + (index // 10) * 0.045:.6f})"
            plot_ids.append(plot_id)

        session.flush()
        observation_date = date.today()
        for index, plot_id in enumerate(plot_ids):
            session.add(PlotFeatures(
                plot_id=plot_id,
                obs_date=observation_date,
                vv_db=-12.0 + (index % 5),
                vh_db=-18.0 + (index % 4),
                delta_vv_7d=-0.4 + (index % 3) * 0.2,
                delta_ndvi_7d=-0.02 + (index % 4) * 0.01,
                ndvi=0.35 + (index % 5) * 0.05,
                rainfall_7d=2.0 + (index % 4) * 3.0,
                et0=4.8,
                kc=0.9,
                etc=4.32,
                lst=31.0 + (index % 4),
                smap_sm=0.18,
                crop_stage="vegetative",
                label_source="water_balance",
            ))
        now = utc_now()
        for day_offset in range(14):
            created_at = now - timedelta(days=13 - day_offset)
            for index, plot_id in enumerate(plot_ids):
                advisory_class = REALISTIC_CLASS_PATTERN[(index + day_offset // 3) % len(REALISTIC_CLASS_PATTERN)]
                prediction_id = f"{DEMO_PREFIX}prediction-{day_offset:02d}-{index:02d}"
                advisory_id = f"{DEMO_PREFIX}advisory-{day_offset:02d}-{index:02d}"
                get_or_create(session, MlPrediction, prediction_id, {
                    "prediction_id": prediction_id,
                    "plot_id": plot_id,
                    "model_version": "demo-v1.3.0",
                    "stage1_soil_moisture_estimate": 0.12 + (index % 5) * 0.02,
                    "stage1_cwsi_estimate": 0.35 + (index % 4) * 0.08,
                    "advisory_class": advisory_class,
                    "confidence_score": 0.84,
                    "reason_code": "demo_dataset",
                    "input_feature_snapshot": {
                        "dataset": "demo",
                        "provider": "nir_api",
                        "nir_percent": 18.0 + (index % 8) * 7.5,
                        "confidence": 0.82 + (index % 4) * 0.03,
                        "urgency": (
                            "URGENT"
                            if advisory_class == "irrigate_now"
                            else "MODERATE"
                            if advisory_class == "irrigate_soon"
                            else "SAFE"
                        ),
                        "fallback_used": False,
                    },
                    "predicted_at": created_at,
                })
                get_or_create(session, Advisory, advisory_id, {
                    "advisory_id": advisory_id,
                    "plot_id": plot_id,
                    "prediction_id": prediction_id,
                    "advisory_class": advisory_class,
                    "language_used": "en",
                    "sms_sent": False,
                    "ivr_triggered": False,
                    "created_at": created_at,
                })

        get_or_create(session, ModelEvaluationRun, f"{DEMO_PREFIX}evaluation-v1.3.0", {
            "run_id": f"{DEMO_PREFIX}evaluation-v1.3.0",
            "model_version": "demo-v1.3.0",
            "trained_at": now - timedelta(days=10),
            "agro_zone": "vidarbha-yavatmal-pilot",
            "rmse": 0.0721,
            "mae": 0.0512,
            "r2": 0.81,
            "accuracy": 0.88,
            "precision_score": 0.79,
            "recall": 0.90,
            "f1": 0.84,
            "fpr": 0.04,
            "passed_fpr_threshold": True,
            "shap_feature_importance": {"ndvi": 0.31, "vv_db": 0.22, "soil_moisture": 0.18},
            "notes": "Seeded local demonstration evaluation.",
        })
        get_or_create(session, ModelEvaluationRun, f"{DEMO_PREFIX}evaluation-v1.2.0", {
            "run_id": f"{DEMO_PREFIX}evaluation-v1.2.0",
            "model_version": "demo-v1.2.0",
            "trained_at": now - timedelta(days=35),
            "agro_zone": "vidarbha-yavatmal-pilot",
            "rmse": 0.086,
            "mae": 0.061,
            "r2": 0.74,
            "accuracy": 0.82,
            "precision_score": 0.71,
            "recall": 0.84,
            "f1": 0.77,
            "fpr": 0.12,
            "passed_fpr_threshold": False,
            "shap_feature_importance": {"ndvi": 0.28, "vv_db": 0.20, "soil_moisture": 0.16},
            "notes": "Seeded local demonstration evaluation requiring review.",
        })
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    seed()
    print(f"Seeded dashboard demo data. Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
