"""
Advisory generation, SMS delivery, and feedback endpoints.

Changes per 12_Backend_Changes_Required.md:
  POST /advisories/generate/{plot_id}   -- now calls Stage1 -> Stage2 internally (sec 12.2)
  POST /advisories/feedback/{advisory_id} -- snapshots predicted_class/confidence/soil_moisture
                                             and model_version at time of advisory (sec 12.1 / 12.2)
"""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.db.database import get_db
from app.models import Advisory, AdvisoryFeedback, Farmer, MlPrediction, Plot
from app.services.ml_prediction_service import MLPredictionService
from app.services.messaging_service import MessagingService
from app.services.sms_template_service import SMSTemplateService

router = APIRouter(prefix="/advisories", tags=["advisories"])


@router.post("/generate/{plot_id}", status_code=status.HTTP_201_CREATED)
def generate_and_send_advisory(plot_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Generate an advisory for a plot and log the SMS send.

    Internally calls Stage 1 (soil moisture regression) then Stage 2
    (rule-based decision layer) -- kept as a two-step pipeline so Stage 1
    output is inspectable independently of the final advisory (sec 12.2).
    """
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    farmer = db.query(Farmer).filter(Farmer.farmer_id == plot.farmer_id).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")

    if plot.status == "paused":
        return {
            "status": "skipped",
            "reason": "Plot has advisory paused by farmer",
            "plot_id": plot_id,
        }
    if plot.data_status == "data_unavailable":
        return {
            "status": "skipped",
            "reason": "Plot data is unavailable after repeated ingestion failures",
            "plot_id": plot_id,
        }

    # Stage 1 -> Stage 2 pipeline (sec 12.2)
    ml_service = MLPredictionService(db)
    try:
        prediction = ml_service.predict_irrigation_stress(plot_id)
        saved_pred = ml_service.save_prediction(prediction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sms_service = SMSTemplateService(db)
    sms_service.get_or_create_templates()
    message = sms_service.generate_advisory_message(
        farmer_id=farmer.farmer_id,
        farmer_phone=farmer.phone_number,
        plot_id=plot_id,
        crop_type=plot.crop_type,
        language=farmer.preferred_language or "en",
        advisory_class=prediction.advisory_class,
        reason_code=prediction.reason_code,
        confidence=prediction.confidence_score,
    )
    if not message:
        raise HTTPException(status_code=500, detail="Failed to generate advisory message")

    should_send = prediction.advisory_class != "no_action"
    advisory = sms_service.create_advisory_record(message, saved_pred.prediction_id, sms_sent=should_send)
    if should_send:
        messaging = MessagingService(db)
        try:
            messaging.ensure_sms_capacity(farmer.farmer_id)
            sms_service.log_sms_send(
                advisory_id=advisory.advisory_id,
                farmer_id=farmer.farmer_id,
                farmer_phone=farmer.phone_number,
                message_text=message.message_text,
            )
            if prediction.advisory_class == "irrigate_now":
                messaging.send_ivr(farmer.phone_number, message.message_text)
                advisory.ivr_triggered = True
                db.commit()
        except HTTPException as exc:
            if exc.status_code == 429:
                advisory.sms_sent = False
                db.commit()
                return {
                    "advisory_id": advisory.advisory_id,
                    "prediction_id": saved_pred.prediction_id,
                    "plot_id": plot_id,
                    "farmer_phone": farmer.phone_number,
                    "advisory_class": advisory.advisory_class,
                    "reason_code": saved_pred.reason_code,
                    "message": message.message_text,
                    "priority": message.priority.value,
                    "language": advisory.language_used,
                    "sms_status": "suppressed_quota",
                    "model_version": saved_pred.model_version,
                    "stage1_soil_moisture_pct": float(saved_pred.stage1_soil_moisture_estimate) if saved_pred.stage1_soil_moisture_estimate is not None else None,
                    "nir_percent": (prediction.explanation or {}).get("nir_percent"),
                    "urgency": (prediction.explanation or {}).get("urgency"),
                    "fallback_used": (prediction.explanation or {}).get("fallback_used", False),
                }
            raise

    return {
        "advisory_id": advisory.advisory_id,
        "prediction_id": saved_pred.prediction_id,
        "plot_id": plot_id,
        "farmer_phone": farmer.phone_number,
        "advisory_class": advisory.advisory_class,
        "reason_code": saved_pred.reason_code,
        "message": message.message_text,
        "priority": message.priority.value,
        "language": advisory.language_used,
        "sms_status": "sent" if should_send else "not_sent_no_action",
        "model_version": saved_pred.model_version,
        "stage1_soil_moisture_pct": float(saved_pred.stage1_soil_moisture_estimate) if saved_pred.stage1_soil_moisture_estimate is not None else None,
        "nir_percent": (prediction.explanation or {}).get("nir_percent"),
        "urgency": (prediction.explanation or {}).get("urgency"),
        "fallback_used": (prediction.explanation or {}).get("fallback_used", False),
    }


@router.get("/{advisory_id}")
def get_advisory(advisory_id: str, db: Session = Depends(get_db)) -> dict:
    """Retrieve advisory details."""
    advisory = db.query(Advisory).filter(Advisory.advisory_id == advisory_id).first()
    if not advisory:
        raise HTTPException(status_code=404, detail="Advisory not found")

    return {
        "advisory_id": advisory.advisory_id,
        "plot_id": advisory.plot_id,
        "prediction_id": advisory.prediction_id,
        "advisory_class": advisory.advisory_class,
        "template_id": advisory.template_id,
        "language_used": advisory.language_used,
        "sms_sent": advisory.sms_sent,
        "ivr_triggered": advisory.ivr_triggered,
        "created_at": advisory.created_at.isoformat(),
    }


@router.post("/feedback/{advisory_id}")
def record_advisory_feedback(
    advisory_id: str,
    feedback_score: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    Record farmer feedback on an advisory.

    sec 12.1 / 12.2 -- Snapshots predicted_class, predicted_confidence,
    predicted_soil_moisture and model_version at time of advisory so that
    Precision/Recall/F1/FPR and RMSE/MAE can be computed per model version
    after the fact from live feedback data.

    Feedback codes: 1=irrigated, 2=not_needed, 3=crop_damaged
    """
    advisory = db.query(Advisory).filter(Advisory.advisory_id == advisory_id).first()
    if not advisory:
        raise HTTPException(status_code=404, detail="Advisory not found")

    reply_map = {1: "irrigated", 2: "not_needed", 3: "crop_damaged"}
    if feedback_score not in reply_map:
        raise HTTPException(status_code=400, detail="Feedback score must be one of: 1, 2, 3")

    farmer = db.query(Farmer).filter(Farmer.farmer_id == advisory.plot.farmer_id).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")

    # Snapshot the prediction state at advisory time (sec 12.1 / 12.2)
    pred = db.query(MlPrediction).filter(
        MlPrediction.prediction_id == advisory.prediction_id
    ).first()

    predicted_class = None
    predicted_confidence = None
    predicted_soil_moisture = None
    model_version = None

    if pred:
        predicted_class = pred.advisory_class
        predicted_confidence = float(pred.confidence_score) if pred.confidence_score is not None else None
        predicted_soil_moisture = float(pred.stage1_soil_moisture_estimate) if pred.stage1_soil_moisture_estimate is not None else None
        model_version = pred.model_version

    feedback = AdvisoryFeedback(
        feedback_id=str(uuid.uuid4()),
        advisory_id=advisory_id,
        farmer_id=farmer.farmer_id,
        reply_code=reply_map[feedback_score],
        raw_reply_text=str(feedback_score),
        # Prediction snapshot for post-hoc evaluation (sec 12.1)
        predicted_class=predicted_class,
        predicted_confidence=predicted_confidence,
        predicted_soil_moisture=predicted_soil_moisture,
        model_version=model_version,
    )
    db.add(feedback)
    db.commit()

    return {
        "feedback_id": feedback.feedback_id,
        "advisory_id": advisory_id,
        "score": feedback_score,
        "reply_code": reply_map[feedback_score],
        "model_version": model_version,
        "predicted_class_snapshot": predicted_class,
        "message": "Feedback recorded successfully",
    }
