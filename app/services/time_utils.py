from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def kst_today() -> date:
    return datetime.now(tz=KST).date()


def kst_day_window(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time(0, 0), tzinfo=KST)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def posting_window(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time(8, 0), tzinfo=KST)
    end_local = datetime.combine(day, time(23, 0), tzinfo=KST)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
