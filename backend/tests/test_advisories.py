from app.models import AdvisoryFeedback
from app.services.ml_prediction_service import PredictionResult, PredictionType
from app.utils.time import utc_now


def test_generate_advisory_skips_sms_for_no_action(client):
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "9123456789",
            "name": "Advisory Farmer",
            "preferred_language": "en",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Advisory Plot",
            "latitude": 19.076,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    plot_id = plot_response.json()["plot_id"]

    ingest_response = client.post(f"/ingest/{plot_id}?use_mock=true")
    assert ingest_response.status_code == 202

    advisory_response = client.post(f"/advisories/generate/{plot_id}")
    assert advisory_response.status_code == 201
    advisory_data = advisory_response.json()
    assert advisory_data["plot_id"] == plot_id
    assert advisory_data["sms_status"] == "not_sent_no_action"
    assert advisory_data["message"]

    get_response = client.get(f"/advisories/{advisory_data['advisory_id']}")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["advisory_id"] == advisory_data["advisory_id"]
    assert get_data["sms_sent"] is False


def test_generate_advisory_and_record_feedback(client, db_session, monkeypatch):
    def forced_prediction(self, plot_id: str):
        return PredictionResult(
            prediction_id="prediction-test-1",
            plot_id=plot_id,
            prediction_type=PredictionType.IRRIGATION_STRESS,
            predicted_value=18.0,
            advisory_class="irrigate_now",
            confidence_score=0.95,
            reason_code="low_soil_moisture",
            explanation={
                "reason": "forced test advisory",
                "stage2_rules": {
                    "advisory_class": "irrigate_now",
                    "reason_code": "low_soil_moisture",
                    "cwsi": 0.82,
                },
            },
            model_version="test-v1",
            predicted_at=utc_now(),
        )

    monkeypatch.setattr("app.services.ml_prediction_service.MLPredictionService.predict_irrigation_stress", forced_prediction)

    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "9123456799",
            "name": "Advisory Farmer",
            "preferred_language": "en",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Advisory Plot",
            "latitude": 19.076,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    plot_id = plot_response.json()["plot_id"]

    advisory_response = client.post(f"/advisories/generate/{plot_id}")
    assert advisory_response.status_code == 201
    advisory_data = advisory_response.json()
    assert advisory_data["plot_id"] == plot_id
    assert advisory_data["sms_status"] == "sent"
    assert advisory_data["message"]

    get_response = client.get(f"/advisories/{advisory_data['advisory_id']}")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["advisory_id"] == advisory_data["advisory_id"]
    assert get_data["sms_sent"] is True

    feedback_response = client.post(
        f"/advisories/feedback/{advisory_data['advisory_id']}",
        params={"feedback_score": 1},
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["score"] == 1

    feedback_row = db_session.query(AdvisoryFeedback).filter(AdvisoryFeedback.advisory_id == advisory_data["advisory_id"]).first()
    assert feedback_row is not None
    assert feedback_row.predicted_class == "irrigate_now"
    assert float(feedback_row.predicted_confidence) == 0.95
    assert float(feedback_row.predicted_soil_moisture) == 18.0
    assert feedback_row.model_version == "test-v1"
