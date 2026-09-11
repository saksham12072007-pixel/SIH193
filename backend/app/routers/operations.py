from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Advisory, Alert, Farmer, InstitutionalUser, MlPrediction, Plot, SatelliteData, SmsLog
from app.routers.alerts import _sync_alerts
from app.routers.institutional_auth import get_current_institutional_user
from app.utils.time import utc_now

router = APIRouter(prefix="/institutional/operations", tags=["institutional-operations"])


def _apply_scope(query, current_user: InstitutionalUser, state: str | None, district: str | None):
    """Same RBAC scoping as _plot_allowed used to do row-by-row in Python,
    pushed into the query itself so it's one indexed SQL filter instead of a
    per-plot lazy-load of `plot.farmer` (an N+1 that was part of why this
    endpoint took 6+ seconds against a few thousand plots)."""
    if state:
        query = query.filter(Farmer.state == state)
    if district:
        query = query.filter(Farmer.district == district)
    if current_user.role != "admin":
        geography = current_user.assigned_geography or {}
        if geography.get("districts"):
            query = query.filter(Farmer.district.in_(geography["districts"]))
        elif geography.get("states"):
            query = query.filter(Farmer.state.in_(geography["states"]))
        else:
            query = query.filter(False)  # noqa: FBT003 -- no assigned geography -> nothing visible
    return query


@router.get("/status")
def get_operations_status(
    state: str | None = None,
    district: str | None = None,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """
    Return aggregate workflow health without exposing farmer message content.

    Every metric here is a SQL-side COUNT/GROUP BY against a scoped plot_id
    subquery, never a Python loop over materialized rows -- with tens of
    thousands of satellite_data/advisory/prediction rows in a real (or
    heavily-seeded demo) deployment, loading full ORM objects just to feed
    them into a Counter() made this endpoint take 6+ seconds.
    """
    scoped_plots = _apply_scope(
        db.query(Plot.plot_id, Plot.farmer_id, Plot.data_status, Plot.last_ingestion_at)
        .join(Farmer, Farmer.farmer_id == Plot.farmer_id)
        .filter(Plot.status == "active"),
        current_user, state, district,
    )
    plot_ids_subq = scoped_plots.with_entities(Plot.plot_id).subquery()
    farmer_ids_subq = scoped_plots.with_entities(Plot.farmer_id).distinct().subquery()

    recent_cutoff = utc_now() - timedelta(hours=24)

    total_active = scoped_plots.count()
    ingestion = dict(
        scoped_plots.with_entities(Plot.data_status, func.count(Plot.plot_id))
        .group_by(Plot.data_status).all()
    )
    recent_ingestion = scoped_plots.filter(Plot.last_ingestion_at >= recent_cutoff).count()

    _sync_alerts(db)

    observations_query = db.query(SatelliteData).filter(
        SatelliteData.plot_id.in_(plot_ids_subq.select()),
        SatelliteData.ingestion_status == "success",
    )
    successful_observations = observations_query.with_entities(func.count(SatelliteData.satellite_id)).scalar()
    sources = dict(
        observations_query.with_entities(SatelliteData.data_source, func.count(SatelliteData.satellite_id))
        .group_by(SatelliteData.data_source).all()
    )
    is_synthetic_expr = func.coalesce(SatelliteData.quality_flag == "synthetic_demo", False)
    provenance_raw = dict(
        observations_query.with_entities(
            is_synthetic_expr,
            func.count(SatelliteData.satellite_id),
        ).group_by(is_synthetic_expr).all()
    )
    provenance = {("synthetic_demo" if is_synthetic else "provider"): count for is_synthetic, count in provenance_raw.items()}

    predictions_query = db.query(MlPrediction).filter(MlPrediction.plot_id.in_(plot_ids_subq.select()))
    predictions_total = predictions_query.with_entities(func.count(MlPrediction.prediction_id)).scalar()
    predictions_last_24h = predictions_query.filter(MlPrediction.predicted_at >= recent_cutoff).with_entities(
        func.count(MlPrediction.prediction_id)
    ).scalar()

    advisories_query = db.query(Advisory).filter(Advisory.plot_id.in_(plot_ids_subq.select()))
    advisories_total = advisories_query.with_entities(func.count(Advisory.advisory_id)).scalar()
    advisories_last_24h = advisories_query.filter(Advisory.created_at >= recent_cutoff).with_entities(
        func.count(Advisory.advisory_id)
    ).scalar()

    alerts_query = db.query(Alert).filter(Alert.plot_id.in_(plot_ids_subq.select()))
    alerts_total = alerts_query.with_entities(func.count(Alert.alert_id)).scalar()
    lifecycle = dict(
        alerts_query.with_entities(Alert.status, func.count(Alert.alert_id)).group_by(Alert.status).all()
    )

    sms_query = db.query(SmsLog).filter(SmsLog.farmer_id.in_(farmer_ids_subq.select()))
    total_messages = sms_query.with_entities(func.count(SmsLog.sms_log_id)).scalar()
    delivery = dict(
        sms_query.with_entities(SmsLog.delivery_status, func.count(SmsLog.sms_log_id)).group_by(SmsLog.delivery_status).all()
    )

    return {
        "scope": {"state": state, "district": district},
        "generated_at": utc_now().isoformat(),
        "plots": {
            "active": total_active,
            "data_status": ingestion,
            "ingested_last_24h": recent_ingestion,
            "successful_observations": successful_observations,
            "by_source": sources,
            "provenance": provenance,
        },
        "processing": {
            "predictions_total": predictions_total,
            "predictions_last_24h": predictions_last_24h,
            "advisories_total": advisories_total,
            "advisories_last_24h": advisories_last_24h,
        },
        "alerts": {
            "total": alerts_total,
            "by_status": lifecycle,
        },
        "delivery": {
            "total_messages": total_messages,
            "by_status": delivery,
            "delivered_rate_percent": round(
                (delivery.get("delivered", 0) / total_messages) * 100, 1
            ) if total_messages else None,
        },
    }
