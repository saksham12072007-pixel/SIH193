"""Tests for Phase 3: ML Prediction Service."""

from app.services.nir_api_service import NirApiError, NirPrediction


def _create_demo_plot(client):
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432199",
            "name": "Smoke Test Farmer",
            "preferred_language": "en",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    assert farmer_response.status_code == 201

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_response.json()["farmer_id"],
            "plot_nickname": "Smoke Test Plot",
            "latitude": 19.076,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    assert plot_response.status_code == 201
    plot_id = plot_response.json()["plot_id"]
    assert client.post(f"/ingest/{plot_id}?use_mock=true").status_code == 202
    return plot_id


def test_prediction_smoke_exposes_nir_contract(client, monkeypatch):
    plot_id = _create_demo_plot(client)
    monkeypatch.setattr(
        "app.services.ml_prediction_service.MLPredictionService._build_nir_input",
        lambda self, plot_id, stage1: (
            {
                "soil_moisture": 41.0,
                "temperature": 28.0,
                "rainfall": 4.0,
                "et0": 4.5,
                "crop_stage": 2,
                "crop": "rice",
                "soil_type": "loamy",
            },
            None,
        ),
    )

    def fake_predict(self, payload):
        return NirPrediction(
            nir=41.27,
            advice="Irrigate within 24 hours",
            urgency="MODERATE",
            confidence=0.8209,
            model_version="2.0.0",
            request=payload,
        )

    monkeypatch.setattr("app.services.nir_api_service.NirApiService.predict", fake_predict)

    response = client.post(f"/predictions/irrigation-stress/{plot_id}")

    assert response.status_code == 201
    body = response.json()
    assert body["nir_percent"] == 41.27
    assert body["urgency"] == "MODERATE"
    assert body["confidence"] == 0.8209
    assert body["model_version"] == "2.0.0"
    assert body["fallback_used"] is False


def test_prediction_smoke_reports_legacy_fallback(client, monkeypatch):
    plot_id = _create_demo_plot(client)
    monkeypatch.setattr(
        "app.services.ml_prediction_service.MLPredictionService._build_nir_input",
        lambda self, plot_id, stage1: (
            {
                "soil_moisture": 41.0,
                "temperature": 28.0,
                "rainfall": 4.0,
                "et0": 4.5,
                "crop_stage": 2,
                "crop": "rice",
                "soil_type": "loamy",
            },
            None,
        ),
    )

    def unavailable(self, payload):
        raise NirApiError("test NIR outage")

    monkeypatch.setattr("app.services.nir_api_service.NirApiService.predict", unavailable)

    response = client.post(f"/predictions/irrigation-stress/{plot_id}")

    assert response.status_code == 201
    body = response.json()
    assert body["fallback_used"] is True
    assert body["nir_percent"] is None
    assert body["model_version"] == "v1.1-two-stage"


def test_prediction_nonexistent_plot(client):
    """Test prediction for nonexistent plot returns 404."""
    response = client.post("/predictions/irrigation-stress/nonexistent-plot-id")
    assert response.status_code == 404


def test_explain_nonexistent_prediction(client):
    """Test explanation for nonexistent prediction returns 404."""
    response = client.get("/predictions/explain/nonexistent-prediction-id")
    assert response.status_code == 404


def test_get_latest_nonexistent_plot(client):
    """Test latest prediction for nonexistent plot returns 404."""
    response = client.get("/predictions/latest/nonexistent-plot-id")
    assert response.status_code == 404
