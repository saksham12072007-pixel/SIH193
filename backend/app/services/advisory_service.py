from app.schemas.advisory import AdvisoryDecision


class AdvisoryService:
    """Deterministic advisory engine skeleton aligned with project requirements."""

    def decide(self, soil_moisture: float, ndvi_trend: float, crop_stage: str) -> AdvisoryDecision:
        if soil_moisture < 0.25:
            return AdvisoryDecision(
                advisory_class="irrigate_now",
                confidence_score=0.92,
                reason_code="low_soil_moisture",
                model_version="baseline-v1",
            )
        if soil_moisture < 0.4 or ndvi_trend < -0.03:
            return AdvisoryDecision(
                advisory_class="irrigate_soon",
                confidence_score=0.76,
                reason_code="declining_ndvi_trend",
                model_version="baseline-v1",
            )
        if crop_stage == "late":
            return AdvisoryDecision(
                advisory_class="monitor",
                confidence_score=0.64,
                reason_code="stage_monitor",
                model_version="baseline-v1",
            )
        return AdvisoryDecision(
            advisory_class="no_action",
            confidence_score=0.88,
            reason_code="adequate_moisture",
            model_version="baseline-v1",
        )
