from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.schema import AccountStatus, BrandVertical


class ThreadsAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    threads_user_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=10)
    token_expires_at: datetime | None = None
    brand_vertical: BrandVertical | None = None


class InstagramAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    ig_user_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=10)
    token_expires_at: datetime | None = None
    brand_vertical: BrandVertical | None = None


class AccountOut(BaseModel):
    id: UUID
    name: str
    external_user_id: str
    status: AccountStatus


class AccountCreateResponse(BaseModel):
    account: AccountOut
