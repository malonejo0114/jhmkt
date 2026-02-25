from pydantic import BaseModel, Field

from app.models.schema import SourceType


class SeedItemIn(BaseModel):
    topic: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    source_url: str = Field(min_length=8, max_length=2000)
    source_type: SourceType
    priority: int = Field(default=50, ge=1, le=100)
    active: bool = True


class SeedImportJsonBody(BaseModel):
    items: list[SeedItemIn]


class SeedImportError(BaseModel):
    line: int
    reason: str


class SeedImportResponse(BaseModel):
    inserted: int
    updated: int
    errors: list[SeedImportError]
