from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ContentSourceItem, SourceType, TrendKeywordSnapshot
from app.services.external_http import request_json


@dataclass
class TrendKeywordResult:
    keyword: str
    group_name: str
    ratio: float
    delta_ratio: float
    rank: int
    source_url: str


def _today_utc_date() -> date:
    return datetime.now(timezone.utc).date()


def _build_keyword_groups(raw_keywords: str) -> list[dict]:
    keywords = [item.strip() for item in raw_keywords.split(",") if item.strip()]
    groups = []
    for keyword in keywords[:20]:
        groups.append({"groupName": keyword, "keywords": [keyword]})
    return groups


def _extract_latest_ratios(data: dict) -> list[TrendKeywordResult]:
    rows: list[TrendKeywordResult] = []
    results = data.get("results", [])
    for item in results:
        group_name = str(item.get("title") or item.get("groupName") or "").strip()
        keyword = group_name
        points = item.get("data", []) if isinstance(item.get("data"), list) else []
        if not points:
            continue
        latest = float(points[-1].get("ratio", 0) or 0)
        prev = float(points[-2].get("ratio", latest) or latest) if len(points) >= 2 else latest
        delta = latest - prev
        source_url = f"https://www.coupang.com/np/search?q={quote_plus(keyword)}"
        rows.append(
            TrendKeywordResult(
                keyword=keyword,
                group_name=group_name or keyword,
                ratio=latest,
                delta_ratio=delta,
                rank=0,
                source_url=source_url,
            )
        )

    rows.sort(key=lambda x: (x.ratio + (x.delta_ratio * 0.7)), reverse=True)
    for i, row in enumerate(rows, start=1):
        row.rank = i
    return rows


def _fetch_naver_trends() -> list[TrendKeywordResult]:
    settings = get_settings()
    groups = _build_keyword_groups(settings.naver_trend_keywords)
    if not groups:
        return []

    if not settings.naver_client_id or not settings.naver_client_secret:
        raise ValueError("Naver 트렌드 API 키가 설정되지 않았습니다.")

    today = _today_utc_date()
    start = today - timedelta(days=7)
    payload = {
        "startDate": start.isoformat(),
        "endDate": today.isoformat(),
        "timeUnit": "date",
        "keywordGroups": groups,
    }

    data = request_json(
        "POST",
        "https://openapi.naver.com/v1/datalab/search",
        headers={
            "X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret,
            "Content-Type": "application/json",
        },
        json_body=payload,
        timeout=20.0,
    )
    return _extract_latest_ratios(data)


def _upsert_seed_from_keyword(db: Session, keyword: str, source_url: str, priority: int) -> None:
    topic = f"{keyword} 트렌드 가이드"
    existing = (
        db.execute(
            select(ContentSourceItem).where(
                ContentSourceItem.topic == topic,
                ContentSourceItem.source_url == source_url,
            )
        )
        .scalars()
        .first()
    )
    if existing:
        existing.priority = max(existing.priority, priority)
        existing.active = True
        existing.category = "트렌드"
        return

    db.add(
        ContentSourceItem(
            topic=topic,
            category="트렌드",
            source_url=source_url,
            source_type=SourceType.SEARCH_URL,
            priority=priority,
            active=True,
        )
    )


def sync_naver_trend_keywords(db: Session, target_date: date | None = None) -> dict:
    settings = get_settings()
    if not settings.naver_trend_enabled:
        return {"status": "SKIPPED_DISABLED", "imported": 0}

    biz_date = target_date or _today_utc_date()
    rows = _fetch_naver_trends()
    top_n = max(1, min(settings.naver_trend_top_n, len(rows)))
    selected = rows[:top_n]

    db.execute(
        delete(TrendKeywordSnapshot).where(
            TrendKeywordSnapshot.biz_date == biz_date,
            TrendKeywordSnapshot.provider == "NAVER",
        )
    )

    imported = 0
    for row in selected:
        db.add(
            TrendKeywordSnapshot(
                biz_date=biz_date,
                provider="NAVER",
                keyword=row.keyword,
                group_name=row.group_name,
                ratio=row.ratio,
                delta_ratio=row.delta_ratio,
                rank=row.rank,
                source_url=row.source_url,
            )
        )

        seed_priority = max(50, 100 - (row.rank - 1) * 5)
        _upsert_seed_from_keyword(db, row.keyword, row.source_url, priority=seed_priority)
        imported += 1

    db.commit()
    return {
        "status": "SUCCESS",
        "biz_date": biz_date.isoformat(),
        "imported": imported,
        "top_keywords": [row.keyword for row in selected],
    }
