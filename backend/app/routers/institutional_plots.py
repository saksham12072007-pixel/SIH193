import json
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Advisory, InstitutionalUser, Plot, PlotFeatures, SatelliteData
from app.routers.institutional_auth import get_current_institutional_user
from app.schemas.institutional import (
    InstitutionalPlotMarker,
    PlotHistoryPoint,
    PlotHistoryResponse,
)

router = APIRouter(prefix="/institutional/plots", tags=["institutional-plots"])
_POINT_RE = re.compile(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.I)


def _scope_allowed(user: InstitutionalUser, plot: Plot) -> bool:
    if user.role == "admin":
        return True
    assigned = user.assigned_geography or {}
    states = set(assigned.get("states", []))
    districts = set(assigned.get("districts", []))
    farmer = plot.farmer
    return (
        (not states or farmer.state in states)
        and (not districts or farmer.district in districts)
    )


def _coordinates(location_point: str | None) -> tuple[float, float] | None:
    if not location_point:
        return None
    match = _POINT_RE.fullmatch(location_point.strip())
    if not match:
        return None
    longitude, latitude = (float(value) for value in match.groups())
    return latitude, longitude


def _numeric_value(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            for key in ("nir", "nir_percent", "value"):
                if parsed.get(key) is not None:
                    return float(parsed[key])
            return None
        return float(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _urgency_for_advisory(advisory_class: str | None) -> str:
    return {
        "no_action": "SAFE",
        "monitor": "MODERATE",
        "irrigate_soon": "HIGH",
        "irrigate_now": "URGENT",
    }.get((advisory_class or "").lower(), "UNKNOWN")


def _latest_satellite(
    rows: list[SatelliteData], data_type: str
) -> dict[date, float]:
    values: dict[date, float] = {}
    for row in rows:
        if row.data_type.lower() != data_type:
            continue
        value = _numeric_value(row.value)
        if value is not None:
            values[row.observation_date.date()] = value
    return values


@router.get("/map", response_model=list[InstitutionalPlotMarker])
def get_plot_markers(
    state: str | None = None,
    district: str | None = None,
    crop: str | None = None,
    soil: str | None = None,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> list[InstitutionalPlotMarker]:
    """Return rounded plot markers for an authorized institutional scope."""
    query = db.query(Plot).join(Plot.farmer).filter(Plot.status == "active")
    if state:
        query = query.filter(Plot.farmer.has(state=state))
    if district:
        query = query.filter(Plot.farmer.has(district=district))
    if crop:
        query = query.filter(Plot.crop_type == crop)
    if soil:
        query = query.filter(Plot.soil_texture == soil)

    plots = [plot for plot in query.all() if _scope_allowed(current_user, plot)]
    plot_ids = [plot.plot_id for plot in plots]
    latest_features = {}
    if plot_ids:
        latest_feature_dates = (
            db.query(
                PlotFeatures.plot_id,
                func.max(PlotFeatures.obs_date).label("latest_date"),
            )
            .filter(PlotFeatures.plot_id.in_(plot_ids))
            .group_by(PlotFeatures.plot_id)
            .subquery()
        )
        latest_features = {
            feature.plot_id: feature
            for feature in db.query(PlotFeatures)
            .join(
                latest_feature_dates,
                and_(
                    PlotFeatures.plot_id == latest_feature_dates.c.plot_id,
                    PlotFeatures.obs_date == latest_feature_dates.c.latest_date,
                ),
            )
            .all()
        }

    latest_nir = {}
    if plot_ids:
        latest_nir_dates = (
            db.query(
                SatelliteData.plot_id,
                func.max(SatelliteData.observation_date).label("latest_date"),
            )
            .filter(
                SatelliteData.plot_id.in_(plot_ids),
                SatelliteData.data_type == "nir",
            )
            .group_by(SatelliteData.plot_id)
            .subquery()
        )
        latest_nir = {
            satellite.plot_id: satellite
            for satellite in db.query(SatelliteData)
            .join(
                latest_nir_dates,
                and_(
                    SatelliteData.plot_id == latest_nir_dates.c.plot_id,
                    SatelliteData.observation_date == latest_nir_dates.c.latest_date,
                ),
            )
            .all()
        }

    latest_advisories = {}
    if plot_ids:
        latest_advisory_dates = (
            db.query(
                Advisory.plot_id,
                func.max(Advisory.created_at).label("latest_date"),
            )
            .filter(Advisory.plot_id.in_(plot_ids))
            .group_by(Advisory.plot_id)
            .subquery()
        )
        latest_advisories = {
            advisory.plot_id: advisory
            for advisory in db.query(Advisory)
            .join(
                latest_advisory_dates,
                and_(
                    Advisory.plot_id == latest_advisory_dates.c.plot_id,
                    Advisory.created_at == latest_advisory_dates.c.latest_date,
                ),
            )
            .all()
        }

    markers: list[InstitutionalPlotMarker] = []
    for plot in plots:
        coordinates = _coordinates(plot.location_point)
        if coordinates is None:
            continue
        latitude, longitude = coordinates
        latest_feature = latest_features.get(plot.plot_id)
        latest_satellite = latest_nir.get(plot.plot_id)
        latest_advisory = latest_advisories.get(plot.plot_id)
        urgency = _urgency_for_advisory(
            latest_advisory.advisory_class if latest_advisory else None
        )
        markers.append(
            InstitutionalPlotMarker(
                plot_id=plot.plot_id,
                farmer_id=plot.farmer_id,
                crop=plot.crop_type,
                state=plot.farmer.state,
                district=plot.farmer.district,
                village=plot.village_name,
                latitude=round(latitude, 4),
                longitude=round(longitude, 4),
                location_precision=plot.location_precision,
                observed_at=latest_feature.updated_at if latest_feature else None,
                ndvi=float(latest_feature.ndvi) if latest_feature and latest_feature.ndvi is not None else None,
                nir=_numeric_value(latest_satellite.value) if latest_satellite else None,
                status=urgency if urgency != "UNKNOWN" else plot.data_status,
                urgency=urgency,
            )
        )
    return markers


@router.get("/{plot_id}/history", response_model=PlotHistoryResponse)
def get_plot_history(
    plot_id: str,
    days: int = Query(default=90, ge=1, le=730),
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> PlotHistoryResponse:
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if plot is None:
        raise HTTPException(status_code=404, detail="Plot not found")
    if not _scope_allowed(current_user, plot):
        raise HTTPException(status_code=403, detail="Plot is outside assigned geography")

    start_date = date.today() - timedelta(days=days)
    features = (
        db.query(PlotFeatures)
        .filter(PlotFeatures.plot_id == plot_id, PlotFeatures.obs_date >= start_date)
        .order_by(PlotFeatures.obs_date.asc())
        .all()
    )
    satellite = (
        db.query(SatelliteData)
        .filter(
            SatelliteData.plot_id == plot_id,
            SatelliteData.observation_date >= datetime.combine(start_date, datetime.min.time()),
        )
        .all()
    )
    nir_by_date = _latest_satellite(satellite, "nir")
    feature_dates = {feature.obs_date for feature in features}
    dates = sorted(feature_dates | set(nir_by_date))
    series = [
        PlotHistoryPoint(
            date=observation_date,
            ndvi=next(
                (float(feature.ndvi) for feature in features if feature.obs_date == observation_date and feature.ndvi is not None),
                None,
            ),
            nir=nir_by_date.get(observation_date),
            rainfall_7d=next(
                (
                    float(feature.rainfall_7d)
                    for feature in features
                    if feature.obs_date == observation_date and feature.rainfall_7d is not None
                ),
                None,
            ),
        )
        for observation_date in dates
    ]
    return PlotHistoryResponse(
        plot_id=plot.plot_id,
        crop=plot.crop_type,
        location_precision=plot.location_precision,
        series=series,
    )
