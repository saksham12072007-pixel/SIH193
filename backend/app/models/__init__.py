from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.utils.time import utc_now


class Farmer(Base):
    __tablename__ = "farmers"

    farmer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, default="hi")
    state: Mapped[str | None] = mapped_column(String(60), nullable=True)
    district: Mapped[str | None] = mapped_column(String(60), nullable=True)
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    registration_channel: Mapped[str] = mapped_column(String(20), default="sms")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")

    plots: Mapped[list["Plot"]] = relationship(back_populates="farmer")
    advisory_feedback: Mapped[list["AdvisoryFeedback"]] = relationship(back_populates="farmer")
    sms_logs: Mapped[list["SmsLog"]] = relationship(back_populates="farmer")


class Plot(Base):
    __tablename__ = "plots"

    plot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmers.farmer_id"), nullable=False)
    plot_nickname: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_precision: Mapped[str] = mapped_column(String(40), default="gps")
    village_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    buffer_polygon: Mapped[str | None] = mapped_column(String(255), nullable=True)
    crop_type: Mapped[str] = mapped_column(String(60), nullable=False)
    plot_size_declared: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    sowing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    # sec 12.1: soil context features for Stage 1 regression (sandy soils dry faster than clay)
    soil_texture: Mapped[str | None] = mapped_column(String(30), nullable=True)
    soil_awc: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)  # available water capacity
    irrigation_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ingestion_failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data_status: Mapped[str] = mapped_column(String(30), default="available", nullable=False)
    last_ingestion_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    farmer: Mapped[Farmer] = relationship(back_populates="plots")
    satellite_data: Mapped[list["SatelliteData"]] = relationship(back_populates="plot")
    ml_predictions: Mapped[list["MlPrediction"]] = relationship(back_populates="plot")
    advisories: Mapped[list["Advisory"]] = relationship(back_populates="plot")
    plot_features: Mapped[list["PlotFeatures"]] = relationship(back_populates="plot")


class SatelliteData(Base):
    __tablename__ = "satellite_data"

    # e.g. "weather-<uuid>-<index>" -- longer than a bare UUID.
    satellite_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.plot_id"), nullable=False)
    data_source: Mapped[str] = mapped_column(String(30), nullable=False)
    data_type: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    quality_flag: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cloud_coverage: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    cloud_masked: Mapped[bool] = mapped_column(Boolean, default=False)
    ingestion_status: Mapped[str] = mapped_column(String(30), default="success")

    plot: Mapped[Plot] = relationship(back_populates="satellite_data")


class PlotFeatures(Base):
    """
    sec 12.1 -- Canonical per-plot-per-date feature row.

    Every row is assembled using the "nearest valid observation per source" join
    logic (11_Complete_Architecture.md sec 11.4):
      - Sentinel-1: nearest pass within +-3 days
      - Sentinel-2: nearest cloud-free pass within +-5 days
      - Weather: exact date (1/3/7/14-day windows ending on obs_date)

    SMAP: smap_sm is a context input feature ONLY.
    The ingestion pipeline must NEVER write SMAP values into soil_moisture_label
    when SMAP is also used as an input feature -- this causes circular evaluation
    leakage (model learns to reproduce SMAP rather than predict independently).
    """

    __tablename__ = "plot_features"

    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.plot_id"), primary_key=True)
    obs_date: Mapped[date] = mapped_column(Date, primary_key=True)

    # Sentinel-1 SAR features (primary soil-moisture signal -- cloud-proof)
    vv_db: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    vh_db: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    delta_vv_7d: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    delta_vh_7d: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Sentinel-2 optical features (vegetation-stress signal, NOT soil moisture directly)
    ndvi: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    ndwi: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    evi: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    savi: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    delta_ndvi_7d: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    delta_ndvi_14d: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # Weather features
    rainfall_1d: Mapped[float | None] = mapped_column(Numeric(7, 2), nullable=True)
    rainfall_3d: Mapped[float | None] = mapped_column(Numeric(7, 2), nullable=True)
    rainfall_7d: Mapped[float | None] = mapped_column(Numeric(7, 2), nullable=True)
    rainfall_14d: Mapped[float | None] = mapped_column(Numeric(7, 2), nullable=True)
    rain_forecast_48h: Mapped[float | None] = mapped_column(Numeric(7, 2), nullable=True)
    et0: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)  # Penman-Monteith
    kc: Mapped[float | None] = mapped_column(Numeric(5, 3), nullable=True)   # crop coefficient
    etc: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)  # ETc = ET0 * Kc
    lst: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)  # Land Surface Temp

    # SMAP -- regional calibration prior ONLY (NEVER the training label, per sec 12.3.2)
    smap_sm: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # Crop/context features
    crop_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Ground-truth label -- nullable until assigned
    # Hierarchy (best to weakest): ISMN/field probes > water-balance bucket model > farmer_feedback
    # 'smap' only allowed as label_source when SMAP is NOT used as input feature in that model run
    label_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    soil_moisture_label: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    plot: Mapped[Plot] = relationship(back_populates="plot_features")


class MlPrediction(Base):
    __tablename__ = "ml_predictions"

    prediction_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.plot_id"), nullable=False)
    model_version: Mapped[str] = mapped_column(String(30), nullable=False)
    stage1_soil_moisture_estimate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    stage1_cwsi_estimate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    advisory_class: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    input_feature_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    predicted_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    plot: Mapped[Plot] = relationship(back_populates="ml_predictions")
    advisory: Mapped["Advisory"] = relationship(back_populates="prediction")


class ModelEvaluationRun(Base):
    """
    sec 12.1 / sec 13.5 -- Per-model-version evaluation metrics.

    Promotion gate (sec 13.5):
      1. FPR (Stage 2) must be below agreed threshold -> passed_fpr_threshold must be True.
      2. Among passing models: best RMSE/R2 for Stage 1, best Recall on 'Irrigate Now' for Stage 2.
      3. If passed_fpr_threshold is False, promotion is blocked; notes must document the reason.

    Every retrain cycle writes one row here before the model can be deployed to production.
    """

    __tablename__ = "model_evaluation_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agro_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Stage 1 regression metrics (literature target RMSE: ~0.05-0.09 m3/m3)
    rmse: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    mae: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    r2: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    # Stage 2 classification metrics
    accuracy: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    precision_score: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    recall: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)  # weighted higher for Irrigate Now
    f1: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    fpr: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)   # FP/(FP+TN) -- hard constraint
    passed_fpr_threshold: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # SHAP feature importance snapshot (sec 12.4.4 -- for explainability and SIH judge Q&A)
    shap_feature_importance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class SmsTemplate(Base):
    __tablename__ = "sms_templates"

    # Composite id of crop_code-reason_code-language_code (up to 60+50+10 chars
    # plus separators), not a UUID -- 36 was too narrow for real seed data.
    template_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    crop_code: Mapped[str] = mapped_column(String(60), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    language_code: Mapped[str] = mapped_column(String(10), nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("crop_code", "reason_code", "language_code", name="uq_sms_template_lookup"),
    )


class Advisory(Base):
    __tablename__ = "advisories"

    advisory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.plot_id"), nullable=False)
    prediction_id: Mapped[str] = mapped_column(ForeignKey("ml_predictions.prediction_id"), nullable=False)
    advisory_class: Mapped[str] = mapped_column(String(30), nullable=False)
    # Matches sms_templates.template_id's width (String(128), also a
    # composite id rather than a UUID).
    template_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_used: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sms_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    ivr_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    plot: Mapped[Plot] = relationship(back_populates="advisories")
    prediction: Mapped[MlPrediction] = relationship(back_populates="advisory")
    sms_logs: Mapped[list["SmsLog"]] = relationship(back_populates="advisory")
    feedback: Mapped[list["AdvisoryFeedback"]] = relationship(back_populates="advisory")


class Alert(Base):
    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    advisory_id: Mapped[str] = mapped_column(ForeignKey("advisories.advisory_id"), unique=True, nullable=False)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.plot_id"), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_metric: Mapped[str | None] = mapped_column(String(60), nullable=True)
    trigger_value: Mapped[str | None] = mapped_column(String(60), nullable=True)
    threshold: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="GENERATED", nullable=False)
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("institutional_users.user_id"), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    advisory: Mapped[Advisory] = relationship()
    plot: Mapped[Plot] = relationship()


class SmsLog(Base):
    __tablename__ = "sms_logs"

    sms_log_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    advisory_id: Mapped[str | None] = mapped_column(ForeignKey("advisories.advisory_id"), nullable=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmers.farmer_id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="outbound")
    message_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    gateway_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), default="queued")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    advisory: Mapped[Advisory | None] = relationship(back_populates="sms_logs")
    farmer: Mapped[Farmer] = relationship(back_populates="sms_logs")


class AdvisoryFeedback(Base):
    __tablename__ = "advisory_feedback"

    feedback_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    advisory_id: Mapped[str] = mapped_column(ForeignKey("advisories.advisory_id"), nullable=False)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmers.farmer_id"), nullable=False)
    reply_code: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_reply_text: Mapped[str | None] = mapped_column(String(160), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    used_in_retraining_batch: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # sec 12.1: prediction-snapshot for post-hoc Precision/Recall/FPR/RMSE evaluation
    predicted_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    predicted_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    predicted_soil_moisture: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    advisory: Mapped[Advisory] = relationship(back_populates="feedback")
    farmer: Mapped[Farmer] = relationship(back_populates="advisory_feedback")


class SmsConversationSession(Base):
    __tablename__ = "sms_conversation_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    farmer_id: Mapped[str | None] = mapped_column(ForeignKey("farmers.farmer_id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="sms")
    current_state: Mapped[str] = mapped_column(String(40), default="idle")
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    farmer: Mapped[Farmer | None] = relationship()


class SupportedLanguage(Base):
    __tablename__ = "supported_languages"

    language_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    script_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    rule_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    operator: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    district: Mapped[str | None] = mapped_column(String(60), nullable=True)
    crop: Mapped[str | None] = mapped_column(String(60), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("institutional_users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class FieldInspection(Base):
    __tablename__ = "field_inspections"

    inspection_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.plot_id"), nullable=False)
    officer_user_id: Mapped[str] = mapped_column(ForeignKey("institutional_users.user_id"), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(60), nullable=False)
    observed_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    farmer_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    officer_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    # Photo *upload* storage is not implemented (no object-storage integration exists
    # in this backend yet); this holds externally-hosted URLs only, if ever supplied.
    photos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    inspection_date: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    plot: Mapped[Plot] = relationship()


class InstitutionalUser(Base):
    __tablename__ = "institutional_users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(30), default="viewer")
    assigned_geography: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = [
    "Farmer",
    "Plot",
    "SatelliteData",
    "PlotFeatures",
    "MlPrediction",
    "ModelEvaluationRun",
    "SmsTemplate",
    "Advisory",
    "SmsLog",
    "AdvisoryFeedback",
    "Alert",
    "AlertRule",
    "FieldInspection",
    "SmsConversationSession",
    "SupportedLanguage",
    "InstitutionalUser",
    "Base",
]
