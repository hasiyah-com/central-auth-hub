"""Calendar features use Bangkok; database timestamps remain naive UTC."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BANGKOK = ZoneInfo("Asia/Bangkok")
FEATURE_CONTRACT = "rba-23-bangkok-v1"


def as_utc_naive(value: datetime) -> datetime:
    """Naive values follow the database UTC contract, never server local time."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def as_bangkok(value: datetime) -> datetime:
    return as_utc_naive(value).replace(tzinfo=timezone.utc).astimezone(BANGKOK)
