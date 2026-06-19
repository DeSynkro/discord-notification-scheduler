import re
from uuid import uuid4
from pydantic import BaseModel, field_validator, Field
from typing import Optional
from zoneinfo import available_timezones

TIMEZONE_SET = available_timezones()

DAYS_OF_WEEK = [
    "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday"
]

TIMEZONES = sorted(TIMEZONE_SET)

WEBHOOK_PATTERN = re.compile(
    r"^https://discord\.com/api/webhooks/(\d{17,19})/([A-Za-z0-9_\-]+)$"
)

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class EmbedConfig(BaseModel):
    title: Optional[str] = None
    color: Optional[str] = None  # hex color like #FF0000

    @field_validator("color")
    @classmethod
    def check_color(cls, v):
        if v is None:
            return v
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("Color must be a hex value like #FF0000")
        return v.upper()


class Webhook(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str

    @field_validator("url")
    @classmethod
    def check_url(cls, v):
        if not WEBHOOK_PATTERN.match(v):
            raise ValueError(
                "Must be a Discord webhook URL like "
                "https://discord.com/api/webhooks/123456/abc-xyz"
            )
        return v


class Alarm(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(..., min_length=1, max_length=100)
    webhook_name: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=2000)
    message_type: str = "text"  # "text" or "embed"
    embed: Optional[EmbedConfig] = None
    time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    days: list[str] = Field(default_factory=lambda: list(DAYS_OF_WEEK))
    timezone: str = "UTC"
    enabled: bool = True
    last_fired: Optional[str] = None  # ISO timestamp of last successful send
    last_error: Optional[str] = None  # error message from last attempt

    @field_validator("days")
    @classmethod
    def check_days(cls, v):
        if not v:
            return list(DAYS_OF_WEEK)
        for day in v:
            if day not in DAYS_OF_WEEK:
                raise ValueError(f"'{day}' is not a valid day name")
        return v

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, v):
        if v not in TIMEZONE_SET:
            raise ValueError(f"'{v}' is not a valid timezone")
        return v

    @field_validator("message_type")
    @classmethod
    def check_type(cls, v):
        if v not in ("text", "embed"):
            raise ValueError("message_type must be 'text' or 'embed'")
        return v
