"""Local calendar days converted to half-open UTC intervals."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def day_range(day: date, tz: ZoneInfo | str) -> tuple[datetime, datetime]:
    if isinstance(day, datetime) or not isinstance(day, date):
        raise ValueError("day 必须是 date。")
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
