"""
In-process background scheduler -- periodically runs ingest+predict for all
active plots so data and predictions stay live without an external cron.

Opens its own DB session per cycle (SessionLocal, not the request-scoped
get_db generator) since jobs run outside any request lifecycle.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.models import Plot
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


def run_pipeline_cycle() -> None:
    """Ingest (and, via auto-chaining, predict) for every active plot."""
    db = SessionLocal()
    processed = 0
    failed = 0
    try:
        plots = db.query(Plot).filter(Plot.status == "active").all()
        service = IngestionService(db)
        for plot in plots:
            try:
                service.fetch_plot_cycle(plot.plot_id)
                processed += 1
            except Exception:
                failed += 1
                logger.exception("Scheduled pipeline cycle failed for plot=%s", plot.plot_id)
        logger.info("Scheduled pipeline cycle complete: processed=%d failed=%d", processed, failed)
    finally:
        db.close()


class PipelineScheduler:
    """Wraps an APScheduler BackgroundScheduler running run_pipeline_cycle on an interval."""

    def __init__(self) -> None:
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        if self._scheduler is not None:
            return
        interval_minutes = get_settings().scheduler_interval_minutes
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            run_pipeline_cycle,
            "interval",
            minutes=interval_minutes,
            id="pipeline_cycle",
        )
        scheduler.start()
        self._scheduler = scheduler
        logger.info("PipelineScheduler started: interval_minutes=%d", interval_minutes)

    def stop(self) -> None:
        if self._scheduler is None:
            return
        self._scheduler.shutdown(wait=False)
        self._scheduler = None
        logger.info("PipelineScheduler stopped")
