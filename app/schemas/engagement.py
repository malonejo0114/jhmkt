from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import BrandVertical, CommentActionType, CommentTriggerType


class BrandProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    vertical_type: BrandVertical
    comment_style_prompt: str = Field(default="", max_length=2000)


class BrandProfileOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    vertical_type: BrandVertical
    comment_style_prompt: str
    active: bool


class AssignBrandProfileRequest(BaseModel):
    brand_profile_id: UUID


class CommentRuleCreateRequest(BaseModel):
    instagram_account_id: UUID
    brand_profile_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    trigger_type: CommentTriggerType
    trigger_value: str = Field(min_length=1, max_length=120)
    action_type: CommentActionType
    ai_style_prompt: str = Field(default="", max_length=2000)
    message_template: str = Field(min_length=1, max_length=2000)
    priority: int = Field(default=100, ge=1, le=9999)
    cooldown_minutes: int = Field(default=60, ge=0, le=1440)
    active: bool = True


class CommentRuleUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    trigger_type: CommentTriggerType
    trigger_value: str = Field(min_length=1, max_length=120)
    action_type: CommentActionType
    ai_style_prompt: str = Field(default="", max_length=2000)
    message_template: str = Field(min_length=1, max_length=2000)
    priority: int = Field(default=100, ge=1, le=9999)
    cooldown_minutes: int = Field(default=60, ge=0, le=1440)
    active: bool = True
    brand_profile_id: UUID | None = None


class CommentRuleToggleRequest(BaseModel):
    active: bool


class CommentRuleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    instagram_account_id: UUID
    brand_profile_id: UUID | None
    name: str
    trigger_type: CommentTriggerType
    trigger_value: str
    action_type: CommentActionType
    ai_style_prompt: str
    message_template: str
    priority: int
    cooldown_minutes: int
    active: bool


class CommentEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    instagram_account_id: UUID
    external_comment_id: str
    comment_text: str
    status: str
    status_reason: str | None
    created_at: datetime


class ReplyJobOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    comment_event_id: UUID
    instagram_account_id: UUID
    action_type: CommentActionType
    status: str
    skip_reason: str | None
    attempts: int
    max_attempts: int
    next_retry_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    sent_at: datetime | None
    created_at: datetime


class ThreadsCommentEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    threads_account_id: UUID
    external_reply_id: str
    external_media_id: str | None
    external_from_username: str | None
    reply_text: str
    status: str
    status_reason: str | None
    created_at: datetime


class ThreadsReplyJobOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    comment_event_id: UUID
    threads_account_id: UUID
    status: str
    reply_text: str
    skip_reason: str | None
    attempts: int
    max_attempts: int
    next_retry_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    sent_at: datetime | None
    created_at: datetime
