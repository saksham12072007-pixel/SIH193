import uuid

from app.core.auth import create_institutional_access_token, hash_password
from app.models import InstitutionalUser, MlPrediction
from app.services.ml_prediction_service import PredictionResult, PredictionType
from app.utils.time import utc_now


def _register_farmer(client, phone_number: str, district: str = "Nashik", language: str = "en"):
    response = client.post(
        "/farmers/register",
        json={
            "phone_number": phone_number,
            "name": f"Farmer {phone_number[-4:]}",
            "preferred_language": language,
            "state": "Maharashtra",
            "district": district,
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    assert response.status_code == 201
    return response.json()["farmer_id"]


def _create_plot(client, farmer_id: str, nickname: str, crop_type: str = "rice"):
    response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": nickname,
            "latitude": 19.076,
            "longitude": 72.8777,
            "crop_type": crop_type,
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    assert response.status_code == 201
    return response.json()["plot_id"]


def _institutional_headers(client, district: str = "Nashik"):
    signup = client.post(
        "/institutional/signup",
        json={
            "email": f"{district.lower()}@example.com",
            "password": "StrongPass123",
            "role": "viewer",
            "assigned_geography": {"districts": [district]},
        },
    )
    assert signup.status_code == 201

    login = client.post(
        "/institutional/login",
        json={"email": f"{district.lower()}@example.com", "password": "StrongPass123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _admin_headers(db_session, email: str = "admin@example.com"):
    """Admin accounts can no longer self-signup via the API (privilege-escalation
    fix), so tests provision one directly the same way the seed scripts do."""
    user = InstitutionalUser(
        user_id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password("StrongPass123"),
        role="admin",
        assigned_geography={},
    )
    db_session.add(user)
    db_session.commit()
    token = create_institutional_access_token(user_id=user.user_id, role="admin", assigned_geography={})
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_aggregates_and_trends(client, db_session):
    plot_ids = []
    for index in range(5):
        farmer_id = _register_farmer(client, f"9000001{index:03d}", district="Nashik")
        plot_id = _create_plot(client, farmer_id, f"Plot {index}")
        plot_ids.append(plot_id)

    for plot_id in plot_ids:
        assert client.post(f"/ingest/{plot_id}?use_mock=true").status_code == 202
        advisory = client.post(f"/advisories/generate/{plot_id}")
        assert advisory.status_code == 201
        prediction = db_session.query(MlPrediction).filter(
            MlPrediction.prediction_id == advisory.json()["prediction_id"]
        ).one()
        prediction.input_feature_snapshot = {
            "provider": "nir_api",
            "nir_percent": 10.0 + len(plot_ids),
        }
    db_session.commit()

    headers = _institutional_headers(client, district="Nashik")

    unauthorized = client.get("/dashboard/aggregates?district=Nashik&window_days=30")
    assert unauthorized.status_code in (401, 403)

    aggregates = client.get("/dashboard/aggregates?district=Nashik&window_days=30", headers=headers)
    assert aggregates.status_code == 200
    aggregate_data = aggregates.json()
    assert aggregate_data["suppressed"] is False
    assert aggregate_data["total_plots"] == 5
    assert "alert_rate" in aggregate_data
    assert aggregate_data["nri_percent"] == 15.0
    assert aggregate_data["nri_plot_count"] == 5
    assert sum(aggregate_data["summary"].values()) == 5
    nashik = next(d for d in aggregate_data["districts"] if d["name"] == "Nashik")
    assert nashik["avgNir"] is not None
    # Mock ingestion writes real plot_features rows, so these are no longer hardcoded None.
    assert nashik["avgNdvi"] is not None
    assert nashik["avgRainfall"] is not None

    trends = client.get("/dashboard/trends?district=Nashik&window_days=30", headers=headers)
    assert trends.status_code == 200
    trend_data = trends.json()
    assert trend_data["suppressed"] is False
    assert len(trend_data["series"]) >= 1

    unauthorized_analytics = client.get("/dashboard/analytics?district=Nashik&window_days=30")
    assert unauthorized_analytics.status_code in (401, 403)

    analytics = client.get("/dashboard/analytics?district=Nashik&window_days=30", headers=headers)
    assert analytics.status_code == 200
    analytics_data = analytics.json()
    assert analytics_data["suppressed"] is False
    assert len(analytics_data["observations"]) == 5
    assert all(obs["nir_percent"] is not None for obs in analytics_data["observations"])
    crop_summary = analytics_data["crop_summary"]
    assert len(crop_summary) == 1
    assert crop_summary[0]["name"] == "rice"
    assert crop_summary[0]["avg_nir"] is not None
    assert len(analytics_data["state_summary"]) == 1
    assert analytics_data["state_summary"][0]["name"] == "Maharashtra"


def test_sms_and_internal_orchestration(client, db_session, monkeypatch):
    def forced_prediction(self, plot_id: str):
        # Ingestion now auto-chains a prediction (live-update wiring), so this
        # mock is invoked more than once per test -- each call needs a unique id.
        return PredictionResult(
            prediction_id=f"prediction-test-{uuid.uuid4()}",
            plot_id=plot_id,
            prediction_type=PredictionType.IRRIGATION_STRESS,
            predicted_value=19.0,
            advisory_class="irrigate_now",
            confidence_score=0.94,
            reason_code="low_soil_moisture",
            explanation={
                "reason": "forced orchestration test",
                "stage2_rules": {
                    "advisory_class": "irrigate_now",
                    "reason_code": "low_soil_moisture",
                    "cwsi": 0.81,
                },
            },
            model_version="test-v1",
            predicted_at=utc_now(),
        )

    monkeypatch.setattr("app.services.ml_prediction_service.MLPredictionService.predict_irrigation_stress", forced_prediction)

    farmer_id = _register_farmer(client, "9000012345", district="Pune")
    plot_id = _create_plot(client, farmer_id, "SMS Plot")

    send_response = client.post(
        "/sms/send",
        json={
            "farmer_phone": "9000012345",
            "message_body": "Test advisory message",
            "advisory_id": None,
        },
    )
    assert send_response.status_code == 200
    message_id = send_response.json()["message_id"]

    delivery_response = client.post(
        "/sms/webhook/delivery",
        json={"sms_log_id": message_id, "status": "delivered"},
    )
    assert delivery_response.status_code == 200

    assert client.post(f"/ingest/{plot_id}?use_mock=true").status_code == 202
    assert client.post(f"/advisories/generate/{plot_id}").status_code == 201

    inbound_response = client.post(
        "/sms/inbound",
        json={"farmer_phone": "9000012345", "message_body": "1"},
    )
    assert inbound_response.status_code == 200
    assert inbound_response.json()["ok"] is True

    admin_headers = _admin_headers(db_session)

    unauthorized = client.post("/internal/ingestion/trigger?use_mock=true")
    assert unauthorized.status_code in (401, 403)

    internal_ingestion = client.post("/internal/ingestion/trigger?use_mock=true", headers=admin_headers)
    assert internal_ingestion.status_code == 200
    assert internal_ingestion.json()["status"] == "queued"

    internal_retraining = client.post("/internal/retraining/run", headers=admin_headers)
    assert internal_retraining.status_code == 200
    assert internal_retraining.json()["feedback_records_seen"] >= 1


def test_inbound_sms_clarifies_unrecognized_or_unmatched_feedback(client):
    _register_farmer(client, "9000099999", district="Pune")

    unmatched = client.post(
        "/sms/inbound",
        json={"farmer_phone": "9000099999", "message_body": "1"},
    )
    assert unmatched.status_code == 200
    assert unmatched.json()["ok"] is False
    assert "72 hours" in unmatched.json()["message"]

    unrecognized = client.post(
        "/sms/inbound",
        json={"farmer_phone": "9000099999", "message_body": "9"},
    )
    assert unrecognized.status_code == 200
    assert unrecognized.json()["ok"] is False
    assert "Unrecognized reply" in unrecognized.json()["message"]
