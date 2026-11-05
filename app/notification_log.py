from datetime import datetime, timezone

from app.models import LogEntry
from app.storage import read_json, write_json

MAX_LOG = 500


def preview(message: str) -> str:
    return " ".join(message.split())[:200]


def append_log(
    kind: str,
    item,
    source_id: str | None,
    success: bool,
    error: str,
) -> None:
    entry = LogEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        kind=kind,
        source_id=source_id,
        name=item.name,
        webhook_name=item.webhook_name,
        timezone=getattr(item, "timezone", "UTC") or "UTC",
        status="ok" if success else "err",
        error=None if success else (error or "Unknown error"),
        preview=preview(item.message),
    )
    rows = read_json("log")
    rows.insert(0, entry.model_dump())
    write_json("log", rows[:MAX_LOG])


def read_log(limit: int | None = None) -> list[dict]:
    rows = read_json("log")
    return rows if limit is None else rows[:limit]


def clear_log() -> None:
    write_json("log", [])
