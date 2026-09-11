from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import AdvisoryFeedback, Farmer, Plot
from app.routers.institutional_auth import require_admin
from app.services.ingestion_service import IngestionService
from app.services.ml_prediction_service import MLPredictionService
from app.services.ml_training_service import MLTrainingService
from app.services.messaging_service import MessagingService
from app.services.sms_template_service import SMSTemplateService

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_admin)])


@router.post("/ingestion/trigger")
def trigger_ingestion(
    use_mock: bool = Query(
        False,
        description="Use generated data instead of configured live ingestion providers.",
    ),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    plots = db.query(Plot).filter(Plot.status == "active").all()
    service = IngestionService(db)
    ingested = 0
    for plot in plots:
        ingested += len(service.fetch_plot_cycle(plot.plot_id, use_mock=use_mock))
    return {"status": "queued", "message": "Ingestion cycle completed", "plots_processed": len(plots), "records_ingested": ingested}


@router.post("/predictions/run")
def run_prediction(db: Session = Depends(get_db)) -> dict[str, object]:
    plots = db.query(Plot).filter(Plot.status == "active").all()
    service = MLPredictionService(db)
    saved = 0
    skipped = 0
    for plot in plots:
        try:
            result = service.predict_irrigation_stress(plot.plot_id)
            service.save_prediction(result)
            saved += 1
        except ValueError:
            skipped += 1
    return {"status": "queued", "message": "Prediction run completed", "plots_processed": len(plots), "predictions_saved": saved, "plots_skipped": skipped}


@router.post("/advisories/generate")
def generate_advisory(db: Session = Depends(get_db)) -> dict[str, object]:
    plots = db.query(Plot).filter(Plot.status == "active").all()
    sms_service = SMSTemplateService(db)
    sms_service.get_or_create_templates()
    prediction_service = MLPredictionService(db)

    generated = 0
    skipped = 0
    for plot in plots:
        farmer = db.query(Farmer).filter(Farmer.farmer_id == plot.farmer_id).first()
        if not farmer:
            skipped += 1
            continue
        try:
            prediction = prediction_service.predict_irrigation_stress(plot.plot_id)
            saved_pred = prediction_service.save_prediction(prediction)
            message = sms_service.generate_advisory_message(
                farmer_id=farmer.farmer_id,
                farmer_phone=farmer.phone_number,
                plot_id=plot.plot_id,
                crop_type=plot.crop_type,
                language=farmer.preferred_language or "en",
                advisory_class=prediction.advisory_class,
                reason_code=prediction.reason_code,
                confidence=prediction.confidence_score,
            )
            if not message:
                skipped += 1
                continue
            should_send = prediction.advisory_class != "no_action"
            advisory = sms_service.create_advisory_record(message, saved_pred.prediction_id, sms_sent=should_send)
            if should_send:
                messaging = MessagingService(db)
                try:
                    messaging.ensure_sms_capacity(farmer.farmer_id)
                    sms_service.log_sms_send(
                        advisory.advisory_id, farmer.farmer_id, farmer.phone_number, message.message_text
                    )
                    if prediction.advisory_class == "irrigate_now":
                        messaging.send_ivr(farmer.phone_number, message.message_text)
                        advisory.ivr_triggered = True
                        db.commit()
                except Exception:
                    skipped += 1
                    continue
            generated += 1
        except ValueError:
            skipped += 1

    return {"status": "queued", "message": "Advisory generation completed", "plots_processed": len(plots), "advisories_generated": generated, "plots_skipped": skipped}


@router.post("/retraining/run")
def run_retraining(
    agro_zone: str = Query("yavatmal-mh", description="Agro-climatic zone scope for the model version."),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """
    Full retrain cycle (doc 13.5): build dataset from canonical plot_features
    rows, temporal split, fit XGBoost, evaluate, log to model_evaluation_runs
    with the FPR promotion gate, and persist the artifact for serving.

    The promoted artifact is picked up automatically by SoilMoistureModel on
    the next prediction -- no restart required.
    """
    feedback_count = db.query(AdvisoryFeedback).count()
    result = MLTrainingService(db).run_retraining(agro_zone=agro_zone)
    return {
        "status": result.status,
        "message": result.message,
        "feedback_records_seen": feedback_count,
        "training": result.to_dict(),
    }


@router.post("/sms/retry")
def retry_sms(db: Session = Depends(get_db)) -> dict[str, object]:
    return {"status": "completed", "messages_retried": MessagingService(db).retry_failed()}
