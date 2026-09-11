import pytest

from app.services.nir_api_service import NirApiError, NirApiService


def _service() -> NirApiService:
    service = object.__new__(NirApiService)
    service.model_version_override = None
    return service


def test_parse_prediction_supports_confidence_and_model_version():
    result = _service()._parse_prediction(
        {
            "nir": 22.4,
            "advice": "No irrigation needed",
            "urgency": "SAFE",
            "confidence": 0.91,
            "model_version": "v2.0.0-2025-09-04",
        },
        {"crop": "cotton"},
    )

    assert result.nir == 22.4
    assert result.urgency == "SAFE"
    assert result.confidence == 0.91
    assert result.model_version == "v2.0.0-2025-09-04"


def test_parse_prediction_normalizes_percentage_confidence():
    result = _service()._parse_prediction(
        {
            "nir": 39.29,
            "advice": "Irrigate within 1-2 days",
            "urgency": "MODERATE",
            "confidence": 87.73,
            "model_version": "2.0.0",
        },
        {"crop": "rice"},
    )

    assert result.confidence == pytest.approx(0.8773)


@pytest.mark.parametrize(
    "body",
    [
        {"nir": 101, "advice": "bad", "urgency": "SAFE"},
        {"nir": 20, "advice": "bad", "urgency": "UNKNOWN"},
        {"nir": 20, "advice": "bad", "urgency": "SAFE", "confidence": 101.1},
    ],
)
def test_parse_prediction_rejects_invalid_contract(body):
    with pytest.raises(NirApiError):
        _service()._parse_prediction(body, {})
