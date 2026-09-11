import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.auth import verify_farmer_session_token
from app.models import Farmer, Plot
from app.schemas.plot import PlotCreate, PlotRead
from app.utils.audit import AuditEventType, log_audit_event
from app.utils.geospatial import generate_buffer_polygon, validate_india_bounds

router = APIRouter(prefix="/plots", tags=["plots"])
SUPPORTED_CROP_TYPES = {"rice", "wheat", "maize", "cotton", "sugarcane", "millet", "pulses", "soybean"}


def _is_owner_session(session_token: str | None, farmer_id: str) -> bool:
    if not session_token:
        return False
    try:
        payload = verify_farmer_session_token(session_token)
    except HTTPException:
        return False
    return payload.get("farmer_id") == farmer_id


def _mask_plot(plot: Plot) -> Plot:
    return Plot(
        plot_id=plot.plot_id,
        farmer_id=plot.farmer_id,
        plot_nickname=plot.plot_nickname,
        location_point=None,
        location_precision=plot.location_precision,
        village_name=None,
        buffer_polygon=None,
        crop_type=plot.crop_type,
        plot_size_declared=plot.plot_size_declared,
        sowing_date=plot.sowing_date,
        status=plot.status,
        created_at=plot.created_at,
        updated_at=plot.updated_at,
        soil_texture=plot.soil_texture,
        soil_awc=plot.soil_awc,
        irrigation_type=plot.irrigation_type,
        ingestion_failure_count=plot.ingestion_failure_count,
        data_status=plot.data_status,
        last_ingestion_at=plot.last_ingestion_at,
    )


@router.post("/create", response_model=PlotRead, status_code=status.HTTP_201_CREATED)
def create_plot(payload: PlotCreate, db: Session = Depends(get_db)) -> Plot:
    farmer = db.query(Farmer).filter(Farmer.farmer_id == payload.farmer_id).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")

    if not farmer.consent_given_at:
        raise HTTPException(status_code=400, detail="Farmer consent is required before plot registration")

    normalized_crop = payload.crop_type.strip().lower()
    if normalized_crop not in SUPPORTED_CROP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported crop type '{payload.crop_type}'. Allowed values: {', '.join(sorted(SUPPORTED_CROP_TYPES))}",
        )

    location_precision = "gps"
    buffer_polygon_wkt = None

    if payload.latitude is not None and payload.longitude is not None:
        if not validate_india_bounds(payload.latitude, payload.longitude):
            raise HTTPException(status_code=400, detail="Plot location must be within India")
        buffer_poly = generate_buffer_polygon(payload.latitude, payload.longitude, buffer_radius_meters=50)
        buffer_polygon_wkt = buffer_poly.wkt
        location_precision = "gps"
    elif payload.village_name:
        location_precision = "village_fallback"
    else:
        raise HTTPException(status_code=400, detail="Latitude/longitude or village fallback is required")

    plot = Plot(
        plot_id=str(uuid.uuid4()),
        farmer_id=payload.farmer_id,
        plot_nickname=payload.plot_nickname or f"Plot {len(farmer.plots) + 1}",
        location_point=(
            f"POINT ({payload.longitude} {payload.latitude})"
            if payload.latitude is not None and payload.longitude is not None
            else None
        ),
        location_precision=location_precision,
        village_name=payload.village_name,
        buffer_polygon=buffer_polygon_wkt,
        crop_type=normalized_crop,
        plot_size_declared=payload.plot_size_declared,
        sowing_date=payload.sowing_date,
        soil_texture=payload.soil_texture.strip().lower() if payload.soil_texture else None,
        irrigation_type=payload.irrigation_type.strip().lower() if payload.irrigation_type else None,
        status="active",
    )

    db.add(plot)
    db.commit()
    db.refresh(plot)

    log_audit_event(
        db,
        str(uuid.uuid4()),
        AuditEventType.PLOT_CREATED,
        farmer_id=payload.farmer_id,
        entity_type="plot",
        entity_id=plot.plot_id,
        details=f"Plot created: {normalized_crop} in {location_precision} precision",
    )

    return plot


@router.get("/{farmer_id}", response_model=list[PlotRead])
def list_plots(farmer_id: str, session_token: str | None = None, db: Session = Depends(get_db)) -> list[Plot]:
    farmer = db.query(Farmer).filter(Farmer.farmer_id == farmer_id).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")
    plots = db.query(Plot).filter(Plot.farmer_id == farmer_id).order_by(Plot.created_at.desc()).all()
    return plots if _is_owner_session(session_token, farmer_id) else [_mask_plot(plot) for plot in plots]


@router.get("/plot/{plot_id}", response_model=PlotRead)
def get_plot(plot_id: str, session_token: str | None = None, db: Session = Depends(get_db)) -> Plot:
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")
    return plot if _is_owner_session(session_token, plot.farmer_id) else _mask_plot(plot)
