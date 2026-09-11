from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, contains_eager

from app.db.database import get_db
from app.models import Advisory, Alert, Farmer, InstitutionalUser, MlPrediction, Plot, PlotFeatures
from app.routers.institutional_auth import get_current_institutional_user
from app.utils.time import utc_now

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

MIN_AGGREGATION_THRESHOLD = 5
_ADVISORY_URGENCY = {"no_action": "SAFE", "monitor": "MODERATE", "irrigate_soon": "HIGH", "irrigate_now": "URGENT"}


def _scope_query(
    db: Session,
    state: str | None = None,
    district: str | None = None,
    crop: str | None = None,
    soil: str | None = None,
):
    # contains_eager populates Plot.farmer from this same JOIN instead of
    # lazy-loading it later -- callers access plot.farmer.district per plot,
    # which without this issues one query per plot (thousands, for a
    # national scope) instead of one query total.
    query = db.query(Plot).join(Farmer, Farmer.farmer_id == Plot.farmer_id).options(contains_eager(Plot.farmer))
    if district:
        query = query.filter(Farmer.district == district)
    elif state:
        query = query.filter(Farmer.state == state)
    if crop:
        query = query.filter(Plot.crop_type == crop)
    if soil:
        query = query.filter(Plot.soil_texture == soil)
    return query


def _scope_label(state: str | None, district: str | None) -> str:
    if district:
        return district
    if state:
        return state
    return "pilot-district"


def _enforce_scope(
    current_user: InstitutionalUser, state: str | None, district: str | None
) -> tuple[str | None, str | None]:
    if current_user.role == "admin":
        return state, district

    assigned = current_user.assigned_geography or {}
    allowed_states = set(assigned.get("states", []))
    allowed_districts = set(assigned.get("districts", []))

    if district:
        if district not in allowed_districts:
            raise PermissionError("Requested district is not in assigned geography")
        return None, district

    if state:
        if state not in allowed_states:
            raise PermissionError("Requested state is not in assigned geography")
        return state, None

    if allowed_districts:
        return None, sorted(allowed_districts)[0]
    if allowed_states:
        return sorted(allowed_states)[0], None
    raise PermissionError("No assigned geography configured for this institutional user")


def _latest_advisories_by_plot(db: Session, plot_id_subq, window_start: datetime) -> dict[str, Advisory]:
    advisories = (
        db.query(Advisory)
        .filter(Advisory.plot_id.in_(plot_id_subq), Advisory.created_at >= window_start)
        .order_by(Advisory.plot_id.asc(), Advisory.created_at.desc())
        .all()
    )
    latest: dict[str, Advisory] = {}
    for advisory in advisories:
        if advisory.plot_id not in latest:
            latest[advisory.plot_id] = advisory
    return latest


@router.get("/aggregates")
def get_aggregates(
    state: str | None = None,
    district: str | None = None,
    crop: str | None = None,
    soil: str | None = None,
    window_days: int = 7,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        state, district = _enforce_scope(current_user, state, district)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    scope = _scope_query(db, state=state, district=district, crop=crop, soil=soil)
    # A large materialized id list passed to .in_() (thousands of bind params)
    # is dramatically slower against Postgres than pushing the id lookup down
    # as a subquery -- confirmed ~29s vs <1s for a 3.7k-plot national scope.
    plot_id_subq = scope.with_entities(Plot.plot_id)
    total_plots = scope.count()
    scope_name = _scope_label(state, district)

    if total_plots < MIN_AGGREGATION_THRESHOLD:
        return {
            "scope": scope_name,
            "window_days": window_days,
            "suppressed": True,
            "total_plots": 0,
            "alert_rate": 0.0,
            "nri_percent": None,
            "nri_plot_count": 0,
            "summary": {"no_action": 0, "monitor": 0, "irrigate_soon": 0, "irrigate_now": 0},
        }

    window_start = utc_now() - timedelta(days=window_days)
    latest = _latest_advisories_by_plot(db, plot_id_subq, window_start)
    prediction_ids_subq = db.query(Advisory.prediction_id).filter(
        Advisory.plot_id.in_(plot_id_subq), Advisory.created_at >= window_start
    )
    # Select only the columns actually used below instead of full ORM rows --
    # MlPrediction has several Numeric columns unused here (this endpoint
    # only reads prediction_id/input_feature_snapshot), and cutting the
    # unused columns meaningfully reduces bytes transferred at this scale.
    predictions = (
        db.query(MlPrediction.prediction_id, MlPrediction.input_feature_snapshot)
        .filter(MlPrediction.prediction_id.in_(prediction_ids_subq))
        .all()
        if latest
        else []
    )
    nri_values: list[float] = []
    for prediction in predictions:
        snapshot = prediction.input_feature_snapshot or {}
        if snapshot.get("provider") != "nir_api":
            continue
        nir_value = snapshot.get("nir_percent")
        if nir_value is not None:
            nri_values.append(float(nir_value))

    summary = Counter(advisory.advisory_class for advisory in latest.values())
    alerts = sum(1 for advisory in latest.values() if advisory.advisory_class in {"monitor", "irrigate_soon", "irrigate_now"})
    alert_rate = round((alerts / total_plots) * 100.0, 1) if total_plots else 0.0

    # Same column-selection trick as predictions above -- PlotFeatures has
    # ~25 columns, only 4 are read below.
    feature_rows = (
        db.query(PlotFeatures.plot_id, PlotFeatures.ndvi, PlotFeatures.rainfall_7d)
        .filter(PlotFeatures.plot_id.in_(plot_id_subq), PlotFeatures.obs_date >= window_start.date())
        .all()
    )
    features_by_plot: dict[str, list] = defaultdict(list)
    for row in feature_rows:
        features_by_plot[row.plot_id].append(row)

    district_groups: dict[str, dict[str, object]] = {}
    prediction_by_id = {prediction.prediction_id: prediction for prediction in predictions}
    for plot in scope.all():
        name = plot.farmer.district or "Unknown"
        group = district_groups.setdefault(
            name,
            {
                "name": name,
                "totalFarms": 0,
                "urgent": 0,
                "moderate": 0,
                "safe": 0,
                "crops": Counter(),
                "nirValues": [],
                "ndviValues": [],
                "rainfallValues": [],
            },
        )
        group["totalFarms"] += 1
        group["crops"][plot.crop_type] += 1
        advisory = latest.get(plot.plot_id)
        if advisory is None or advisory.advisory_class == "no_action":
            group["safe"] += 1
        elif advisory.advisory_class == "irrigate_now":
            group["urgent"] += 1
        else:
            group["moderate"] += 1
        prediction = prediction_by_id.get(advisory.prediction_id) if advisory else None
        nir_value = (prediction.input_feature_snapshot or {}).get("nir_percent") if prediction else None
        if nir_value is not None:
            group["nirValues"].append(float(nir_value))
        for row in features_by_plot.get(plot.plot_id, []):
            if row.ndvi is not None:
                group["ndviValues"].append(float(row.ndvi))
            if row.rainfall_7d is not None:
                group["rainfallValues"].append(float(row.rainfall_7d))

    districts = []
    for group in district_groups.values():
        crops = group.pop("crops")
        nir_values = group.pop("nirValues")
        ndvi_values = group.pop("ndviValues")
        rainfall_values = group.pop("rainfallValues")
        districts.append(
            {
                **group,
                "avgNir": round(sum(nir_values) / len(nir_values), 1) if nir_values else None,
                "avgNdvi": round(sum(ndvi_values) / len(ndvi_values), 4) if ndvi_values else None,
                "avgRainfall": round(sum(rainfall_values) / len(rainfall_values), 2) if rainfall_values else None,
                "primaryCrop": crops.most_common(1)[0][0] if crops else "Unknown",
            }
        )

    return {
        "scope": scope_name,
        "window_days": window_days,
        "suppressed": False,
        "total_plots": total_plots,
        "alert_rate": alert_rate,
        "nri_percent": round(sum(nri_values) / len(nri_values), 1) if nri_values else None,
        "nri_plot_count": len(nri_values),
        "summary": {
            "no_action": summary.get("no_action", 0),
            "monitor": summary.get("monitor", 0),
            "irrigate_soon": summary.get("irrigate_soon", 0),
            "irrigate_now": summary.get("irrigate_now", 0),
        },
        "districts": sorted(districts, key=lambda item: str(item["name"])),
    }


@router.get("/trends")
def get_trends(
    state: str | None = None,
    district: str | None = None,
    crop: str | None = None,
    soil: str | None = None,
    window_days: int = 14,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        state, district = _enforce_scope(current_user, state, district)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    scope = _scope_query(db, state=state, district=district, crop=crop, soil=soil)
    plot_id_subq = scope.with_entities(Plot.plot_id)
    scope_name = _scope_label(state, district)

    if scope.count() < MIN_AGGREGATION_THRESHOLD:
        return {"scope": scope_name, "window_days": window_days, "suppressed": True, "series": []}

    window_start = utc_now() - timedelta(days=window_days)
    advisories = (
        db.query(Advisory)
        .filter(Advisory.plot_id.in_(plot_id_subq), Advisory.created_at >= window_start)
        .order_by(Advisory.created_at.asc())
        .all()
    )

    # A plot re-ingested more than once in a day (retry after a failed
    # satellite pass, a manual re-trigger, a bulk dataset re-import) produces
    # multiple advisories that day -- count only its latest one per day, or
    # that day's total balloons past the plot's actual single-day signal.
    latest_per_plot_per_day: dict[tuple[str, str], Advisory] = {}
    for advisory in advisories:
        day = advisory.created_at.date().isoformat()
        key = (advisory.plot_id, day)
        existing = latest_per_plot_per_day.get(key)
        if existing is None or advisory.created_at >= existing.created_at:
            latest_per_plot_per_day[key] = advisory

    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for (_, day), advisory in latest_per_plot_per_day.items():
        buckets[day][advisory.advisory_class] += 1

    feature_rows = (
        db.query(
            PlotFeatures.plot_id, PlotFeatures.obs_date, PlotFeatures.ndvi, PlotFeatures.savi,
            PlotFeatures.rainfall_7d, PlotFeatures.soil_moisture_label, PlotFeatures.vv_db,
        )
        .filter(PlotFeatures.plot_id.in_(plot_id_subq), PlotFeatures.obs_date >= window_start.date())
        .order_by(PlotFeatures.obs_date.asc())
        .all()
    )
    environmental_buckets: dict[str, list[PlotFeatures]] = defaultdict(list)
    for row in feature_rows:
        environmental_buckets[row.obs_date.isoformat()].append(row)

    environmental_series = []
    for day, rows in sorted(environmental_buckets.items()):
        def average(attribute: str) -> float | None:
            values = [float(getattr(row, attribute)) for row in rows if getattr(row, attribute) is not None]
            return round(sum(values) / len(values), 4) if values else None

        environmental_series.append({
            "date": day,
            "ndvi": average("ndvi"),
            "nir_proxy": average("savi"),
            "rainfall_7d": average("rainfall_7d"),
            "soil_moisture": average("soil_moisture_label"),
            "vv_db": average("vv_db"),
            "plots_observed": len(rows),
        })

    crop_buckets: dict[str, list[PlotFeatures]] = defaultdict(list)
    soil_buckets: dict[str, list[PlotFeatures]] = defaultdict(list)
    plot_lookup = {plot.plot_id: plot for plot in scope.all()}
    for row in feature_rows:
        plot = plot_lookup.get(row.plot_id)
        if plot:
            crop_buckets[plot.crop_type].append(row)
            if plot.soil_texture:
                soil_buckets[plot.soil_texture].append(row)

    def summarize_groups(groups: dict[str, list[PlotFeatures]]) -> list[dict[str, object]]:
        result = []
        for name, rows in sorted(groups.items()):
            ndvi_values = [float(row.ndvi) for row in rows if row.ndvi is not None]
            rainfall_values = [float(row.rainfall_7d) for row in rows if row.rainfall_7d is not None]
            result.append({
                "name": name,
                "observations": len(rows),
                "avg_ndvi": round(sum(ndvi_values) / len(ndvi_values), 4) if ndvi_values else None,
                "avg_rainfall_7d": round(sum(rainfall_values) / len(rainfall_values), 2) if rainfall_values else None,
            })
        return result

    series = [
        {
            "date": day,
            "no_action": counts.get("no_action", 0),
            "monitor": counts.get("monitor", 0),
            "irrigate_soon": counts.get("irrigate_soon", 0),
            "irrigate_now": counts.get("irrigate_now", 0),
        }
        for day, counts in sorted(buckets.items())
    ]

    return {
        "scope": scope_name,
        "window_days": window_days,
        "suppressed": False,
        "series": series,
        "environmental_series": environmental_series,
        "data_provenance": {
            "sentinel1": "plot_features.vv_db",
            "sentinel2": "plot_features.ndvi/savi",
            "weather": "plot_features.rainfall_7d",
        },
        "crop_summary": summarize_groups(crop_buckets),
        "soil_summary": summarize_groups(soil_buckets),
    }


@router.get("/registry")
def get_registry(
    state: str | None = None,
    district: str | None = None,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return government-facing farmer and plot registry analytics."""
    try:
        state, district = _enforce_scope(current_user, state, district)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    farmers_query = db.query(Farmer)
    if district:
        farmers_query = farmers_query.filter(Farmer.district == district)
    elif state:
        farmers_query = farmers_query.filter(Farmer.state == state)
    farmers = farmers_query.order_by(Farmer.created_at.desc()).all()
    farmer_ids = [farmer.farmer_id for farmer in farmers]
    plots = (
        db.query(Plot)
        .filter(Plot.farmer_id.in_(farmer_ids))
        .order_by(Plot.created_at.desc())
        .all()
        if farmer_ids
        else []
    )
    plots_by_farmer: dict[str, list[Plot]] = defaultdict(list)
    for plot in plots:
        plots_by_farmer[plot.farmer_id].append(plot)

    crop_counts = Counter(plot.crop_type for plot in plots)
    return {
        "scope": _scope_label(state, district),
        "total_farmers": len(farmers),
        "active_farmers": sum(1 for farmer in farmers if farmer.status == "active"),
        "total_plots": len(plots),
        "active_plots": sum(1 for plot in plots if plot.status == "active"),
        "crop_distribution": dict(sorted(crop_counts.items())),
        "farmers": [
            {
                "farmer_id": farmer.farmer_id,
                "name": farmer.name or "Unnamed farmer",
                "phone_number": farmer.phone_number,
                "state": farmer.state,
                "district": farmer.district,
                "preferred_language": farmer.preferred_language,
                "status": farmer.status,
                "registration_channel": farmer.registration_channel,
                "registered_at": farmer.created_at.isoformat(),
                "plots": [
                    {
                        "plot_id": plot.plot_id,
                        "name": plot.plot_nickname or "Unnamed plot",
                        "crop": plot.crop_type,
                        "village": plot.village_name,
                        "size_acres": float(plot.plot_size_declared) if plot.plot_size_declared is not None else None,
                        "status": plot.status,
                        "data_status": plot.data_status,
                        "last_ingestion_at": plot.last_ingestion_at.isoformat() if plot.last_ingestion_at else None,
                    }
                    for plot in plots_by_farmer.get(farmer.farmer_id, [])
                ],
            }
            for farmer in farmers
        ],
    }


@router.get("/geography")
def get_geography(
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return all seeded/registered state and district combinations in scope."""
    rows = (
        db.query(Farmer.state, Farmer.district)
        .filter(Farmer.state.isnot(None), Farmer.district.isnot(None))
        .distinct()
        .order_by(Farmer.state.asc(), Farmer.district.asc())
        .all()
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    assigned = current_user.assigned_geography or {}
    for state, district in rows:
        if current_user.role != "admin" and (
            (assigned.get("states") and state not in assigned["states"])
            or (assigned.get("districts") and district not in assigned["districts"])
        ):
            continue
        grouped[state].append(district)
    return {"states": sorted(grouped), "districts_by_state": grouped}


# ---------------------------------------------------------------------------
# Model Health Panel (sec 12.5.1)
# ---------------------------------------------------------------------------

@router.get("/model-health")
def get_model_health(
    agro_zone: str | None = None,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """
    Model-health panel for the KVK/admin dashboard (sec 12.5.1).

    Returns the latest evaluation metrics per model version including:
      - Stage 1: RMSE, MAE, R2
      - Stage 2: Accuracy, Precision, Recall, F1, FPR
    FPR alert is included if any model's FPR exceeds the default threshold.
    """
    from app.models import ModelEvaluationRun
    from app.services.model_evaluation_service import DEFAULT_FPR_THRESHOLD, ModelEvaluationService

    service = ModelEvaluationService(db)
    runs = service.get_latest_per_version(agro_zone=agro_zone)

    versions = []
    alerts = []
    for run in runs:
        entry = {
            "model_version": run.model_version,
            "agro_zone": run.agro_zone,
            "trained_at": run.trained_at.isoformat() if run.trained_at else None,
            "stage1_rmse": float(run.rmse) if run.rmse is not None else None,
            "stage1_r2": float(run.r2) if run.r2 is not None else None,
            "stage2_recall": float(run.recall) if run.recall is not None else None,
            "stage2_fpr": float(run.fpr) if run.fpr is not None else None,
            "passed_fpr_threshold": run.passed_fpr_threshold,
        }
        versions.append(entry)
        if run.fpr is not None and float(run.fpr) > DEFAULT_FPR_THRESHOLD:
            alerts.append({
                "model_version": run.model_version,
                "agro_zone": run.agro_zone,
                "fpr": float(run.fpr),
                "threshold": DEFAULT_FPR_THRESHOLD,
                "alert": "FPR EXCEEDED THRESHOLD -- auto-promotion blocked, manual review required",
            })

    return {
        "agro_zone": agro_zone,
        "fpr_threshold": DEFAULT_FPR_THRESHOLD,
        "model_versions": versions,
        "fpr_alerts": alerts,
        "has_alerts": len(alerts) > 0,
    }


# ---------------------------------------------------------------------------
# Analytics (per-plot NIR/NDVI/rainfall/temperature + crop/soil/state/district
# breakdowns) -- backs the institutional Analytics view.
# ---------------------------------------------------------------------------

@router.get("/analytics")
def get_analytics(
    state: str | None = None,
    district: str | None = None,
    crop: str | None = None,
    soil: str | None = None,
    window_days: int = 30,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """
    NIR here is the NIR-API's predicted irrigation-risk percentage (from
    ml_predictions.input_feature_snapshot, provider == "nir_api"), the same
    convention already used by /dashboard/aggregates. This is a different
    metric from the raw Sentinel-2 NIR spectral band stored in satellite_data
    (used by /institutional/plots/map and /institutional/plots/{id}/history) --
    the two share a name but are not the same value.
    """
    try:
        state, district = _enforce_scope(current_user, state, district)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    scope = _scope_query(db, state=state, district=district, crop=crop, soil=soil)
    plot_id_subq = scope.with_entities(Plot.plot_id)
    total_plots = scope.count()
    scope_name = _scope_label(state, district)

    empty: dict[str, object] = {
        "scope": scope_name,
        "window_days": window_days,
        "suppressed": True,
        "observations": [],
        "crop_summary": [],
        "soil_summary": [],
        "state_summary": [],
        "alerts_by_district": [],
        "nir_rainfall_points": [],
    }
    if total_plots < MIN_AGGREGATION_THRESHOLD:
        return empty

    window_start = utc_now() - timedelta(days=window_days)
    latest_advisories = _latest_advisories_by_plot(db, plot_id_subq, window_start)
    prediction_ids_subq = db.query(Advisory.prediction_id).filter(
        Advisory.plot_id.in_(plot_id_subq), Advisory.created_at >= window_start
    )
    predictions = (
        db.query(MlPrediction.prediction_id, MlPrediction.input_feature_snapshot)
        .filter(MlPrediction.prediction_id.in_(prediction_ids_subq))
        .all()
        if latest_advisories
        else []
    )
    prediction_by_id = {prediction.prediction_id: prediction for prediction in predictions}

    nir_by_plot: dict[str, float] = {}
    urgency_by_plot: dict[str, str] = {}
    for plot_id, advisory in latest_advisories.items():
        urgency_by_plot[plot_id] = _ADVISORY_URGENCY.get(advisory.advisory_class, "MODERATE")
        prediction = prediction_by_id.get(advisory.prediction_id)
        if prediction is None:
            continue
        snapshot = prediction.input_feature_snapshot or {}
        if snapshot.get("provider") == "nir_api" and snapshot.get("nir_percent") is not None:
            nir_by_plot[plot_id] = float(snapshot["nir_percent"])

    feature_rows = (
        db.query(PlotFeatures.plot_id, PlotFeatures.obs_date, PlotFeatures.ndvi, PlotFeatures.rainfall_7d, PlotFeatures.lst)
        .filter(PlotFeatures.plot_id.in_(plot_id_subq), PlotFeatures.obs_date >= window_start.date())
        .order_by(PlotFeatures.obs_date.desc())
        .all()
    )
    latest_feature_by_plot: dict[str, object] = {}
    for row in feature_rows:
        latest_feature_by_plot.setdefault(row.plot_id, row)  # desc order -> first seen is latest

    plot_lookup = {plot.plot_id: plot for plot in scope.all()}

    observations: list[dict[str, object]] = []
    for plot_id, nir_percent in nir_by_plot.items():
        plot = plot_lookup.get(plot_id)
        if plot is None:
            continue
        feature = latest_feature_by_plot.get(plot_id)
        observations.append({
            "plot_id": plot_id,
            "district": plot.farmer.district,
            "state": plot.farmer.state,
            "crop": plot.crop_type,
            "soil_texture": plot.soil_texture,
            "nir_percent": nir_percent,
            "ndvi": float(feature.ndvi) if feature and feature.ndvi is not None else None,
            "rainfall_7d": float(feature.rainfall_7d) if feature and feature.rainfall_7d is not None else None,
            "temperature": float(feature.lst) if feature and feature.lst is not None else None,
            "urgency": urgency_by_plot.get(plot_id, "UNKNOWN"),
        })

    def _grouped(key_fn) -> list[dict[str, object]]:
        groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"nir": [], "ndvi": [], "rainfall": []})
        for obs in observations:
            key = key_fn(obs)
            if not key:
                continue
            groups[key]["nir"].append(obs["nir_percent"])
            if obs["ndvi"] is not None:
                groups[key]["ndvi"].append(obs["ndvi"])
            if obs["rainfall_7d"] is not None:
                groups[key]["rainfall"].append(obs["rainfall_7d"])
        return [
            {
                "name": name,
                "count": len(values["nir"]),
                "avg_nir": round(sum(values["nir"]) / len(values["nir"]), 1) if values["nir"] else None,
                "avg_ndvi": round(sum(values["ndvi"]) / len(values["ndvi"]), 4) if values["ndvi"] else None,
                "avg_rainfall_7d": round(sum(values["rainfall"]) / len(values["rainfall"]), 2) if values["rainfall"] else None,
            }
            for name, values in sorted(groups.items())
        ]

    crop_summary = _grouped(lambda obs: obs["crop"])
    soil_summary = _grouped(lambda obs: obs["soil_texture"])
    state_summary = _grouped(lambda obs: obs["state"])

    # NIR-risk vs rainfall, backing the Analytics page's "NIR vs rainfall"
    # chart -- one point per (rainfall, nir_percent) observation, not a
    # day-averaged trend. Rainfall is randomized independently per plot per
    # day in the underlying data, so averaging across thousands of plots each
    # day cancels the real per-plot relationship out by the law of large
    # numbers (verified: day-level means barely move even though the
    # per-observation correlation is a genuine, strong -0.86). A scatter of
    # the actual observations is the statistically correct way to show it.
    all_predictions = (
        db.query(MlPrediction.input_feature_snapshot)
        .filter(MlPrediction.plot_id.in_(plot_id_subq), MlPrediction.predicted_at >= window_start)
        .all()
    )
    nir_rainfall_points = [
        {
            "rainfall_mm": float(snapshot["rainfall_mm"]),
            "nir_percent": float(snapshot["nir_percent"]),
        }
        for prediction in all_predictions
        if (snapshot := (prediction.input_feature_snapshot or {})).get("nir_percent") is not None
        and snapshot.get("rainfall_mm") is not None
    ]
    # Cap the payload/render cost -- deterministic stride sample, not a
    # truncation, so the sample still spans the full rainfall range.
    max_points = 400
    if len(nir_rainfall_points) > max_points:
        stride = len(nir_rainfall_points) // max_points
        nir_rainfall_points = nir_rainfall_points[::stride][:max_points]

    # Was: fetch Alert rows then lazy-access alert.plot.farmer.district per
    # row -- neither Plot nor Farmer was eager-loaded, so this issued up to
    # two extra queries PER ALERT (tens of thousands, for a national scope).
    # Selecting severity + district directly via the same joins is a single
    # query with no relationship traversal at all.
    alert_rows = (
        db.query(Alert.severity, Farmer.district)
        .join(Plot, Plot.plot_id == Alert.plot_id)
        .join(Farmer, Farmer.farmer_id == Plot.farmer_id)
        .filter(Alert.plot_id.in_(plot_id_subq))
        .all()
    )
    district_severity: dict[str, Counter] = defaultdict(Counter)
    for severity, district_name in alert_rows:
        district_severity[district_name or "Unknown"][severity] += 1
    alerts_by_district = [
        {
            "name": name,
            "safe": counts.get("SAFE", 0),
            "moderate": counts.get("MODERATE", 0),
            "high": counts.get("HIGH", 0),
            "urgent": counts.get("URGENT", 0),
        }
        for name, counts in sorted(district_severity.items())
    ]

    return {
        "scope": scope_name,
        "window_days": window_days,
        "suppressed": False,
        "observations": observations,
        "crop_summary": crop_summary,
        "soil_summary": soil_summary,
        "state_summary": state_summary,
        "alerts_by_district": alerts_by_district,
        "nir_rainfall_points": nir_rainfall_points,
    }
