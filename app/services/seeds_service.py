from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentSourceItem, SourceType
from app.schemas.seeds import SeedImportError, SeedItemIn


@dataclass
class SeedImportStat:
    inserted: int
    updated: int
    errors: list[SeedImportError]


def _upsert_seed(db: Session, item: SeedItemIn) -> str:
    existing = (
        db.execute(
            select(ContentSourceItem).where(
                ContentSourceItem.topic == item.topic,
                ContentSourceItem.source_url == item.source_url,
            )
        )
        .scalars()
        .first()
    )

    if existing:
        existing.category = item.category
        existing.source_type = item.source_type
        existing.priority = item.priority
        existing.active = item.active
        return "updated"

    db.add(
        ContentSourceItem(
            topic=item.topic,
            category=item.category,
            source_url=item.source_url,
            source_type=item.source_type,
            priority=item.priority,
            active=item.active,
        )
    )
    return "inserted"


def import_seed_items(db: Session, items: list[SeedItemIn]) -> SeedImportStat:
    stat = SeedImportStat(inserted=0, updated=0, errors=[])

    for idx, item in enumerate(items, start=1):
        try:
            result = _upsert_seed(db, item)
            if result == "inserted":
                stat.inserted += 1
            else:
                stat.updated += 1
        except Exception as exc:  # noqa: BLE001
            stat.errors.append(SeedImportError(line=idx, reason=str(exc)))

    db.commit()
    return stat


def parse_seed_csv(content: bytes) -> list[SeedItemIn]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    required = {"topic", "category", "source_url", "source_type"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV 헤더는 topic,category,source_url,source_type 를 포함해야 합니다.")

    items: list[SeedItemIn] = []
    for row in reader:
        source_type = SourceType(row["source_type"].strip())
        priority = int(row.get("priority", 50) or 50)
        active_raw = str(row.get("active", "true")).strip().lower()
        active = active_raw in {"true", "1", "y", "yes"}

        items.append(
            SeedItemIn(
                topic=row["topic"].strip(),
                category=row["category"].strip(),
                source_url=row["source_url"].strip(),
                source_type=source_type,
                priority=priority,
                active=active,
            )
        )
    return items
