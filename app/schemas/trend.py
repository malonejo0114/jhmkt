from datetime import date

from pydantic import BaseModel


class TrendSyncRequest(BaseModel):
    biz_date: date | None = None


class TrendSyncResponse(BaseModel):
    status: str
    biz_date: str | None = None
    imported: int | None = None
    top_keywords: list[str] | None = None
    reason: str | None = None
