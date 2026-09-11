from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Crop Advisory Backend"
    app_env: str = "development"
    app_debug: bool = True
    database_url: str = "sqlite:///./crop_advisory.db"
    secret_key: str = "change-me-in-production-at-least-32-chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    sms_provider: str = "mock"
    sms_sender_id: str = "TESTSMS"
    ivr_provider: str = "mock"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_sms_from: str | None = None
    twilio_whatsapp_from: str | None = None
    twilio_voice_from: str | None = None
    twilio_status_callback_url: str | None = None
    ingestion_provider: str = "mock"
    gee_project_id: str | None = None
    google_application_credentials: str | None = None
    gee_service_account: str | None = None
    ingestion_lookback_days: int = 30
    data_unavailable_after_failures: int = 2
    ml_api_enabled: bool = True
    ml_api_url: str = "https://nir-api.onrender.com"
    ml_api_key: str | None = None
    ml_api_timeout_seconds: float = 10.0
    ml_api_model_version: str | None = None
    model_artifacts_dir: str = "./ml_artifacts"
    enable_scheduler: bool = False
    scheduler_interval_minutes: int = 60
    frontend_allowed_origins: str = (
        "http://localhost:5050,http://127.0.0.1:5050,"
        "http://localhost:5500,http://127.0.0.1:5500,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    @model_validator(mode="after")
    def validate_deployment_settings(self) -> "Settings":
        if self.app_env.lower() in {"production", "prod", "staging"}:
            if self.secret_key.startswith("change-me") or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be a random value of at least 32 characters outside development")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside development")
            if self.sms_provider.lower() == "twilio":
                required = {
                    "TWILIO_ACCOUNT_SID": self.twilio_account_sid,
                    "TWILIO_AUTH_TOKEN": self.twilio_auth_token,
                    "TWILIO_SMS_FROM": self.twilio_sms_from,
                    "TWILIO_STATUS_CALLBACK_URL": self.twilio_status_callback_url,
                }
                missing = [name for name, value in required.items() if not value]
                if missing:
                    raise ValueError(f"Missing Twilio production settings: {', '.join(missing)}")
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()
