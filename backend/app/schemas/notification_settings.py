from pydantic import BaseModel, Field, model_validator


class EmailRecipient(BaseModel):
    name: str = Field(default="", max_length=128)
    address: str = Field(default="", max_length=320)


class EmailNotificationSettingsRead(BaseModel):
    email_enabled: bool
    offline_alert_seconds: float
    recovery_stable_seconds: float
    notify_recovery: bool
    smtp_sender_name: str
    smtp_host: str
    smtp_port: int
    smtp_auth_enabled: bool
    smtp_username: str
    smtp_password_set: bool
    smtp_from: str
    smtp_to: str
    recipients: list[EmailRecipient]
    smtp_use_ssl: bool
    smtp_starttls: bool
    smtp_timeout_seconds: float
    email_attach_images: bool
    email_capture_interval_seconds: int
    configured: bool


class EmailNotificationSettingsUpdate(BaseModel):
    email_enabled: bool
    offline_alert_seconds: float = Field(ge=0, le=86400)
    recovery_stable_seconds: float = Field(ge=0, le=3600)
    notify_recovery: bool
    smtp_sender_name: str = Field(default="", max_length=128)
    smtp_host: str = ""
    smtp_port: int = Field(ge=1, le=65535)
    smtp_auth_enabled: bool = True
    smtp_username: str = ""
    smtp_password: str | None = None
    clear_smtp_password: bool = False
    smtp_from: str = ""
    smtp_to: str = ""
    recipients: list[EmailRecipient] = Field(default_factory=list, max_length=16)
    smtp_use_ssl: bool = False
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = Field(ge=1, le=120)
    email_attach_images: bool = False
    email_capture_interval_seconds: int = Field(default=2, ge=1, le=60)

    @model_validator(mode="after")
    def validate_tls_modes(self):
        if self.smtp_use_ssl and self.smtp_starttls:
            raise ValueError("SMTP SSL and STARTTLS cannot both be enabled")
        return self
