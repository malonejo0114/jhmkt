from datetime import date

from pydantic import BaseModel


class DailyDashboardRow(BaseModel):
    biz_date: date
    content_units: int
    jobs_success: int
    jobs_failed: int
    jobs_pending: int
    threads_views: int
    threads_likes: int
    threads_replies: int


class DashboardResponse(BaseModel):
    last_7_days: list[DailyDashboardRow]
    totals: dict[str, int]
