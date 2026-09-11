"""Computes real data-quality/completeness metrics for the admin dashboard.

Every figure here is derived directly from existing columns -- nothing is
invented. See DataQualityMetrics in the frontend (src/types/index.ts) for the
shape this feeds.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Farmer, MlPrediction, Plot, PlotFeatures
from app.utils.time import utc_now


def _pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 100.0
    return round((numerator / denominator) * 100.0, 1)


def compute_data_quality(db: Session, window_days: int = 14) -> dict[str, object]:
    farmers = db.query(Farmer).all()
    plots = db.query(Plot).all()
    total_farmers = len(farmers)
    total_plots = len(plots)
    plot_ids = [plot.plot_id for plot in plots]

    complete_farmer_records = sum(
        1 for farmer in farmers if farmer.name and farmer.state and farmer.district
    )
    missing_records = total_farmers - complete_farmer_records

    farms_with_coordinates = sum(1 for plot in plots if plot.location_point)
    invalid_coordinates = sum(1 for plot in plots if plot.location_precision == "village_fallback")

    window_start = (utc_now() - timedelta(days=window_days)).date()
    feature_rows = (
        db.query(PlotFeatures)
        .filter(PlotFeatures.plot_id.in_(plot_ids), PlotFeatures.obs_date >= window_start)
        .all()
        if plot_ids
        else []
    )
    plots_with_recent_ndvi = {row.plot_id for row in feature_rows if row.ndvi is not None}
    plots_with_recent_weather = {row.plot_id for row in feature_rows if row.rainfall_7d is not None}

    recent_predictions = (
        db.query(MlPrediction)
        .filter(MlPrediction.plot_id.in_(plot_ids), MlPrediction.predicted_at >= window_start)
        .all()
        if plot_ids
        else []
    )
    plots_with_recent_nir = {
        prediction.plot_id
        for prediction in recent_predictions
        if (prediction.input_feature_snapshot or {}).get("provider") == "nir_api"
    }

    outdated_data = sum(1 for plot in plots if plot.data_status != "available")

    duplicate_groups: dict[tuple[str, str], int] = defaultdict(int)
    for farmer in farmers:
        if not farmer.name or not farmer.district:
            continue
        duplicate_groups[(farmer.name.strip().lower(), farmer.district)] += 1
    duplicate_farmers = sum(count - 1 for count in duplicate_groups.values() if count > 1)

    return {
        "farmerRecords": _pct(complete_farmer_records, total_farmers),
        "farmCoordinates": _pct(farms_with_coordinates, total_plots),
        "nirData": _pct(len(plots_with_recent_nir), total_plots),
        "ndviData": _pct(len(plots_with_recent_ndvi), total_plots),
        "weatherData": _pct(len(plots_with_recent_weather), total_plots),
        "missingRecords": missing_records,
        "invalidCoordinates": invalid_coordinates,
        "duplicateFarmers": duplicate_farmers,
        "outdatedData": outdated_data,
        "totalFarmers": total_farmers,
        "totalPlots": total_plots,
        "windowDays": window_days,
        "generatedAt": utc_now().isoformat(),
    }
