"""SMS template management and advisory message generation."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy.orm import Session

from app.models import Advisory, SmsLog, SmsTemplate
from app.services.messaging_service import MessagingService
from app.utils.time import utc_now


class SMSPriority(str, Enum):
    """Priority level for SMS delivery."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class AdvisoryMessage:
    """Advisory message to send to a farmer."""

    advisory_id: str
    farmer_id: str
    farmer_phone: str
    plot_id: str
    crop_type: str
    language: str
    advisory_class: str
    reason_code: str
    message_text: str
    priority: SMSPriority
    confidence: float
    template_id: str | None


class SMSTemplateService:
    """Manage SMS templates and generate advisory messages."""

    DEFAULT_TEMPLATES = (
        (
            "adequate_moisture",
            "no_action",
            "आपकी फसल में अभी कोई कार्रवाई नहीं चाहिए। नमी पर्याप्त है।",
            "Your crop has sufficient soil moisture. No action is needed right now.",
        ),
        (
            "recent_rainfall_adequate",
            "no_action",
            "हाल की बारिश पर्याप्त है। अभी कोई कार्रवाई नहीं चाहिए।",
            "Recent rainfall is sufficient. No action is needed right now.",
        ),
        (
            "stage_monitor",
            "monitor",
            "आपकी फसल पर नजर रखें। अगले कुछ दिनों में स्थिति बदल सकती है।",
            "Please monitor your crop. Conditions may change over the next few days.",
        ),
        (
            "declining_ndvi_trend",
            "irrigate_soon",
            "आपकी फसल में नमी घट रही है। अगले 2-3 दिन में सिंचाई की योजना बनाएं।",
            "Your crop shows a declining moisture trend. Plan irrigation in the next 2-3 days.",
        ),
        (
            "moderate_stress_detected",
            "irrigate_soon",
            "नमी कम हो रही है। अगले 2-3 दिन में सिंचाई की योजना बनाएं।",
            "Soil moisture is dropping. Plan irrigation in the next 2-3 days.",
        ),
        (
            "data_unavailable",
            "monitor",
            "इस चक्र में स्पष्ट उपग्रह डेटा नहीं मिला। हम अगली जाँच में फिर प्रयास करेंगे।",
            "No clear satellite data was available this cycle. We will check again next cycle.",
        ),
        (
            "low_soil_moisture",
            "irrigate_now",
            "आपकी फसल को तुरंत सिंचाई की जरूरत है। आज ही सिंचाई करें।",
            "Your crop needs immediate irrigation. Water it today.",
        ),
        (
            "safe_no_irrigation",
            "no_action",
            "सिंचाई की जरूरत नहीं है। मिट्टी में पर्याप्त नमी है।",
            "No irrigation is needed now. Soil moisture is sufficient.",
        ),
        (
            "monitor_and_prepare",
            "irrigate_soon",
            "मिट्टी की नमी कम हो रही है। अगले 2-3 दिन में सिंचाई की तैयारी करें।",
            "Soil moisture is declining. Prepare to irrigate in the next 2-3 days.",
        ),
        (
            "urgent_irrigation_needed",
            "irrigate_now",
            "फसल को तुरंत सिंचाई की जरूरत है। आज ही सिंचाई करें।",
            "Your crop needs urgent irrigation. Water it today.",
        ),
    )

    PRIORITY_BY_CLASS = {
        "no_action": SMSPriority.LOW,
        "monitor": SMSPriority.NORMAL,
        "irrigate_soon": SMSPriority.HIGH,
        "irrigate_now": SMSPriority.CRITICAL,
    }

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_templates(self) -> None:
        """Seed approved templates used by the advisory pipeline."""
        for reason_code, advisory_class, hi_text, en_text in self.DEFAULT_TEMPLATES:
            for language_code, template_text in (("hi", hi_text), ("en", en_text)):
                template_id = f"{reason_code}-{advisory_class}-{language_code}"
                existing = self._find_template_by_id(template_id)
                if existing:
                    continue

                self.db.add(
                    SmsTemplate(
                        template_id=template_id,
                        crop_code="all",
                        reason_code=reason_code,
                        language_code=language_code,
                        template_text=template_text,
                        review_status="approved",
                    )
                )

        self.db.commit()

    def generate_advisory_message(
        self,
        farmer_id: str,
        farmer_phone: str,
        plot_id: str,
        crop_type: str,
        language: str,
        advisory_class: str,
        reason_code: str,
        confidence: float,
    ) -> AdvisoryMessage | None:
        """Generate advisory SMS message from templates."""
        template = self._find_template(crop_type, reason_code, language)
        if not template and language != "en":
            template = self._find_template(crop_type, reason_code, "en")
        if not template:
            return None

        return AdvisoryMessage(
            advisory_id=str(uuid.uuid4()),
            farmer_id=farmer_id,
            farmer_phone=farmer_phone,
            plot_id=plot_id,
            crop_type=crop_type,
            language=template.language_code,
            advisory_class=advisory_class,
            reason_code=reason_code,
            message_text=template.template_text,
            priority=self.PRIORITY_BY_CLASS.get(advisory_class, SMSPriority.NORMAL),
            confidence=confidence,
            template_id=template.template_id,
        )

    def create_advisory_record(self, message: AdvisoryMessage, prediction_id: str, *, sms_sent: bool = True) -> Advisory:
        """Create advisory record in the database."""
        advisory = Advisory(
            advisory_id=message.advisory_id,
            plot_id=message.plot_id,
            prediction_id=prediction_id,
            advisory_class=message.advisory_class,
            template_id=message.template_id,
            language_used=message.language,
            sms_sent=sms_sent,
            ivr_triggered=False,
        )
        self.db.add(advisory)
        self.db.commit()
        self.db.refresh(advisory)
        return advisory

    def log_sms_send(
        self,
        advisory_id: str,
        farmer_id: str,
        farmer_phone: str,
        message_text: str,
        external_id: str | None = None,
    ) -> SmsLog:
        """Log SMS send attempt."""
        result = MessagingService(self.db).send_sms(farmer_phone, message_text)
        sms_log = SmsLog(
            sms_log_id=str(uuid.uuid4()),
            advisory_id=advisory_id,
            farmer_id=farmer_id,
            direction="outbound",
            message_body=message_text,
            gateway_message_id=external_id or result.get("message_id"),
            delivery_status=result.get("status", "queued"),
            retry_count=0,
            sent_at=utc_now(),
        )
        self.db.add(sms_log)
        self.db.commit()
        self.db.refresh(sms_log)
        return sms_log

    def _find_template(self, crop_type: str, reason_code: str, language_code: str) -> SmsTemplate | None:
        """Find an approved template for a crop, with a generic fallback."""
        for crop_code in (crop_type, "all"):
            template = (
                self.db.query(SmsTemplate)
                .filter(
                    SmsTemplate.crop_code == crop_code,
                    SmsTemplate.reason_code == reason_code,
                    SmsTemplate.language_code == language_code,
                    SmsTemplate.review_status == "approved",
                )
                .first()
            )
            if template:
                return template
        return None

    def _find_template_by_id(self, template_id: str) -> SmsTemplate | None:
        return self.db.query(SmsTemplate).filter(SmsTemplate.template_id == template_id).first()
