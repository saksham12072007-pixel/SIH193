from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.routers.institutional_auth import require_admin
from app.services.data_quality_service import compute_data_quality

router = APIRouter(prefix="/institutional/data-quality", tags=["institutional-data-quality"], dependencies=[Depends(require_admin)])


@router.get("")
def get_data_quality(window_days: int = 14, db: Session = Depends(get_db)) -> dict[str, object]:
    return compute_data_quality(db, window_days=window_days)
