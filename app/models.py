import re
from uuid import uuid4
from datetime import date as dt_date, datetime, timezone
from pydantic import BaseModel, field_validator, Field
from typing import Literal, Optional
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

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        if any(ch in v for ch in "/?#%"):
            raise ValueError("Webhook name cannot contain / ? # %")
        return v

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
    id: str = Field(
        default_factory=lambda: uuid4().hex[:12],
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    name: str = Field(..., min_length=1, max_length=100)
    webhook_name: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=2000)
    message_type: str = "text"  # "text" or "embed"
    embed: Optional[EmbedConfig] = None
    time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    days: list[str] = Field(default_factory=lambda: list(DAYS_OF_WEEK))
    timezone: str = "UTC"
    enabled: bool = True
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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


CALENDAR_REPEATS = ("none", "daily", "weekly", "monthly", "yearly")


class CalendarAlert(BaseModel):
    id: str = Field(
        default_factory=lambda: uuid4().hex[:12],
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    name: str = Field(..., min_length=1, max_length=100)
    webhook_name: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=2000)
    message_type: str = "text"
    embed: Optional[EmbedConfig] = None
    color: str = "#3FB950"
    date: str
    time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    timezone: str = "UTC"
    repeat: str = "none"
    enabled: bool = True
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    next_fire: Optional[str] = None
    last_fired: Optional[str] = None
    last_error: Optional[str] = None

    @field_validator("date")
    @classmethod
    def check_date(cls, v):
        if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("Date must be YYYY-MM-DD")
        try:
            parsed = datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Date must be a real calendar date")
        if parsed < dt_date(1900, 1, 1) or parsed > dt_date(2200, 12, 31):
            raise ValueError("Date must be between 1900-01-01 and 2200-12-31")
        return v

    @field_validator("repeat")
    @classmethod
    def check_repeat(cls, v):
        if v not in CALENDAR_REPEATS:
            raise ValueError("repeat must be one of: " + ", ".join(CALENDAR_REPEATS))
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

    @field_validator("color")
    @classmethod
    def check_color(cls, v):
        if not isinstance(v, str) or not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("Color must be a hex value like #3FB950")
        return v.upper()


class LogEntry(BaseModel):
    ts: str
    kind: Literal["weekly", "calendar", "test"]
    source_id: Optional[str] = None
    name: str
    webhook_name: str
    timezone: str = "UTC"
    status: Literal["ok", "err"]
    error: Optional[str] = None
    preview: str
