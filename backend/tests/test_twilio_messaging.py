import httpx

from app.core.config import get_settings
from app.services.messaging_service import TwilioMessagingProvider


def test_twilio_sms_adapter_posts_form_data(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret")
    monkeypatch.setattr(settings, "twilio_sms_from", "+15005550006")
    monkeypatch.setattr(settings, "twilio_status_callback_url", "https://example.test/sms/webhook/delivery")

    def send(url, **kwargs):
        assert url.endswith("/Accounts/AC123/Messages.json")
        assert kwargs["auth"] == ("AC123", "secret")
        assert kwargs["data"]["To"] == "+919999999999"
        return httpx.Response(201, json={"sid": "SM123"})

    monkeypatch.setattr(httpx, "post", send)
    result = TwilioMessagingProvider().send_sms("+919999999999", "Irrigate now")
    assert result == {"status": "queued", "gateway": "twilio", "message_id": "SM123"}
