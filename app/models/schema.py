import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AccountStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ChannelType(str, enum.Enum):
    THREADS = "THREADS"
    INSTAGRAM = "INSTAGRAM"


class JobType(str, enum.Enum):
    THREADS_ROOT = "THREADS_ROOT"
    THREADS_REPLY = "THREADS_REPLY"
    INSTAGRAM_CAROUSEL = "INSTAGRAM_CAROUSEL"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ContentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    FAILED = "FAILED"
    PUBLISHED_PARTIAL = "PUBLISHED_PARTIAL"
    PUBLISHED_ALL = "PUBLISHED_ALL"


class SourceType(str, enum.Enum):
    PRODUCT_URL = "PRODUCT_URL"
    SEARCH_URL = "SEARCH_URL"


class ImproveRunType(str, enum.Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BrandVertical(str, enum.Enum):
    COUPANG = "COUPANG"
    SAJU = "SAJU"


class CommentTriggerType(str, enum.Enum):
    KEYWORD = "KEYWORD"
    REGEX = "REGEX"


class CommentActionType(str, enum.Enum):
    PRIVATE_REPLY = "PRIVATE_REPLY"
    PUBLIC_REPLY = "PUBLIC_REPLY"


class CommentEventStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class ReplyJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SENT = "SENT"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class QuotaBucketType(str, enum.Enum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AppUser(Base, TimestampMixin):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class BrandProfile(Base, TimestampMixin):
    __tablename__ = "brand_profile"
    __table_args__ = (UniqueConstraint("name", name="uq_brand_profile_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    vertical_type: Mapped[BrandVertical] = mapped_column(
        Enum(BrandVertical, name="brand_vertical"), nullable=False
    )
    comment_style_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ThreadsAccount(Base, TimestampMixin):
    __tablename__ = "threads_account"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("brand_profile.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    threads_user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, name="account_status"), nullable=False, default=AccountStatus.ACTIVE
    )


class InstagramAccount(Base, TimestampMixin):
    __tablename__ = "instagram_account"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("brand_profile.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    ig_user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, name="account_status"), nullable=False, default=AccountStatus.ACTIVE
    )


class CommentRule(Base, TimestampMixin):
    __tablename__ = "comment_rule"
    __table_args__ = (
        UniqueConstraint(
            "instagram_account_id",
            "trigger_type",
            "trigger_value",
            "action_type",
            name="uq_comment_rule_account_trigger_action",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instagram_account.id"), nullable=False
    )
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("brand_profile.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_type: Mapped[CommentTriggerType] = mapped_column(
        Enum(CommentTriggerType, name="comment_trigger_type"), nullable=False
    )
    trigger_value: Mapped[str] = mapped_column(String(120), nullable=False)
    action_type: Mapped[CommentActionType] = mapped_column(
        Enum(CommentActionType, name="comment_action_type"), nullable=False
    )
    ai_style_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message_template: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CommentEvent(Base, TimestampMixin):
    __tablename__ = "comment_event"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_comment_event_hash"),
        UniqueConstraint("instagram_account_id", "external_comment_id", name="uq_comment_event_comment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instagram_account.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="META")
    field: Mapped[str] = mapped_column(String(40), nullable=False)
    external_entry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_comment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_media_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_from_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_from_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    comment_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CommentEventStatus] = mapped_column(
        Enum(CommentEventStatus, name="comment_event_status"), nullable=False, default=CommentEventStatus.PENDING
    )
    status_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ReplyJob(Base, TimestampMixin):
    __tablename__ = "reply_job"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_reply_job_idempotency"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    comment_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("comment_event.id"), nullable=False)
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instagram_account.id"), nullable=False
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comment_rule.id"), nullable=True)
    action_type: Mapped[CommentActionType] = mapped_column(
        Enum(CommentActionType, name="comment_action_type"), nullable=False
    )
    reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReplyJobStatus] = mapped_column(
        Enum(ReplyJobStatus, name="reply_job_status"), nullable=False, default=ReplyJobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ThreadsCommentEvent(Base, TimestampMixin):
    __tablename__ = "threads_comment_event"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_threads_comment_event_hash"),
        UniqueConstraint("threads_account_id", "external_reply_id", name="uq_threads_comment_event_reply"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    threads_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("threads_account.id"), nullable=False
    )
    external_reply_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_media_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_parent_reply_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_from_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_from_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reply_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reply_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CommentEventStatus] = mapped_column(
        Enum(CommentEventStatus, name="comment_event_status"), nullable=False, default=CommentEventStatus.PENDING
    )
    status_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ThreadsReplyJob(Base, TimestampMixin):
    __tablename__ = "threads_reply_job"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_threads_reply_job_idempotency"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    comment_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads_comment_event.id"), nullable=False)
    threads_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads_account.id"), nullable=False)
    reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReplyJobStatus] = mapped_column(
        Enum(ReplyJobStatus, name="reply_job_status"), nullable=False, default=ReplyJobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_reply_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuotaBucket(Base):
    __tablename__ = "quota_bucket"
    __table_args__ = (
        UniqueConstraint(
            "instagram_account_id",
            "action_type",
            "bucket_type",
            "bucket_key",
            name="uq_quota_bucket",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instagram_account.id"), nullable=False
    )
    action_type: Mapped[CommentActionType] = mapped_column(
        Enum(CommentActionType, name="comment_action_type"), nullable=False
    )
    bucket_type: Mapped[QuotaBucketType] = mapped_column(
        Enum(QuotaBucketType, name="quota_bucket_type"), nullable=False
    )
    bucket_key: Mapped[str] = mapped_column(String(16), nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ContentSourceItem(Base, TimestampMixin):
    __tablename__ = "content_source_item"
    __table_args__ = (UniqueConstraint("topic", "source_url", name="uq_source_topic_url"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=50)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeeplinkCache(Base):
    __tablename__ = "deeplink_cache"

    original_url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    short_url: Mapped[str] = mapped_column(Text, nullable=False)
    vendor: Mapped[str] = mapped_column(String(20), nullable=False, default="COUPANG")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromptProfile(Base, TimestampMixin):
    __tablename__ = "prompt_profile"
    __table_args__ = (
        UniqueConstraint("channel", "account_ref", "version", name="uq_prompt_profile"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    channel: Mapped[ChannelType] = mapped_column(Enum(ChannelType, name="channel_type"), nullable=False)
    account_ref: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    disclosure_line: Mapped[str] = mapped_column(Text, nullable=False)
    hook_template_weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    style_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    banned_words: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ContentUnit(Base, TimestampMixin):
    __tablename__ = "content_unit"
    __table_args__ = (UniqueConstraint("biz_date", "slot_no", name="uq_content_unit_date_slot"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    biz_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    threads_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("threads_account.id"), nullable=True
    )
    instagram_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("instagram_account.id"), nullable=True
    )
    source_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_source_item.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    original_coupang_url: Mapped[str] = mapped_column(Text, nullable=False)
    coupang_short_url: Mapped[str] = mapped_column(Text, nullable=False)
    threads_body: Mapped[str] = mapped_column(Text, nullable=False)
    threads_first_reply: Mapped[str] = mapped_column(Text, nullable=False)
    instagram_caption: Mapped[str] = mapped_column(Text, nullable=False)
    slide_script: Mapped[dict] = mapped_column(JSONB, nullable=False)
    guardrail_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    threads_review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.PENDING.value, server_default=ReviewStatus.PENDING.value
    )
    instagram_review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.PENDING.value, server_default=ReviewStatus.PENDING.value
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status"), nullable=False, default=ReviewStatus.PENDING
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    duplicate_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    quality_score: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    generation_status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus, name="content_status"), nullable=False, default=ContentStatus.DRAFT
    )
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RenderedAsset(Base):
    __tablename__ = "rendered_asset"
    __table_args__ = (UniqueConstraint("content_unit_id", "slide_no", name="uq_rendered_asset"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_unit.id"), nullable=False)
    slide_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gcs_uri: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PostJob(Base, TimestampMixin):
    __tablename__ = "post_job"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_unit.id"), nullable=False)
    channel: Mapped[ChannelType] = mapped_column(Enum(ChannelType, name="channel_type"), nullable=False)
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, name="job_type"), nullable=False)
    account_ref: Mapped[uuid.UUID] = mapped_column(nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, default=JobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    cloud_task_name: Mapped[str | None] = mapped_column(String(256), unique=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ThreadsPost(Base, TimestampMixin):
    __tablename__ = "threads_post"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_unit.id"), nullable=False, unique=True
    )
    threads_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads_account.id"), nullable=False)
    root_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    first_reply_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    root_text: Mapped[str] = mapped_column(Text, nullable=False)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InstagramPost(Base, TimestampMixin):
    __tablename__ = "instagram_post"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_unit.id"), nullable=False, unique=True
    )
    instagram_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instagram_account.id"), nullable=False
    )
    media_container_ids: Mapped[dict] = mapped_column(JSONB, nullable=False)
    carousel_creation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    carousel_media_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ThreadsInsight(Base):
    __tablename__ = "threads_insight"
    __table_args__ = (UniqueConstraint("media_id", "captured_at", name="uq_threads_insight"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    threads_post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads_post.id"), nullable=False)
    media_id: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replies: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reposts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shares: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class InstagramInsight(Base):
    __tablename__ = "instagram_insight"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instagram_post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instagram_post.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reach: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    saves: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ImprovementRun(Base):
    __tablename__ = "improvement_run"
    __table_args__ = (UniqueConstraint("run_type", "run_date", name="uq_improvement_run"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_type: Mapped[ImproveRunType] = mapped_column(
        Enum(ImproveRunType, name="improve_run_type"), nullable=False
    )
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    before_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    after_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrendKeywordSnapshot(Base):
    __tablename__ = "trend_keyword_snapshot"
    __table_args__ = (
        UniqueConstraint("biz_date", "provider", "keyword", name="uq_trend_keyword_snapshot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    biz_date: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="NAVER")
    keyword: Mapped[str] = mapped_column(String(120), nullable=False)
    group_name: Mapped[str] = mapped_column(String(120), nullable=False)
    ratio: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    delta_ratio: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
