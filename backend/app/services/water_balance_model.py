"""Water-balance bucket model for irrigation stress estimation (weak-label generator)."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy.orm import Session

from app.models import Plot, SatelliteData
from app.services.feature_engineering_service import FeatureEngineeringService


class IrrigationStress(str, Enum):
    """Irrigation stress classification."""

    NO_STRESS = "no_stress"
    MILD_STRESS = "mild_stress"
    MODERATE_STRESS = "moderate_stress"
    SEVERE_STRESS = "severe_stress"


@dataclass
class WaterBalanceResult:
    """Result from water-balance bucket model."""

    plot_id: str
    soil_moisture_pct: float
    irrigation_stress: IrrigationStress
    confidence: float
    reason: str


class WaterBalanceBucketModel:
    """
    FAO-56 inspired water-balance bucket model for irrigation stress estimation.
    
    This is a simplified weak-label generator that uses only publicly available data:
    - NDVI (vegetation index) from Sentinel-2
    - Rainfall from weather data
    - Temperature from weather data
    - Sowing date from farmer registration
    
    No field sensors required; weak labels can be refined with farmer feedback.
    """

    # Model parameters (FAO-56 simplified)
    SOIL_CAPACITY_MM = 150  # Available water capacity (typical for loamy soil)
    ROOT_DEPTH_MM = 600  # Rooting depth (varies by crop, 600mm typical for rice/wheat)
    DEPLETION_FRACTION = 0.5  # Allowable depletion fraction (50% = crop stress begins)
    KC_GROWTH_STAGES = {
        "initial": 0.3,  # Days 0-20
        "development": 0.7,  # Days 20-60
        "mid_season": 1.1,  # Days 60-120
        "late_season": 0.5,  # Days 120+
    }

    def __init__(self, db: Session):
        self.db = db
        self.feature_service = FeatureEngineeringService(db)

    def estimate_stress(self, plot_id: str, observation_date: date | None = None) -> WaterBalanceResult:
        """Estimate irrigation stress for a plot using water-balance model."""
        plot = self.db.query(Plot).filter(Plot.plot_id == plot_id).first()
        if not plot:
            return WaterBalanceResult(
                plot_id=plot_id,
                soil_moisture_pct=0,
                irrigation_stress=IrrigationStress.NO_STRESS,
                confidence=0.0,
                reason="Plot not found",
            )

        as_of = datetime.combine(observation_date, datetime.max.time(), tzinfo=timezone.utc) if observation_date else None
        features = self.feature_service.get_features_for_plot(plot_id, observation_date=as_of)
        if not features or features.ndvi is None:
            return WaterBalanceResult(
                plot_id=plot_id,
                soil_moisture_pct=0,
                irrigation_stress=IrrigationStress.NO_STRESS,
                confidence=0.0,
                reason="Insufficient data (no NDVI readings)",
            )

        # Estimate soil moisture from NDVI and rainfall
        ndvi_normalized = (features.ndvi + 0.2) / 0.8  # Typical NDVI range -0.2 to +0.6
        ndvi_normalized = max(0, min(1, ndvi_normalized))  # Clamp to [0, 1]

        # Rainfall impact
        rainfall_impact = 0
        if features.rainfall_mm and features.rainfall_mm > 0:
            rainfall_impact = min(features.rainfall_mm / 10, 1)  # 10mm saturates soil

        # Days since sowing impacts stress tolerance
        days_into_season = features.days_since_sowing or 0
        kc = self._get_crop_coefficient(days_into_season)

        # Base soil moisture estimate (NDVI as proxy for water availability)
        base_soil_moisture = ndvi_normalized * 100 + rainfall_impact * 20

        # Adjust by crop coefficient and growth stage
        adjusted_moisture = base_soil_moisture * (1 - 0.1 * (1 - kc))

        # Clamp to 0-100%
        soil_moisture_pct = max(0, min(100, adjusted_moisture))

        # Classify stress based on thresholds
        stress_threshold = self.SOIL_CAPACITY_MM * self.DEPLETION_FRACTION
        moisture_normalized = soil_moisture_pct / 100

        if moisture_normalized > 0.8:
            stress = IrrigationStress.NO_STRESS
            confidence = 0.85
            reason = f"High soil moisture ({soil_moisture_pct:.1f}%), strong NDVI ({features.ndvi:.3f})"
        elif moisture_normalized > 0.5:
            stress = IrrigationStress.MILD_STRESS
            confidence = 0.70
            reason = f"Moderate soil moisture ({soil_moisture_pct:.1f}%), declining NDVI trend ({features.ndvi_trend or 0:.4f})"
        elif moisture_normalized > 0.25:
            stress = IrrigationStress.MODERATE_STRESS
            confidence = 0.75
            reason = f"Low soil moisture ({soil_moisture_pct:.1f}%), weak NDVI ({features.ndvi:.3f})"
        else:
            stress = IrrigationStress.SEVERE_STRESS
            confidence = 0.80
            reason = f"Critical soil moisture ({soil_moisture_pct:.1f}%), severe NDVI decline"

        # Adjust confidence by data freshness and quality
        quality = 1 - self.feature_service.compute_cloud_mask_quality(plot_id)
        confidence *= quality

        return WaterBalanceResult(
            plot_id=plot_id,
            soil_moisture_pct=soil_moisture_pct,
            irrigation_stress=stress,
            confidence=confidence,
            reason=reason,
        )

    def _get_crop_coefficient(self, days: int) -> float:
        """Get crop coefficient (Kc) based on growth stage."""
        if days < 20:
            return self.KC_GROWTH_STAGES["initial"]
        elif days < 60:
            return self.KC_GROWTH_STAGES["development"]
        elif days < 120:
            return self.KC_GROWTH_STAGES["mid_season"]
        else:
            return self.KC_GROWTH_STAGES["late_season"]
